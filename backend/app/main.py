import logging
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import func, select

# PoolTimeoutError = 풀 고갈. 파이썬 빌트인 TimeoutError(=OSError 하위)와 **이름만 같고
# 계통이 완전히 다르다**(issubclass → False). 별칭 없이 들여오면 모듈 전역에서 빌트인을
# 조용히 가리므로 반드시 이름을 바꿔 받는다.
from sqlalchemy.exc import DataError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.orm import Session
from starlette.datastructures import Headers

from app.core.config import settings
from app.core.database import get_db
from app.core.ratelimit import limiter
from app.core.textguard import has_nul
from app.models.post import Post
from app.models.user import PUBLIC_BLOG_ROLES, User
from app.routers import (
    admin,
    ai,
    auth,
    comments,
    notifications,
    payments,
    posts,
    push,
    skin,
    subscriptions,
    uploads,
)
from app.services.cleanup import start_cleanup
from app.services.status import STALE_AFTER, get_history, get_latest, start_recorder

logger = logging.getLogger(__name__)

# 절대 운영에서 쓰면 안 되는 기본 SECRET_KEY (코드에 공개돼 있어 토큰 위조 가능)
_INSECURE_SECRET = "change-me-in-production"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 보안 가드: SECRET_KEY가 기본값이거나 너무 약하면 서버를 아예 띄우지 않음(fail-closed).
    # 이게 없으면 .env에 키를 빠뜨린 채 배포돼도 조용히 위험해짐(실제로 한 번 그랬음).
    if settings.secret_key in ("", _INSECURE_SECRET) or len(settings.secret_key) < 16:
        raise RuntimeError(
            "SECRET_KEY가 없거나 너무 약함. .env에 강력한 임의값을 설정해줘 "
            "(예: openssl rand -hex 32)."
        )
    # ORIGIN_SECRET은 헤더로 오가므로 ASCII여야 한다. 비ASCII면 비교 양쪽의 인코딩이
    # 갈려(헤더는 latin-1, 설정값은 utf-8) **어떤 요청도 통과하지 못한다** — 즉 사이트
    # 전체가 403인데 로그엔 아무 단서가 없다. 기동 때 터뜨려 배포 시점에 알게 한다.
    if not settings.origin_secret.isascii():
        raise RuntimeError(
            "ORIGIN_SECRET에 ASCII가 아닌 문자가 있음. 헤더로 전달되는 값이라 "
            "ASCII여야 한다 (예: openssl rand -hex 32)."
        )
    # 그런데 위 검사는 **빈 값을 못 잡는다** — `"".isascii()`는 True다. 비어 있으면
    # 아래 require_origin_secret 미들웨어가 통째로 건너뛴다(fail open). 로컬에선 그게
    # 의도지만(그래야 개발이 돌고, 켜는 순서가 성립한다), 프로드에서 그 상태는
    # **엣지 우회 차단이 꺼진 채 도는 것**이다 — 공격자가 자기 CloudFront 배포를
    # 우리 오리진에 겨누면 WAF·CSP·요청크기 함수를 전부 건너뛰고 /api/*에 닿는다.
    #
    # 이 실패는 밖에서 **아무 신호도 안 낸다.** 사이트가 멀쩡히 200이고, watch.sh의
    # 403 단서조차 안 뜬다(막히는 게 아니라 다 통과하니까). 반대 방향(값 불일치)은
    # 사이트가 통째로 죽어서 즉시 알지만, 이 방향은 영원히 조용하다.
    # SECRET_KEY·S3_BUCKET·PAYMENTS_REQUIRE_LIVE에 대해 이미 같은 모양을 막아뒀는데
    # **여기만 안 쓸려 있었다**(2026-08-11).
    #
    # 켜는 순서는 안 깨진다: ① terraform으로 CloudFront에 헤더를 붙이고 ② .env에
    # 같은 값을 넣는 순서라, 이 가드는 ② 시점에만 걸린다. 넣기 전에 프로드 에스크로
    # (SSM /blog/prod/env)에 64자로 실재하는 걸 확인했다 — 현행 서버는 안 죽는다.
    if settings.public_base_url.startswith("https://") and not settings.origin_secret:
        raise RuntimeError(
            "프로드인데 ORIGIN_SECRET이 비어 있다. 이 상태면 오리진 공유 시크릿 검사가 "
            "통째로 꺼져서, 공격자가 자기 CloudFront 배포로 오리진을 직접 때릴 수 있다"
            "(WAF·CSP 우회). 값은 terraform의 origin_secret과 같아야 한다 — "
            "에스크로(SSM /blog/prod/env)에 있다. 절차는 RECOVERY.md의 origin_secret 항목."
        )
    # 업로드 저장소 가드. S3_BUCKET이 비면 routers/uploads.py가 **예외 없이** 로컬 디스크로
    # 떨어져서, 정성 들인 503 방어를 통째로 건너뛰고 200 + CloudFront URL을 돌려준다.
    # 파일은 컨테이너 안에 있으므로 그 URL은 404이고 컨테이너를 갈면 사라진다.
    # 글쓴이는 업로드 성공으로 보고, 깨진 이미지는 발행 뒤 독자만 본다. 감시도 못 잡는다
    # (watch.sh는 원본/사본 **개수 비교**라 '원본이 안 늘어남'은 신호가 아니다).
    # 07-22 IAM 사고는 그래도 AccessDenied라도 났는데 이건 예외조차 없다 — 2026-08-10 심층검사.
    # 로컬 개발은 이 값이 비어 있는 게 정상이므로, 프로드 표식(PUBLIC_BASE_URL이 http로
    # 시작하지 않는 로컬 기본값이 아닌 경우)일 때만 막는다.
    if settings.public_base_url.startswith("https://") and not settings.s3_bucket:
        raise RuntimeError(
            "S3_BUCKET이 비어 있는데 PUBLIC_BASE_URL이 https다. 이 조합이면 업로드가 "
            "컨테이너 디스크에 저장되고 그 URL은 404가 된다. .env에 S3_BUCKET을 설정해줘."
        )
    # 결제 안전장치를 **기동 때** 확인한다. 지금은 요청 시점에만 본다(payments의 _guard_live)
    # — 그런데 그 검사는 payments_require_live가 True일 때만 돌고, 그 값의 코드 기본값은
    # False이며 시크릿키의 코드 기본값은 **실제 토스 테스트 키**다. 즉 .env에서 그 한 줄이
    # 빠지면 검사가 통째로 사라진 채 테스트 결제 승인이 그대로 Pro로 붙는다.
    # = "한 줄이 빠지면 조용히 공짜 Pro". 위 SECRET_KEY·S3_BUCKET에 대해 이미 같은 모양을
    # 막아뒀는데 결제만 빠져 있었다(2026-08-10 보안검사).
    # 회귀 경로가 가설이 아니다 — env_escrow/DR로 .env를 재조립하는 절차가 실재한다.
    #
    # **키의 종류는 여기서 보지 않는다.** 현행 운영이 바로 '라이브 전환은 안 했고 결제를
    # 꺼둔' 상태(require_live=true + 테스트 키 → 요청 시점 503)인데, 키까지 여기서 막으면
    # 지금 잘 돌고 있는 서버가 기동을 거부한다. 여기서 요구하는 건 "가드가 켜져 있는가"
    # 하나이고, 테스트/라이브 판정은 _guard_live()가 요청 시점에 정확히 한다.
    if settings.public_base_url.startswith("https://") and not settings.payments_require_live:
        raise RuntimeError(
            "프로드인데 PAYMENTS_REQUIRE_LIVE가 꺼져 있다. 이 상태면 코드 기본값인 토스 "
            "**테스트** 시크릿키로 승인이 붙어 공짜 Pro가 나간다. "
            ".env에 PAYMENTS_REQUIRE_LIVE=true 를 설정해줘."
        )
    # **앱 로거를 실제로 켠다.** 저장소 어디에도 basicConfig/dictConfig가 없어서
    # root 레벨이 WARNING이고 핸들러가 0개였다 — 즉 `logger.info(...)`가 **한 줄도
    # 안 나갔다.** 2026-08-11 동적 분석에서 실측으로 잡았다: 토큰 계량을 넣고
    # "AI 초안 완료: 입력=N 출력=M"을 찍게 했는데 도커 로그에 0건이었고,
    # 같은 이유로 cleanup의 "미인증 계정 N건 삭제"와 email의 "새 글 알림 N명 발송"도
    # 전부 무음이었다. **실패(warning/exception)는 보이고 성공·정황만 안 보이는**
    # 상태라, "조용한 실패를 읽을 수 있게 만든다"고 넣은 관측 장치가 정작 조용했다.
    #
    # uvicorn이 자기 로거만 설정하고 root는 안 건드리기 때문이다. force=True를 주는 건
    # uvicorn이 이미 붙여둔 핸들러와 겹쳐 같은 줄이 두 번 나오는 걸 막기 위해서다.
    # 컨테이너 로그는 max-size 10m × 3으로 회전하므로(compose) 양은 묶여 있다.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        force=True,
    )
    logging.getLogger("app").setLevel(logging.INFO)

    # 앱 기동 시 1분 간격 자가 점검 기록 시작 (업타임 집계용)
    start_recorder()
    # 미인증 계정 1시간 간격 자동 정리 시작
    start_cleanup()
    yield


# docs/redoc/openapi를 끈다. CloudFront는 `/api/*`만 오리진으로 보내므로 정상 경로로는
# 안 보이지만, 오리진 SG가 'CloudFront 엣지 전체'(prefix list)라 **공격자가 자기 배포를
# 만들어 직접 오리진을 때리면** 스키마가 통째로 노출된다. 끄는 데 드는 비용이 없다.
# 로컬 개발에서 필요하면 uvicorn을 직접 띄우고 이 인자를 빼면 된다.
app = FastAPI(
    title="Blog Platform API",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# 레이트 리밋: 한도 초과 시 429 응답 (가입/로그인 폭주 방어)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(OperationalError)
async def db_unavailable(request: Request, exc: OperationalError):
    """DB에 못 붙으면 500이 아니라 503으로 답한다.

    2026-07-28 카오스 훈련에서 DB를 내려보니, 글 목록·로그인·내 정보까지 전부
    `500 Internal Server Error`가 **text/plain**으로 나갔다. 문제가 셋이었다:
      · 프론트는 JSON을 기대하므로 파싱조차 못 한다
      · 500은 '이 요청이 잘못됐다'로 읽히지만 실제로는 '지금 서버가 못 한다'다
      · 프론트의 isAsleepStatus는 502/503/504만 '일시적 장애'로 안내한다 → 500은 그냥 빨간 에러

    503으로 바꾸면 이미 있는 안내 경로를 그대로 탄다. Retry-After도 붙여 '다시 오면 된다'를
    기계도 읽을 수 있게 한다.

    OperationalError는 '연결 못 함/끊김' 계열이다. 쿼리가 틀린 것(ProgrammingError)은
    여기 안 걸린다 — 그건 진짜 버그라 500이 맞다.
    """
    logger.warning("DB 접속 실패: %s", exc.orig or exc)
    return JSONResponse(
        {"detail": "일시적으로 서비스에 접속할 수 없어. 잠시 후 다시 시도해줘."},
        status_code=503,
        headers={"Retry-After": "30"},
    )


@app.exception_handler(PoolTimeoutError)
async def db_pool_exhausted(request: Request, exc: PoolTimeoutError):
    """커넥션 풀이 다 찼을 때 503. **DB는 멀쩡하다** — 우리 쪽 커넥션이 없는 것이다.

    2026-08-10 심층검사: 위 db_unavailable이 잡는 OperationalError에 풀 고갈은 **안 걸린다**
    (sqlalchemy.exc.TimeoutError는 SQLAlchemyError 직계지 OperationalError 하위가 아니다).
    그래서 위 주석이 "07-28에 고쳤다"고 적은 500 text/plain이 **이 입구에만 그대로 남아**
    있었다. 실측으로 재현했다(pool_size=1에 동시 요청 → 500 text/plain).

    함정 셋을 실측으로 확인했으니 고치기 전에 읽을 것:
      ① **위 핸들러를 재사용하면 안 된다.** db_unavailable은 `exc.orig`를 읽는데 그건
         DBAPIError에만 있는 속성이라, 이 예외에 물리면 핸들러가 자기 안에서
         AttributeError로 터져 **결국 똑같이 500 text/plain**이 나간다.
      ② `@app.exception_handler((OperationalError, PoolTimeoutError))`처럼 튜플로 묶는 것도
         안 된다. 등록은 에러 없이 통과하지만 Starlette은 type(exc).__mro__로만 찾으므로
         튜플 키는 **영원히 매치되지 않는다** — 조용히 아무 일도 안 일어난다.
      ③ SQLAlchemyError로 넓히지 말 것. ProgrammingError·IntegrityError까지 503이 되어
         '코드가 틀렸다'가 '서버가 지금 못 한다'로 둔갑한다(위 핸들러 주석과 같은 이유).

    로그 문구도 분리한다. '접속 실패'라고 적으면 사고 때 사람을 DB로 보내는데, 실제로 볼 곳은
    커넥션을 오래 쥔 요청이다. Retry-After도 짧게 준다 — 풀은 몇 초면 빈다.
    """
    logger.warning("DB 커넥션 풀 고갈: %s", exc)
    return JSONResponse(
        {"detail": "지금 요청이 몰려 있어. 잠시 후 다시 시도해줘."},
        status_code=503,
        headers={"Retry-After": "5"},
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    """검증 실패는 422 JSON으로 — **입력값을 되돌려주지 않는다.**

    FastAPI 기본 핸들러는 `detail[].input`에 문제의 입력을 그대로 담아 되돌려준다.
    그런데 starlette의 JSONResponse는 `json.dumps(..., allow_nan=False)`라
    **`Infinity`/`NaN`을 인코딩하지 못한다** → 422를 만들다가 ValueError로 터져
    `500 text/plain`이 나갔다. 고아 서로게이트(`\\ud800`)는 UTF-8 인코딩 단계에서 같은 일을 낸다.

    피해가 문법 오류에 그치지 않았다(2026-08-12 실측):
      - **무인증**이고 **모든 JSON 본문 엔드포인트**가 해당된다(숫자 필드가 아니어도 난다).
      - **레이트리밋을 우회한다.** 검증은 slowapi 데코레이터보다 먼저 도는 계층이라
        `{"email":1e999}` 25연발이 **500 × 25**(429 0건)였다. 정상 값 대조군은 401×10 → 429×15.
      - 프론트는 JSON을 기대하므로 text/plain 500은 파싱조차 못 한다.

    그래서 `input`을 떼고 `loc`·`msg`·`type`만 돌려준다. 그 셋으로 프론트가 어느 필드가
    왜 틀렸는지 그리기에 충분하고, **입력을 그대로 반사하지 않는 게 보안상으로도 낫다**.
    """
    safe = [
        {"loc": list(e.get("loc", ())), "msg": str(e.get("msg", "")), "type": str(e.get("type", ""))}
        for e in exc.errors()
    ]
    return JSONResponse({"detail": safe}, status_code=422)


@app.exception_handler(DataError)
async def db_bad_value(request: Request, exc: DataError):
    """DB가 '이 값은 담을 수 없다'고 거절한 것 → 400 JSON. 서버 잘못이 아니다.

    **라우터마다 막지 않고 여기서 받는 이유**: 같은 계열이 계속 새로 생기기 때문이다.
    2026-08-12 오전에 `list_posts`의 `q`·`tag`에 NUL 가드를 넣었는데, 같은 날 오후 검사가
    **같은 병이 다섯 라우터에 그대로 남아 있는 것**을 찾았다(익명 댓글 `content`,
    글 `title`·`tags`, 푸시 `endpoint`, 결제 `order_id`). 필드마다 막는 접근은
    필드가 늘 때마다 다시 샌다 — 이 저장소가 '고친 자리 옆의 안 쓸린 입구'라고 부르는 모양이다.

    범위: `DataError`만. 이건 **값 자체가 부적합**할 때만 나온다(NUL 바이트, 고아 서로게이트,
    bigint 범위 초과, 잘못된 날짜 리터럴). `ProgrammingError`·`IntegrityError`로 넓히면
    '코드가 틀렸다'와 '제약을 어겼다'가 '입력이 나쁘다'로 둔갑한다 — 위 두 핸들러와 같은 이유다.

    원인 문자열은 로그에만 남긴다(스키마·컬럼명을 밖에 알려줄 이유가 없다).

    그런데 그 '원인 문자열'에 **바인딩 값이 딸려 온다**. SQLAlchemy는 예외를 문자열로
    만들 때 실행한 SQL과 파라미터를 함께 붙이므로, 여기서 `exc`를 통째로 찍으면
    사용자가 보낸 원문(이메일·글 본문 등)이 액세스 로그에 그대로 남았다.
    위 db_unavailable이 `exc.orig`만 찍는 것이 같은 함정을 이미 한 번 피한 자리인데
    이 핸들러만 안 쓸려 있었다(2026-09-02에 확인).
    막는 자리는 여기가 아니라 **엔진**이다 — core/database.py에 `hide_parameters=True`를
    줬다. 예외를 문자열로 만드는 자리는 여기 말고도 또 생기므로(위 '고친 자리 옆의
    안 쓸린 입구'와 같은 판단), 필드가 아니라 입구에서 막는 것과 같은 이유다.
    """
    logger.warning("DB가 값을 거절: %s", exc)
    return JSONResponse({"detail": "입력에 사용할 수 없는 값이 있어."}, status_code=400)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite 개발 서버
    allow_methods=["*"],
    allow_headers=["*"],
)

# 요청 본문 크기 상한 (t2.micro 메모리 고갈 DoS 방지). **경로마다 다르다**(2026-09-02).
#
# 왜 둘인가. 예전엔 전 경로 6MB 하나였다. 6MB는 이미지 업로드(5MB, routers/uploads.py의
# MAX_BYTES)를 통과시키려고 잡은 값인데, 그 값이 `/api/auth/login`·익명 댓글·
# `/api/auth/forgot-password` 같은 **무인증 JSON 경로**에도 그대로 걸려 있었다.
# JSON 본문은 파싱 전에 통째로 메모리에 올라오고 slowapi 레이트리밋은 그 **뒤**에 돈다 —
# 한도에 걸리기 전에 이미 5.9MB를 받는다는 뜻이다. 운영은 t2.micro(호스트 957MB·스왑 0)에
# backend 컨테이너 400m 상한이라 그런 연결 수십 개면 OOM으로 컨테이너가 죽는다.
# 업로드 때문에 넓힌 문이 업로드와 무관한 입구까지 같이 넓혀둔 모양이다.
#
# 512KB의 근거 — **정상 JSON 요청 중 가장 큰 것을 스키마에서 실제로 세어봤다**:
#   · POST/PUT /api/posts : content 50,000자(schemas/post.py CONTENT_MAX) + 제목 200
#     + 태그 10×30 + 커버 500 + 연재 100 ≈ 51,100자. 이게 최대다.
#   · PUT /api/skin       : custom_css 50,000자(schemas/user.py CSS_MAX)
#   · 나머지(로그인·댓글 2,000자·AI 메모 5,000자·푸시 구독)는 자릿수가 다르다.
#   브라우저가 보내는 모양(JSON.stringify는 비ASCII를 이스케이프하지 않는다) 기준으로
#   한글 3바이트/자 ≈ 150KB, 전부 이모지(4바이트/자)여도 ≈ 205KB다. 512KB는 그 2.5배다.
#
# 엣지와 같은 값이기도 하다 — terraform/reqsize-function.js가 같은 정책(업로드만
# 6291456, 나머지 524288)을 Content-Length로 본다. 두 곳이 갈리면 "엣지는 통과시켰는데
# 앱이 413"(또는 반대)이 되어, 어느 층이 막았는지 로그만 보고는 못 가린다. 한쪽을
# 고치면 다른 쪽도 같이 고쳐야 한다.
#
# **안 덮는 경계도 적어둔다**(재보고 고른 것이지 잊은 것이 아니다): ensure_ascii로
# 이스케이프하는 클라이언트(파이썬 requests의 `json=`)가 50,000자를 **전부 BMP 밖
# 문자**로 보내면 대리쌍 이스케이프라 12바이트/자 ≈ 600KB가 되어 여기 걸린다.
# 브라우저에서는 만들어질 수 없는 모양이고, 걸려도 413이라 조용하지 않다. 상한을 더
# 올려 그 경우까지 덮기보다 이 경계를 적어두는 쪽을 골랐다 — 상한을 1MB로 하면 위
# OOM 계산에서 남는 여유가 절반으로 준다.
MAX_BODY_BYTES = 512 * 1024

# 업로드만 예외로 6MB(5MB 파일 + multipart 경계·헤더 여유). **정확히 이 한 경로만**이다.
UPLOAD_PATH = "/api/upload"
MAX_UPLOAD_BODY_BYTES = 6 * 1024 * 1024


def _mb(n: int) -> str:
    """413 문구에 쓸 MB 표기. 정수 나눗셈(`n // (1024*1024)`)을 그대로 두면 512KB가
    **'최대 0MB'**가 되어 문구가 거짓말을 한다. 문장은 그대로 두고 숫자만 맞춘다."""
    return f"{n / (1024 * 1024):g}"


async def _no_body() -> dict:
    # 413을 내보낼 때 Response에 넘길 자리 채우기용. Starlette의 Response.__call__은
    # receive를 쓰지 않지만 시그니처가 요구한다.
    return {"type": "http.request", "body": b"", "more_body": False}


class BodySizeLimitMiddleware:
    """요청 본문 크기 상한. **Content-Length만 보면 안 된다.**

    2026-07-30 심층검사에서 실측한 것: 같은 20MB 본문을
      · `Content-Length: 20000035`로 보내면 → 413, 업로드 0바이트 (막힘)
      · `Transfer-Encoding: chunked`로 보내면 → 20,002,488바이트가 전부 앱까지 들어와
        7.7초 동안 메모리에 버퍼링된 뒤 422 (**우회**)
    로그인처럼 무인증으로 부를 수 있는 라우트에서도 되므로, 큰 chunked 요청 몇 개면
    t2.micro의 메모리를 고갈시킬 수 있다.

    앞단도 못 막는다 —
      · CloudFront Function은 본문을 볼 수 없어 같은 Content-Length 검사뿐이다
        (terraform/reqsize-function.js).
      · WAF의 `SizeRestrictions_BODY`는 **Count로 내려가 있다**(감시만). 그 규칙은 8KB
        초과 본문을 막는데 그러면 이미지 업로드가 죽으므로, 되돌리는 게 답이 아니다.
    그래서 방어는 여기서 해야 하고, 여기서는 '수신 스트림을 세는' 방식이어야 한다.

    BaseHTTPMiddleware(@app.middleware) 대신 순수 ASGI로 쓴 이유: 본문이 앱에 닿기 전에
    receive 채널을 우리가 쥐고 있어야 세면서 끊을 수 있다.
    """

    def __init__(self, app, max_bytes: int, upload_max_bytes: int | None = None) -> None:
        self.app = app
        self.max_bytes = max_bytes
        # 업로드 상한을 안 주면 예전처럼 전 경로 한 값으로 돈다. ASGI 레벨 테스트가
        # 그 모양(상한 하나)으로 스트림 동작을 검증하므로 기본값을 남겨둔다.
        self.upload_max_bytes = max_bytes if upload_max_bytes is None else upload_max_bytes

    @staticmethod
    def _has_authorization(scope) -> bool:
        """Authorization 헤더가 붙어 있는가. **값을 검증하지는 않는다.**

        여기는 라우팅 전이라 토큰을 풀 수단이 없다(DB 세션도 의존성도 아직 없다).
        검증은 `require_writer` 가 하고, 여기서는 '큰 본문을 받아줄 후보인가'만 본다.
        """
        for name, value in scope.get("headers", []):
            if name == b"authorization" and value.strip():
                return True
        return False

    def _limit_for(self, scope) -> int:
        """이 요청에 걸 상한. **판정은 ASGI scope의 path로 한다**(2026-09-02).

        `scope["path"]`에는 쿼리스트링이 안 들어간다(그건 `query_string`에 따로 있다).
        그래서 여기서 접을 것은 후행 슬래시뿐이고, 비교는 **정확히 같은가**로 한다 —
        접두사 매칭(`startswith`)이면 `/api/uploadsomething` 같은 경로가 6MB를 얻는다.
        무인증 경로 하나만 잘못 넓혀도 위 OOM 계산이 그대로 되살아난다.

        2026-09-05: **인증 헤더가 없으면 업로드 경로도 6MB를 안 준다.** 09-02에 상한을
        경로별로 쪼갤 때 조건이 경로 하나뿐이라, 로그인하지 않은 요청도 6MB를 받았다.
        업로드는 `require_writer` 로 잠겨 있어 그런 요청의 결말은 401·403인데, FastAPI는
        **본문을 다 읽은 뒤에** 의존성을 푼다(`routing.py` 의 `await request.form()` 이
        `solve_dependencies` 보다 먼저다). 게다가 엔드포인트 함수 안에 있는
        `@limiter.limit("30/hour")` 도 그 경로에서는 실행되지 않아 아무 한도가 없다.
        즉 거절될 요청 하나가 6MB를 먼저 먹었다(2026-09-04 검사 SEC-01).

        ⚠️ **이건 헤더 위조까지 막지는 못한다.** `Authorization: Bearer x` 한 줄이면
        다시 6MB 후보가 된다. 여기서 없어지는 것은 '아무것도 안 붙이고 던지는' 경로이고,
        진짜 상한은 아래 chunked 갈래가 본문을 메모리 리스트가 아니라 디스크로 흘려보낼
        때 생긴다. 그건 업로드 경로를 다시 쓰는 일이라 이번에 하지 않았다.
        """
        path = scope.get("path", "")
        if path.rstrip("/") == UPLOAD_PATH and self._has_authorization(scope):
            return self.upload_max_bytes
        return self.max_bytes

    async def _too_large(self, scope, send, limit: int) -> None:
        # 문구는 예전 것 그대로다. 상한만 경로에서 뽑아 쓴다.
        response = JSONResponse(
            {"detail": f"요청 본문이 너무 큽니다 (최대 {_mb(limit)}MB)"},
            status_code=413,
        )
        await response(scope, _no_body, send)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        # Content-Length 경로와 chunked 버퍼링 경로가 **같은 값**을 봐야 한다.
        # 한쪽만 경로별로 만들면 넓은 쪽이 그대로 우회로가 된다(07-30에 배운 그 모양).
        limit = self._limit_for(scope)

        cl = Headers(scope=scope).get("content-length")
        if cl is not None:
            try:
                declared = int(cl)
            except ValueError:
                declared = None  # 깨진 CL은 판단 근거가 아니다 → 아래 스트림 검사로 넘긴다
            if declared is not None:
                # 가장 싼 경로: 본문을 한 바이트도 읽지 않고 판정한다.
                if declared > limit:
                    return await self._too_large(scope, send, limit)
                return await self.app(scope, receive, send)

        # CL이 없다(chunked) → 상한까지만 버퍼링하며 읽고, 넘는 순간 앱을 부르지 않고 끊는다.
        # 버퍼가 그 경로의 상한(업로드 6MB, 그 외 512KB)으로 묶이므로 노출은 위 CL 경로와 같다.
        buffered: list[dict] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                buffered.append(message)  # http.disconnect 등은 그대로 전달
                break
            total += len(message.get("body", b""))
            if total > limit:
                return await self._too_large(scope, send, limit)
            buffered.append(message)
            if not message.get("more_body", False):
                break

        queued = iter(buffered)

        async def replay():
            # 먼저 우리가 읽어둔 것을 되돌려주고, 다 쓰면 원래 채널로 넘긴다.
            message = next(queued, None)
            return message if message is not None else await receive()

        await self.app(scope, replay, send)


app.add_middleware(
    BodySizeLimitMiddleware,
    max_bytes=MAX_BODY_BYTES,
    upload_max_bytes=MAX_UPLOAD_BODY_BYTES,
)


# 헬스체크만 시크릿 검사에서 뺀다. 이 둘은 CloudFront를 거치지 않고 오리진을 직접
# 찌르는 정상 트래픽이라, 빼지 않으면 컨테이너가 영원히 unhealthy가 되어 배포가 멈춘다.
#   ① 도커 헬스체크: 컨테이너 안에서 127.0.0.1:8000/api/health
#   ② ALB 대상그룹 헬스체크(ecs 모드): ALB가 태스크로 직접 /api/health
# 내용이 {"status":"ok"}뿐이라 열어둬도 새는 정보가 없다.
ORIGIN_SECRET_EXEMPT = frozenset({"/api/health"})


# ⚠️ 이 미들웨어는 BodySizeLimitMiddleware **뒤에** 등록돼야 한다. Starlette은 나중에 등록된
# 것이 바깥쪽이라, 그래야 시크릿 검사가 가장 먼저 돈다. 순서가 뒤집히면 우회 요청이
# 413(본문 초과)을 먼저 받아 우리 요청 크기 상한을 알려주게 된다. 둘 다 헤더만 보는
# 검사라 비용은 같으니, 아무것도 안 알려주는 쪽이 낫다.
@app.middleware("http")
async def require_origin_secret(request: Request, call_next):
    """CloudFront가 붙인 공유 시크릿이 없으면 403.

    막는 것은 '남의 CloudFront 배포로 우리 오리진을 직접 때리는 우회'다. 오리진 SG가
    엣지 전체(prefix list)를 받으므로, SG만으로는 우리 배포와 남의 배포를 구분할 수 없다.

    설정이 비어 있으면 통과시킨다(fail open). 이건 인증이 아니라 우회 차단이고, 진짜
    인증·권한은 라우터의 JWT 검사가 이것과 무관하게 그대로 한다. 무엇보다 여기서 fail
    closed로 굴면 켜는 순서를 한 번만 틀려도(백엔드를 CloudFront보다 먼저) /api/*가
    통째로 막힌다. 켜고 끄는 순서는 terraform/variables.tf의 origin_secret에 적어뒀다.

    ⚠️ 이 403은 밖에서도 403으로 보인다. (2026-08-10 정정) 예전엔 여기에
    "custom_error_response가 200 /index.html로 바꾸므로 403으로 안 보인다"고 적혀
    있었는데, 그 블록은 2026-07-28에 제거됐다(terraform/cloudfront.tf, 라이브
    CustomErrorResponses.Quantity = 0 실측). 같은 거짓이 RECOVERY.md·variables.tf에도
    있어서 셋을 함께 고쳤다 — 재해 중에 없는 증상을 찾게 만드는 서술이었다.
    """
    expected = settings.origin_secret
    if expected and request.url.path not in ORIGIN_SECRET_EXEMPT:
        got = request.headers.get("x-origin-secret", "")
        # 상수시간 비교 — 길이가 달라도 조기 반환하지 않는다.
        # **bytes로 넘기는 게 중요하다.** compare_digest는 str을 받으면 비ASCII 문자에서
        # TypeError를 던진다. Starlette은 헤더를 latin-1로 디코드하므로 공격자가 0x80~0xFF
        # 바이트 하나만 넣어도 이 검사가 403 대신 500으로 죽는다(검증: 실제 재현함).
        # 우회는 아니지만 — 예외는 call_next 전에 나므로 요청은 라우터에 닿지 않는다 —
        # 차단 장치가 스스로 터지는 건 이 검사에 기대하는 동작이 아니다.
        if not secrets.compare_digest(got.encode("latin-1"), expected.encode()):
            return JSONResponse({"detail": "Forbidden"}, status_code=403)
    return await call_next(request)


# 모든 API 라우트를 /api 아래로 (CloudFront가 /api/*를 EC2로 라우팅 → HTTPS 통일)
app.include_router(auth.router, prefix="/api")
app.include_router(posts.router, prefix="/api")
app.include_router(comments.router, prefix="/api")
app.include_router(subscriptions.router, prefix="/api")
app.include_router(uploads.router, prefix="/api")
app.include_router(ai.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(payments.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")
app.include_router(push.router, prefix="/api")
app.include_router(skin.router, prefix="/api")

# 업로드된 이미지 파일 서빙: GET /uploads/<파일명> → uploads/ 폴더
# ⚠️ 이건 **로컬 개발용 폴백**이다. 운영에서는 S3_BUCKET이 설정돼 있어 이미지가 S3에
# 저장되고(routers/uploads.py), CloudFront의 /uploads/* 전용 동작은 2026-06-26에
# 제거돼 기본 S3 오리진이 직접 서빙한다 — 즉 운영 트래픽은 이 마운트를 타지 않는다.
# 폴더가 없으면 마운트하지 않는다. StaticFiles는 없는 디렉터리에 RuntimeError를 던지는데,
# 그러면 **import가 실패해 컨테이너가 영원히 unhealthy**가 된다(routers/uploads.py 윗주석의
# 그 고장이다). uploads.py는 mkdir 실패를 이미 '넘어간다'로 처리하는데 여기만 무조건
# 마운트해서 의도가 어긋나 있었다 — 폴백이 없는 것과 앱이 안 뜨는 것은 다른 무게다.
if uploads.UPLOAD_DIR.is_dir():
    app.mount("/uploads", StaticFiles(directory=uploads.UPLOAD_DIR), name="uploads")
else:
    logger.warning("uploads/ 가 없어 /uploads 정적 서빙을 건너뛴다 — 이미지는 S3에서 온다")


# ⚠️ **여기엔 레이트리밋을 걸지 않는다. 일부러다.**
# 2026-08-27 훈련에서 "무인증 + 리밋 없는 GET" 전수 조사에 이 줄이 걸렸는데, 나머지
# 다섯과 성격이 다르다. 이건 사용자 경로가 아니라 **감시 경로**다 —
# docker-compose 의 healthcheck(30초마다)와 scripts/watch.sh(매시)가 이걸 부른다.
# 한도를 걸면 부하가 몰린 순간, 그러니까 상태를 가장 알아야 하는 순간에 429 가 나가고
# 도커가 컨테이너를 unhealthy 로 판정해 재시작한다. 방어가 사고를 만든다.
# 비용도 0이다(DB 를 안 본다 — 그건 07-28·08-26이 '일부러 안 고칠 것'으로 남긴 선택이다).
@app.get("/api/health")
def health_check():
    return {"status": "ok"}


# 무인증 공개 경로 셋(`/api/skin`·`/api/blog-owner`·`/api/authors/{h}`)에 넉넉한 한도를
# 건다. 셋 다 `/@handle` 화면이 첫 페인트 전에 부르고 전부 DB 조회다. CloudFront의
# `/api/*`는 CachingDisabled라 엣지에서 흡수되는 게 0이고 WAF에도 rate 룰이 없어서,
# 노트북 한 대로 t2.micro 크레딧을 태울 수 있었다(2026-08-19 보안검사, 44 req/s 실측).
# 한도가 높은 이유는 skin.py 주석에 적었다 — 낮게 걸면 정상 방문자가 먼저 걸린다.
@app.get("/api/blog-owner")
@limiter.limit("120/minute")
def blog_owner(request: Request, db: Session = Depends(get_db)):
    # 이 블로그의 주인(관리자). 프론트의 '이 블로그 구독' 버튼이 이 id를 구독함.
    #
    # ⚠️ **이메일에서 이름을 유도하지 않는다.** 2026-08-10 보안검사: 예전엔
    # `owner.email.split("@")[0]`을 무인증·무제한으로 반환했다. admin은 단 하나이고
    # 발신 도메인이 공개 제공자임이 config에 적혀 있어, 로컬파트만 알면 **전체 주소가
    # 완성된다** — register가 애써 막은 계정 열거를 가장 값나가는 계정에서 무효화하는
    # 셈이었다. 게다가 그 값이 익명 댓글 사칭의 재료로도 쓰였다(같은 검사).
    # display_name이 없으면 None을 준다. 프론트(Sidebar)에 이미 폴백 문자열이 있어
    # 화면 손실이 없다 — 이메일로 되돌아가는 경로를 아예 두지 않는 게 요점이다.
    owner = db.scalar(select(User).where(User.role == "admin").order_by(User.id))
    if owner is None:
        return {"id": None, "name": None}
    return {"id": owner.id, "name": owner.display_name}


@app.get("/api/authors/{handle}")
@limiter.limit("120/minute")
def author_profile(request: Request, handle: str, db: Session = Depends(get_db)):
    """`/@handle` 화면이 그릴 사람 정보. **무인증**이다(공개 블로그니까).

    돌려주는 것은 화면에 이미 보이는 것뿐이다 — 표시명·핸들·공개 글 수. 이메일은
    절대 안 나간다(2026-08-10 보안검사에서 끊은 경로다). display_name이 없으면 핸들을
    이름으로 쓴다. 이메일로 되돌아가는 폴백은 두지 않는다.

    핸들이 없으면 404다. 스킨(GET /api/skin?handle=)이 없는 핸들에 빈 값을 주는 것과
    다른 이유: 저건 장식이라 없어도 화면이 그려지지만, 이건 **그 화면이 존재하는가**에
    대한 답이라 없으면 없다고 해야 한다. 아니면 아무 주소나 빈 블로그로 열린다.

    글 수는 공개 글만 센다. 로그인 여부에 따라 숫자가 달라지면 '몇 편 있는 블로그인가'가
    보는 사람마다 달라지고, 비공개 글의 존재가 숫자로 새어 나간다.
    """
    # NUL이 들어오면 psycopg2가 DB에 닿기 전에 던져 **무인증 500**이 된다(2026-08-19).
    # 여기서는 404가 맞다 — 이 응답은 '그 화면이 존재하는가'에 대한 답이고,
    # 없는 핸들과 쓸 수 없는 핸들은 그 질문에 같은 답을 준다.
    if has_nul(handle):
        raise HTTPException(status_code=404, detail="그런 블로그가 없어")
    # 역할 조건이 붙어 있다 — 차단·승인취소된 계정의 블로그는 **없는 것**이 된다.
    # 셋(authors·skin·posts)이 같은 규칙을 봐야 회수가 통째로 듣는다.
    u = db.scalar(
        select(User).where(
            func.lower(User.handle) == handle.strip().lower(),
            User.role.in_(PUBLIC_BLOG_ROLES),
        )
    )
    if u is None:
        raise HTTPException(status_code=404, detail="그런 블로그가 없어")
    n = db.scalar(
        select(func.count())
        .select_from(Post)
        .where(Post.owner_id == u.id, Post.visibility == "public")
    )
    return {"handle": u.handle, "name": u.display_name or u.handle, "posts": n or 0}


@app.get("/api/status")
@limiter.limit("30/minute")  # 무인증 남용 방지 (이제 캐시라 가볍지만 유지)
def status(request: Request):
    # 백그라운드가 1분마다 갱신한 캐시를 반환 (매 호출 라이브 점검·SMTP 연결 안 함)
    c = get_latest()
    # 옛 캐시(at 없음)로도 안 깨지게 폴백을 둔다. 폴백이면 나이는 0이다 —
    # 모르는 것을 '낡았다'고 단언하지 않는다.
    raw_at = c.get("at")
    checked_at = datetime.fromisoformat(raw_at) if raw_at else datetime.now(UTC)
    age = max(0, int((datetime.now(UTC) - checked_at).total_seconds()))
    return {
        "backend": "ok" if c["backend_ok"] else "down",
        "database": "ok" if c["database_ok"] else "down",
        "mail": "ok" if c["mail_ok"] else "down",
        # 폴백을 두지 않는다. 처음엔 `c.get("disk_ok", True)`로 두고 "기동 직후 옛 모양을
        # 줄 수 있다"고 적었는데 **그 주석이 거짓이었다**(2026-08-10, 같은 날 보안검사에서 지적).
        # _latest는 프로세스 내 메모리 캐시라 이 프로세스의 run_checks()가 넣은 값뿐이고,
        # 캐시가 없으면 get_latest()가 run_checks()를 직접 부른다 — run_checks는 항상
        # disk_ok를 넣는다. 즉 그 폴백은 **도달 불가능한 죽은 코드**였고, 기본값 True는
        # status.py가 "못 쟀으면 초록으로 넘기지 않는다"며 False로 잡은 방침과 정반대였다.
        # 없는 키로 KeyError가 나는 게 맞다 — 그건 이 응답이 조립되는 계약이 깨졌다는 뜻이다.
        "disk": "ok" if c["disk_ok"] else "down",
        "stats": {"posts": c["posts"], "subscribers": c["subscribers"]},
        # 이 점검이 **실제로 돈** 시각. 호출 시각을 찍으면 최대 60초 낡은 캐시가
        # 방금 잰 것처럼 보인다(2026-07-28 카오스 훈련). 사고 중 오판을 부르는 거짓이다.
        # 옛 캐시(at 없음)로도 안 깨지게 폴백을 둔다.
        "checked_at": checked_at.isoformat(),
        # 이 응답을 믿어도 되는가. **판정은 서버가 한다** (services/status.py의
        # STALE_AFTER 주석). 화면이 각자 임계를 정하면 상태 페이지와 watch.sh 가
        # 같은 순간에 다른 답을 낸다. 08-27 훈련이 잡은 "884초 동안 ok"의 나머지
        # 절반이 이 자리다 — 그때 값이 안 늙는 건 코드로 닫았는데, 낡은 값을
        # **낡았다고 말하는** 장치는 없었다.
        "checked_age_seconds": age,
        "stale": age > STALE_AFTER,
    }


@app.get("/api/status/history")
@limiter.limit("30/minute")  # 무인증 + 매 호출 DB 집계 쿼리 → 남용 시 DB 부하 방지
def status_history(request: Request, days: int = 30):
    # 최근 N일 일별 업타임 (업타임 페이지가 사용). 범위 1~90일로 제한
    days = max(1, min(days, 90))
    return get_history(days)

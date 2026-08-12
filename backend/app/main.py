import logging
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import select

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
from app.models.user import User
from app.routers import (
    admin,
    ai,
    auth,
    comments,
    notifications,
    payments,
    posts,
    push,
    subscribers,
    subscriptions,
    uploads,
)
from app.services.cleanup import start_cleanup
from app.services.status import get_history, get_latest, start_recorder

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
    """
    logger.warning("DB가 값을 거절: %s", exc)
    return JSONResponse({"detail": "입력에 사용할 수 없는 값이 있어."}, status_code=400)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite 개발 서버
    allow_methods=["*"],
    allow_headers=["*"],
)

# 요청 본문 크기 상한 (t2.micro 메모리 고갈 DoS 방지).
# 이미지 업로드(5MB)는 통과하도록 6MB.
MAX_BODY_BYTES = 6 * 1024 * 1024


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

    def __init__(self, app, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def _too_large(self, scope, send) -> None:
        response = JSONResponse(
            {"detail": f"요청 본문이 너무 큽니다 (최대 {self.max_bytes // (1024 * 1024)}MB)"},
            status_code=413,
        )
        await response(scope, _no_body, send)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        cl = Headers(scope=scope).get("content-length")
        if cl is not None:
            try:
                declared = int(cl)
            except ValueError:
                declared = None  # 깨진 CL은 판단 근거가 아니다 → 아래 스트림 검사로 넘긴다
            if declared is not None:
                # 가장 싼 경로: 본문을 한 바이트도 읽지 않고 판정한다.
                if declared > self.max_bytes:
                    return await self._too_large(scope, send)
                return await self.app(scope, receive, send)

        # CL이 없다(chunked) → 상한까지만 버퍼링하며 읽고, 넘는 순간 앱을 부르지 않고 끊는다.
        # 버퍼가 상한(6MB)으로 묶이므로 노출은 위 CL 경로와 같다.
        buffered: list[dict] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                buffered.append(message)  # http.disconnect 등은 그대로 전달
                break
            total += len(message.get("body", b""))
            if total > self.max_bytes:
                return await self._too_large(scope, send)
            buffered.append(message)
            if not message.get("more_body", False):
                break

        queued = iter(buffered)

        async def replay():
            # 먼저 우리가 읽어둔 것을 되돌려주고, 다 쓰면 원래 채널로 넘긴다.
            message = next(queued, None)
            return message if message is not None else await receive()

        await self.app(scope, replay, send)


app.add_middleware(BodySizeLimitMiddleware, max_bytes=MAX_BODY_BYTES)


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
app.include_router(subscribers.router, prefix="/api")
app.include_router(comments.router, prefix="/api")
app.include_router(subscriptions.router, prefix="/api")
app.include_router(uploads.router, prefix="/api")
app.include_router(ai.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(payments.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")
app.include_router(push.router, prefix="/api")

# 업로드된 이미지 파일 서빙: GET /uploads/<파일명> → uploads/ 폴더
# ⚠️ 이건 **로컬 개발용 폴백**이다. 운영에서는 S3_BUCKET이 설정돼 있어 이미지가 S3에
# 저장되고(routers/uploads.py), CloudFront의 /uploads/* 전용 동작은 2026-06-26에
# 제거돼 기본 S3 오리진이 직접 서빙한다 — 즉 운영 트래픽은 이 마운트를 타지 않는다.
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")


@app.get("/api/health")
def health_check():
    return {"status": "ok"}


@app.get("/api/blog-owner")
def blog_owner(db: Session = Depends(get_db)):
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


@app.get("/api/status")
@limiter.limit("30/minute")  # 무인증 남용 방지 (이제 캐시라 가볍지만 유지)
def status(request: Request):
    # 백그라운드가 1분마다 갱신한 캐시를 반환 (매 호출 라이브 점검·SMTP 연결 안 함)
    c = get_latest()
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
        "checked_at": c.get("at") or datetime.now(UTC).isoformat(),
    }


@app.get("/api/status/history")
@limiter.limit("30/minute")  # 무인증 + 매 호출 DB 집계 쿼리 → 남용 시 DB 부하 방지
def status_history(request: Request, days: int = 30):
    # 최근 N일 일별 업타임 (업타임 페이지가 사용). 범위 1~90일로 제한
    days = max(1, min(days, 90))
    return get_history(days)

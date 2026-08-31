import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import require_writer
from app.core.ratelimit import limiter
from app.models.user import User

logger = logging.getLogger(__name__)

# POST는 /upload(단수), 저장된 파일 서빙은 /uploads/<파일>(StaticFiles)로 분리
router = APIRouter(prefix="/upload", tags=["uploads"])

# 로컬 개발용 저장 폴더. 운영은 S3_BUCKET이 설정돼 있어 아래에서 S3로 올린다
# (2026-06-26에 이전 완료 — 인스턴스를 교체해도 이미지가 안 사라지게).
UPLOAD_DIR = Path("uploads")

# ⚠️ **import 단계에서 죽으면 안 된다.** 예전엔 여기서 곧바로 mkdir을 했는데, 그 한 줄이
# **새로 클론한 사람의 `docker compose up`을 통째로 실패시켰다**(2026-08-12 동적 분석에서
# 재현). 조각은 셋 다 멀쩡한데 조합이 안 쓸린 자리였다:
#   ① Dockerfile이 비-root(uid 10001)로 돌고 `/app/uploads`만 chown한다(2026-08-10 보안검사)
#   ② dev compose는 핫리로드용으로 `./backend:/app` **전체**를 마운트해 그 chown을 덮는다
#   ③ `backend/uploads/`는 .gitignore라 새 클론엔 없다 → uid 10001이 uid 1000 소유
#      디렉터리에 mkdir → PermissionError → **import 실패 → 컨테이너가 영원히 unhealthy**
# 기존 체크아웃에는 그 폴더가 이미 있어 아무도 재현하지 못했다.
# 운영은 S3를 쓰므로(2026-06-26 이전 완료) 이 폴더가 없어도 서비스는 정상이다.
# 그래서 여기서는 '되면 만들고, 안 되면 넘어간다'. 실제로 필요한 시점(로컬 저장)에 다시 만든다.
try:
    UPLOAD_DIR.mkdir(exist_ok=True)
except OSError as e:  # 권한 없음·읽기전용 마운트 등
    logger.warning("로컬 업로드 폴더를 만들지 못했다(%s) — S3 경로만 쓴다", e)

MAX_BYTES = 5 * 1024 * 1024  # 5MB — 디스크/메모리 폭탄 방지


def _sniff_image(data: bytes) -> tuple[str, str] | None:
    """파일 앞부분(매직바이트)으로 실제 이미지 종류를 판별한다.
    클라가 보낸 content-type·파일명은 위조 가능하므로 믿지 않고 '내용'으로만 결정.
    반환: (정규화된 content_type, 확장자) 또는 None(이미지 아님 → 거부)."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", ".png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg", ".jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif", ".gif"
    # WebP는 "RIFF"....(4바이트 크기)...."WEBP" 구조
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return None


@router.post("")
# 글 작성(30/시간)과 같은 상한. 2026-07-30 심층검사에서 **이 라우트만 상한이 없는 것**을
# 발견했다: 글 30/h · 댓글 20/h · AI 10/h · 결제 20/h가 다 있는데 여기만 없어서, 12연발이
# 전부 200으로 통과했다. 그런데 이 경로는 한 번에 5MB를 S3에 얹고 CloudFront로 나가므로
# **비용이 붙는 쓰기**이고, 하필 공개된 데모 계정(writer)이 그대로 부를 수 있었다.
# 같은 날 AI 비용 캡을 조여놓고 이쪽을 열어둔 셈이었다.
#
# 한계는 정직하게: 이건 IP 기준이라 여러 IP로 몰리면 얇다. 구조적 방어는 AI 캡처럼
# **계정 기준 DB 카운터**인데 그건 테이블·마이그레이션이 필요해 여기서 하지 않았다
# (docs/cost-guardrail-drill-20260730.md의 남은 것 참고).
@limiter.limit("30/hour")
# ⚠️ **이 함수는 `def`여야 한다. `async def`로 되돌리지 마라.**
#
# 2026-08-10 심층검사 실측: 이 라우트는 앱 전체에서 **유일한 `async def` 엔드포인트**였고,
# 그 안에서 boto3의 `put_object`(동기)를 불렀다. `async def`는 threadpool로 안 빠지고
# **이벤트 루프 스레드에서 직접** 돌기 때문에 그 동안 루프가 통째로 멈춘다. uvicorn 워커가
# 1개라(docker-compose.prod.yml에 --workers 없음) 그건 곧 API 전체 정지다 — sync
# 엔드포인트들조차 threadpool로 **디스패치될 수 없다**(디스패치가 루프 위에서 일어난다).
#
# 얼마나 멈추나: 도달 불가 주소로 put_object를 걸어 재봤더니 **112.3초**였다.
# 요청 **1개**로 그렇게 된다. /api/health도 못 나가므로 도커 헬스체크(30s×3)가
# 약 95초 뒤 unhealthy로 뒤집힌다.
#
# `def`로 두면 FastAPI가 threadpool에서 돌리므로 느려도 그 요청 하나만 느리다.
def upload_image(
    request: Request,
    file: UploadFile,
    user: User = Depends(require_writer),
    # `db`를 **직접 받는다.** require_writer가 이미 세션을 열지만(deps.py의 get_current_user가
    # `db.get(User, ...)`를 한다) 이 라우트가 세션 인자를 안 받아서 **커밋하고 싶어도 손이
    # 안 닿았다.** 그래서 그 트랜잭션이 아래 S3 호출 내내(**실측 최악 55~57초** — 아래
    # Config 주석 참고) 열린 채였고, 풀 20칸 중 1칸이 그동안 `idle in transaction`으로 묶였다.
    # 에디터에서 이미지 여러 장을 올리는 정상 동작만으로 풀이 찰 수 있다.
    # ai.py가 2026-08-10에 벤더 호출 앞에서 정확히 같은 이유로 커밋을 넣었는데
    # 업로드만 안 쓸려 있었다. (2026-08-11 병목검사)
    db: Session = Depends(get_db),
):
    # 승인된 사람(writer/admin)만 — 글쓰기 부속이라 같이 잠금

    # 최대 MAX_BYTES까지만 읽음(+1바이트로 초과 감지) → 거대 파일이 메모리를 다 먹기 전에 차단
    # sync 함수이므로 `await file.read()` 대신 밑의 파일 객체를 직접 읽는다. 완전히 같은
    # 동작이다 — starlette의 UploadFile.read는 결국 `self.file.read(size)`이고, 인메모리가
    # 아닐 때만 threadpool로 한 번 넘긴다. 여기는 이미 threadpool 안이라 그 홉이 불필요하다.
    # (5MB 업로드는 formparsers의 spool_max_size=1MB를 넘어 이미 디스크에 스풀돼 있다)
    content = file.file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="파일이 너무 커 (최대 5MB)")

    # 실제 내용(매직바이트)으로만 이미지 판별 → content_type·확장자 둘 다 여기서 도출.
    # (예전엔 클라가 보낸 content-type/파일명을 믿어서 .html/.svg 같은 게 저장될 수 있었음)
    sniffed = _sniff_image(content)
    if sniffed is None:
        raise HTTPException(
            status_code=400, detail="이미지 파일만 업로드 가능 (png/jpeg/gif/webp)"
        )
    content_type, ext = sniffed

    # **여기서 DB 커넥션을 놓는다.** 위 검증까지가 DB가 필요한 전부고(require_writer의
    # 사용자 조회), 아래 S3 호출은 **실측 최악 55~57초**다. 커밋하면 커넥션이 그 자리에서 풀에
    # 반납된다(ai.py:331이 같은 근거로 실측해둔 것: checkedout 1 → 0).
    # 이 라우트는 이후 DB를 안 쓰므로 다시 빌릴 일도 없다.
    # rollback이 아니라 commit인 이유도 ai.py와 같다 — 밀린 쓰기가 없다는 보장이
    # 코드에 명시돼 있지 않고, rollback은 있으면 조용히 버린다.
    db.commit()

    # 충돌 없는 고유 이름 + 판별된 안전한 확장자.
    # 사용자가 보낸 파일명은 아예 안 씀 → 경로조작(../)·실행 가능 확장자 모두 차단
    name = f"{uuid.uuid4().hex}{ext}"

    if settings.s3_bucket:
        # 프로드: S3에 업로드 (EC2 인스턴스 역할로 인증, 키 불필요).
        # CloudFront가 /uploads/* 를 이 버킷에서 서빙 → 인스턴스 교체에도 안전.
        # ContentType도 판별값으로 고정 → 브라우저가 절대 HTML로 실행 못 함
        import boto3
        from botocore.config import Config
        from botocore.exceptions import BotoCoreError, ClientError

        # **타임아웃과 재시도 상한을 반드시 준다.** botocore 기본값은 connect 60초 /
        # read 60초 / retries max_attempts=5(_retry.json의 __default__, S3 오버라이드 없음)라,
        # S3가 블랙홀이면 한 요청이 100초를 훌쩍 넘긴다(위 112.3초가 그 값이다).
        # 연결·읽기 타임아웃 둘 다 재시도 대상이라 기본값이면 5회가 다 돈다.
        # services/ses_status.py가 같은 함정에 이미 Config를 준 이유와 같다 —
        # 그때 업로드 경로만 빠져 있었다.
        #
        # 숫자의 근거는 대역폭이 아니라 **전체 예산**이다. CloudFront의 /api/* 오리진
        # read timeout이 60초라(terraform/cloudfront.tf) 그보다 오래 걸린 응답은 사용자가
        # 볼 수 없다 — services/ai.py가 REQUEST_TIMEOUT=55를 정한 것과 같은 앵커다.
        #
        # ⚠️ **아래 계산은 2026-08-27 카오스 훈련에서 틀린 것으로 확인됐다.** 원래 여기엔
        #   `2회 시도 × (connect 5 + read 20) + 백오프 ≈ 51초 < 60초`
        # 라고 적혀 있었는데, `retries={"max_attempts": 2}` 는 **2회 시도가 아니라 2회
        # 재시도(=총 3시도)** 다. botocore 소스에서 직접 확인:
        # `ClientArgsCreator._compute_retry_max_attempts` 가 클라이언트 config 의
        # max_attempts 를 `total_max_attempts = value + 1` 로 정규화한다
        # ("client config max_attempts means total retries").
        #
        # 실측(blackhole 로 S3 를 hang 시킴): 업로드 1건당 PUT 이 **항상 3번** 나갔고
        # 시도 간격 18.0~18.3초, 벽시계 **55.42 / 56.18 / 56.67초**. 본문은 7.8KB다.
        # CloudFront 오리진 read timeout 60초까지 여유가 **3.3초**뿐이고, 그것도
        # 5MB 실물이 아니라 7.8KB 기준이다. 5MB 는 아직 안 쟀다.
        #
        # 고칠지 말지는 아직 판단하지 않았다 — `max_attempts` 를 1(=총 2시도)로 내리거나
        # read_timeout 을 줄이는 두 갈래인데, 재시도를 남긴 이유(아래 문단)가 여전히
        # 유효해서 그냥 깎을 값이 아니다. **틀린 숫자를 먼저 고치고 판단은 남긴다** —
        # 이 51초는 **위 두 곳**(트랜잭션 수명 주석·커밋 근거 주석)에도 복붙돼 있었고,
        # 거기서는 '커넥션이 얼마나 묶이나'의 근거로 쓰인다. 셋을 같이 고쳤다.
        # read=20의 검산: 5MB=40Mbit. t2.micro 지속 대역폭은 AWS 미공표라 추정이지만 극단적
        # 비관 하한 10Mbps로 잡아도 4초다. 게다가 read_timeout은 '요청 전체의 데드라인'이
        # 아니라 소켓 한 번의 I/O 타임아웃이라 더 여유가 있다.
        # ses_status.py의 read=3을 그대로 옮기면 안 된다 — 그쪽은 본문 없는 제어 API다.
        #
        # 재시도를 1회 남긴 이유: Body가 bytes라 재전송이 안전하고(파일 객체면 seek가
        # 필요했다) Key가 매번 새 uuid라 중복도 안 생긴다. 사용자가 5MB를 이미 올려보낸
        # 뒤라 TCP 한 번 튄 걸로 버리기엔 아깝다.
        s3 = boto3.client(
            "s3",
            region_name=settings.aws_region,
            config=Config(
                connect_timeout=5,
                read_timeout=20,
                retries={"max_attempts": 2},
            ),
        )
        try:
            s3.put_object(
                Bucket=settings.s3_bucket,
                Key=f"uploads/{name}",
                Body=content,
                ContentType=content_type,
                # 업로드 이미지에는 캐시 헤더가 **아예 없었다**(2026-08-31 검사: 라이브
                # HEAD 응답에 cache-control 줄 자체가 없다). 배포 워크플로가 dist 에 캐시
                # 헤더를 박는 08-10 수정은 `--exclude "uploads/*"` 때문에 이 프리픽스에
                # 닿지 않는다. 그래서 같은 이미지를 볼 때마다 매번 다시 받아 간다.
                #
                # 파일명이 uuid4 hex 라 **내용이 바뀌면 이름이 바뀐다** — 해시가 박힌 번들
                # 자산과 같은 논리이므로 immutable 로 둘 수 있다. 이미 올라간 것들은 이
                # 코드가 안 건드린다(메타데이터만 따로 갱신해야 한다).
                CacheControl="public,max-age=31536000,immutable",
            )
        except (ClientError, BotoCoreError) as e:
            # S3가 죽거나 권한이 빠지면 여기서 예외가 그대로 터져 **500 text/plain**이 나갔다
            # (2026-07-28 카오스 훈련에서 실측: InvalidAccessKeyId → 500 "Internal Server Error").
            # 프론트는 JSON을 기대하므로 파싱조차 못 하고, 사용자는 이유를 모른 채 빨간 에러만 본다.
            # 503으로 바꾸면 프론트의 isAsleepStatus(502/503/504)가 '일시적 장애' 안내로 받는다.
            #
            # 원인 문자열은 서버 로그에만 남긴다 — 버킷명·권한 오류는 밖에 알려줄 이유가 없다.
            logger.warning("S3 업로드 실패: %s", e)
            raise HTTPException(
                status_code=503,
                detail="이미지 저장소에 일시적으로 접근할 수 없어. 잠시 후 다시 시도해줘.",
            ) from e
    else:
        # 로컬 개발: 디스크에 저장 (확장자가 판별값이라 StaticFiles도 올바른 타입으로 서빙)
        # 폴더는 여기서 만든다 — import 시점의 mkdir은 실패해도 넘어가기 때문이다(위 주석).
        # 실패하면 S3 경로와 **같은 모양의 503**을 준다. 스택트레이스를 밖으로 내지 않는다.
        try:
            UPLOAD_DIR.mkdir(exist_ok=True)
            dest = UPLOAD_DIR / name
            dest.write_bytes(content)
        except OSError as e:
            logger.warning("로컬 업로드 저장 실패: %s", e)
            raise HTTPException(
                status_code=503,
                detail="이미지 저장소에 일시적으로 접근할 수 없어. 잠시 후 다시 시도해줘.",
            ) from e

    # 마크다운에 넣을 수 있는 절대 URL 반환 (둘 다 /uploads/<name>)
    return {"url": f"{settings.public_base_url}/uploads/{name}"}

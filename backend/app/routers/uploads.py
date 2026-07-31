import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile

from app.core.config import settings
from app.core.deps import require_writer
from app.core.ratelimit import limiter
from app.models.user import User

logger = logging.getLogger(__name__)

# POST는 /upload(단수), 저장된 파일 서빙은 /uploads/<파일>(StaticFiles)로 분리
router = APIRouter(prefix="/upload", tags=["uploads"])

# 로컬 개발용 저장 폴더. 운영은 S3_BUCKET이 설정돼 있어 아래에서 S3로 올린다
# (2026-06-26에 이전 완료 — 인스턴스를 교체해도 이미지가 안 사라지게).
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

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
async def upload_image(
    request: Request, file: UploadFile, user: User = Depends(require_writer)
):
    # 승인된 사람(writer/admin)만 — 글쓰기 부속이라 같이 잠금

    # 최대 MAX_BYTES까지만 읽음(+1바이트로 초과 감지) → 거대 파일이 메모리를 다 먹기 전에 차단
    content = await file.read(MAX_BYTES + 1)
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

    # 충돌 없는 고유 이름 + 판별된 안전한 확장자.
    # 사용자가 보낸 파일명은 아예 안 씀 → 경로조작(../)·실행 가능 확장자 모두 차단
    name = f"{uuid.uuid4().hex}{ext}"

    if settings.s3_bucket:
        # 프로드: S3에 업로드 (EC2 인스턴스 역할로 인증, 키 불필요).
        # CloudFront가 /uploads/* 를 이 버킷에서 서빙 → 인스턴스 교체에도 안전.
        # ContentType도 판별값으로 고정 → 브라우저가 절대 HTML로 실행 못 함
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError

        s3 = boto3.client("s3", region_name=settings.aws_region)
        try:
            s3.put_object(
                Bucket=settings.s3_bucket,
                Key=f"uploads/{name}",
                Body=content,
                ContentType=content_type,
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
        dest = UPLOAD_DIR / name
        dest.write_bytes(content)

    # 마크다운에 넣을 수 있는 절대 URL 반환 (둘 다 /uploads/<name>)
    return {"url": f"{settings.public_base_url}/uploads/{name}"}

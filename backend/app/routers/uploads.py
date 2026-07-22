import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app.core.config import settings
from app.core.deps import require_writer
from app.models.user import User

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
async def upload_image(file: UploadFile, user: User = Depends(require_writer)):
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

        s3 = boto3.client("s3", region_name=settings.aws_region)
        s3.put_object(
            Bucket=settings.s3_bucket,
            Key=f"uploads/{name}",
            Body=content,
            ContentType=content_type,
        )
    else:
        # 로컬 개발: 디스크에 저장 (확장자가 판별값이라 StaticFiles도 올바른 타입으로 서빙)
        dest = UPLOAD_DIR / name
        dest.write_bytes(content)

    # 마크다운에 넣을 수 있는 절대 URL 반환 (둘 다 /uploads/<name>)
    return {"url": f"{settings.public_base_url}/uploads/{name}"}

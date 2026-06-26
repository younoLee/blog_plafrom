import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile, HTTPException

from app.core.config import settings
from app.core.deps import require_writer
from app.models.user import User

# POST는 /upload(단수), 저장된 파일 서빙은 /uploads/<파일>(StaticFiles)로 분리
router = APIRouter(prefix="/upload", tags=["uploads"])

# 업로드 파일을 저장할 로컬 폴더 (나중에 S3로 교체)
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED = {"image/png", "image/jpeg", "image/gif", "image/webp"}
MAX_BYTES = 5 * 1024 * 1024  # 5MB — 디스크/메모리 폭탄 방지


@router.post("")
async def upload_image(file: UploadFile, user: User = Depends(require_writer)):
    # 승인된 사람(writer/admin)만 — 글쓰기 부속이라 같이 잠금
    # 이미지 종류만 허용
    if file.content_type not in ALLOWED:
        raise HTTPException(status_code=400, detail="이미지 파일만 업로드 가능")

    # 최대 MAX_BYTES까지만 읽음(+1바이트로 초과 감지) → 거대 파일이 메모리를 다 먹기 전에 차단
    content = await file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="파일이 너무 커 (최대 5MB)")

    # 원본 확장자 유지 + 충돌 없는 고유 이름 (uuid)
    ext = Path(file.filename or "").suffix.lower()
    name = f"{uuid.uuid4().hex}{ext}"

    if settings.s3_bucket:
        # 프로드: S3에 업로드 (EC2 인스턴스 역할로 인증, 키 불필요).
        # CloudFront가 /uploads/* 를 이 버킷에서 서빙 → 인스턴스 교체에도 안전
        import boto3

        s3 = boto3.client("s3", region_name=settings.aws_region)
        s3.put_object(
            Bucket=settings.s3_bucket,
            Key=f"uploads/{name}",
            Body=content,
            ContentType=file.content_type,
        )
    else:
        # 로컬 개발: 디스크에 저장
        dest = UPLOAD_DIR / name
        dest.write_bytes(content)

    # 마크다운에 넣을 수 있는 절대 URL 반환 (둘 다 /uploads/<name>)
    return {"url": f"{settings.public_base_url}/uploads/{name}"}

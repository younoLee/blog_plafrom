import uuid
from pathlib import Path

from fastapi import APIRouter, UploadFile, HTTPException

from app.core.config import settings

# POST는 /upload(단수), 저장된 파일 서빙은 /uploads/<파일>(StaticFiles)로 분리
router = APIRouter(prefix="/upload", tags=["uploads"])

# 업로드 파일을 저장할 로컬 폴더 (나중에 S3로 교체)
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED = {"image/png", "image/jpeg", "image/gif", "image/webp"}


@router.post("")
async def upload_image(file: UploadFile):
    # 이미지 종류만 허용
    if file.content_type not in ALLOWED:
        raise HTTPException(status_code=400, detail="이미지 파일만 업로드 가능")

    # 원본 확장자 유지 + 충돌 없는 고유 이름 (uuid)
    ext = Path(file.filename or "").suffix.lower()
    name = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_DIR / name

    # 파일 저장
    content = await file.read()
    dest.write_bytes(content)

    # 마크다운에 넣을 수 있는 절대 URL 반환
    return {"url": f"{settings.public_base_url}/uploads/{name}"}

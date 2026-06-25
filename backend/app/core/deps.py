from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User

# Authorization: Bearer <토큰> 헤더에서 토큰을 꺼냄
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")
# auto_error=False: 토큰 없어도 에러 안 내고 None (선택적 로그인용)
oauth2_optional = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    user_id = decode_access_token(token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="로그인이 필요해")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="유효하지 않은 사용자")
    return user


def get_current_user_optional(
    token: str | None = Depends(oauth2_optional), db: Session = Depends(get_db)
) -> User | None:
    """로그인했으면 User, 아니면 None (에러 안 냄)."""
    if not token:
        return None
    user_id = decode_access_token(token)
    if user_id is None:
        return None
    return db.get(User, user_id)

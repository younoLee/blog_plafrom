from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.security import hash_password, verify_password, create_access_token
from app.models.user import User
from app.schemas.user import UserCreate, UserRead, Token

router = APIRouter(prefix="/auth", tags=["auth"])


def _is_admin_email(email: str) -> bool:
    # .env의 ADMIN_EMAIL과 일치하면 관리자. 빈 값이면 아무도 관리자 아님.
    return bool(settings.admin_email) and email == settings.admin_email


@router.post("/register", response_model=UserRead, status_code=201)
def register(data: UserCreate, db: Session = Depends(get_db)):
    exists = db.scalar(select(User).where(User.email == data.email))
    if exists:
        raise HTTPException(status_code=409, detail="이미 가입된 이메일")
    # 관리자 이메일이면 admin, 아니면 pending(승인 대기)으로 가입
    role = "admin" if _is_admin_email(data.email) else "pending"
    user = User(
        email=data.email, hashed_password=hash_password(data.password), role=role
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(data: UserCreate, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email))
    # 사용자 없거나 비밀번호 틀리면 동일한 401 (어느 쪽이 틀렸는지 안 알려줌 = 보안)
    if user is None or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 틀렸어")
    # 차단된 계정은 로그인 불가
    if user.role == "banned":
        raise HTTPException(status_code=403, detail="차단된 계정이야")
    # 관리자 이메일인데 아직 admin이 아니면 승격 (ADMIN_EMAIL을 나중에 지정한 경우 대비)
    if _is_admin_email(user.email) and user.role != "admin":
        user.role = "admin"
        db.commit()
    return Token(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserRead)
def me(current: User = Depends(get_current_user)):
    return current

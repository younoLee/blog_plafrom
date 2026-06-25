from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.ratelimit import limiter
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_email_token,
    decode_email_token,
)
from app.models.user import User
from app.schemas.user import UserCreate, UserRead, Token
from app.services.email import send_verification_email

router = APIRouter(prefix="/auth", tags=["auth"])


def _is_admin_email(email: str) -> bool:
    # .env의 ADMIN_EMAIL과 일치하면 관리자. 빈 값이면 아무도 관리자 아님.
    return bool(settings.admin_email) and email == settings.admin_email


@router.post("/register", response_model=UserRead, status_code=201)
@limiter.limit("5/hour")  # 한 IP당 시간당 5번까지만 가입 (대량가입 속도 차단)
def register(request: Request, data: UserCreate, background: BackgroundTasks, db: Session = Depends(get_db)):
    exists = db.scalar(select(User).where(User.email == data.email))
    if exists:
        raise HTTPException(status_code=409, detail="이미 가입된 이메일")
    # 관리자 이메일이면 admin+자동 인증, 아니면 pending+미인증(확인메일 필요)
    is_admin = _is_admin_email(data.email)
    user = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        role="admin" if is_admin else "pending",
        email_verified=is_admin,  # 관리자는 메일 인증 생략
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    # 일반 가입자에게만 확인메일 발송 (응답 후 백그라운드로)
    if not is_admin:
        token = create_email_token(user.id, purpose="verify")
        link = f"{settings.frontend_base_url}/verify?token={token}"
        background.add_task(send_verification_email, user.email, link)
    return user


@router.post("/verify", response_model=UserRead)
def verify_email(token: str, db: Session = Depends(get_db)):
    # 메일 링크의 토큰으로 이메일 인증 처리 (purpose=verify인 토큰만 통과)
    user_id = decode_email_token(token, purpose="verify")
    if user_id is None:
        raise HTTPException(status_code=400, detail="유효하지 않거나 만료된 링크야")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없음")
    user.email_verified = True
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
@limiter.limit("10/minute")  # 무차별 비번 대입 속도 제한
def login(request: Request, data: UserCreate, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email))
    # 사용자 없거나 비밀번호 틀리면 동일한 401 (어느 쪽이 틀렸는지 안 알려줌 = 보안)
    if user is None or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 틀렸어")
    # 차단된 계정은 로그인 불가
    if user.role == "banned":
        raise HTTPException(status_code=403, detail="차단된 계정이야")
    # 이메일 미인증이면 로그인 불가 (봇 대량가입 차단)
    if not user.email_verified:
        raise HTTPException(status_code=403, detail="이메일 인증이 필요해 (메일함 확인)")
    # 관리자 이메일인데 아직 admin이 아니면 승격 (ADMIN_EMAIL을 나중에 지정한 경우 대비)
    if _is_admin_email(user.email) and user.role != "admin":
        user.role = "admin"
        db.commit()
    return Token(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserRead)
def me(current: User = Depends(get_current_user)):
    return current

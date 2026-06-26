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
from app.schemas.user import (
    UserCreate,
    RegisterRequest,
    UserRead,
    Token,
    ForgotPasswordRequest,
    ResetPasswordRequest,
)
from app.services.email import send_verification_email, send_reset_email

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=201)
@limiter.limit("5/hour")  # 한 IP당 시간당 5번까지만 가입 (대량가입 속도 차단)
def register(request: Request, data: RegisterRequest, background: BackgroundTasks, db: Session = Depends(get_db)):
    exists = db.scalar(select(User).where(User.email == data.email))
    if exists:
        raise HTTPException(status_code=409, detail="이미 가입된 이메일")
    # 모든 가입자는 pending + 미인증으로 시작 (관리자 승격은 DB에서만)
    user = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        role="pending",
        email_verified=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    # 확인메일 발송 (응답 후 백그라운드로)
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
    return Token(access_token=create_access_token(user.id, user.token_version))


@router.post("/forgot-password", status_code=202)
@limiter.limit("5/hour")  # 메일 폭탄 방지
def forgot_password(
    request: Request,
    data: ForgotPasswordRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(User.email == data.email))
    # 가입돼 있고 차단 안 된 계정에만 실제 발송. 단 응답은 항상 동일(존재 여부 노출 안 함)
    if user is not None and user.role != "banned":
        token = create_email_token(user.id, purpose="reset", expire_hours=1)
        link = f"{settings.frontend_base_url}/reset?token={token}"
        background.add_task(send_reset_email, user.email, link)
    return {"message": "재설정 링크를 보냈어 (가입된 이메일이라면)"}


@router.post("/reset-password", response_model=UserRead)
def reset_password(data: ResetPasswordRequest, db: Session = Depends(get_db)):
    # reset 목적 토큰만 통과
    user_id = decode_email_token(data.token, purpose="reset")
    if user_id is None:
        raise HTTPException(status_code=400, detail="유효하지 않거나 만료된 링크야")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없음")
    user.hashed_password = hash_password(data.new_password)
    user.token_version += 1  # 비번 바뀌면 기존에 발급된 모든 토큰 무효화
    db.commit()
    db.refresh(user)
    return user


@router.get("/me", response_model=UserRead)
def me(current: User = Depends(get_current_user)):
    return current

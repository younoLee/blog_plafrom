from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.ratelimit import limiter
from app.core.security import (
    create_access_token,
    create_email_token,
    decode_email_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.user import (
    ForgotPasswordRequest,
    RegisterRequest,
    ResetPasswordRequest,
    Token,
    UserCreate,
    UserRead,
)
from app.services.email import (
    send_already_registered_email,
    send_reset_email,
    send_verification_email,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=202)
@limiter.limit("5/hour")  # 한 IP당 시간당 5번까지만 가입 (대량가입 속도 차단)
def register(request: Request, data: RegisterRequest, background: BackgroundTasks, db: Session = Depends(get_db)):
    # 계정 존재 여부를 HTTP 응답으로 노출하지 않으려고 신규/기존 구분 없이 동일한 202 응답.
    # 실제 안내는 '메일로만' 간다 (forgot-password와 같은 패턴) → 이메일 enumeration 방지.
    existing = db.scalar(select(User).where(User.email == data.email))
    if existing is None:
        # 신규: pending + 미인증으로 생성 후 인증메일 (관리자 승격은 DB에서만)
        user = User(
            email=data.email,
            hashed_password=hash_password(data.password),
            role="pending",
            email_verified=False,
        )
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            # 동시 가입 레이스: 그 찰나 다른 요청이 같은 이메일을 만듦(email unique 충돌).
            # 500 대신 일반 응답 유지(존재 여부 노출 안 함) — 이미 메일은 그쪽 요청이 보냄.
            db.rollback()
            return {"message": "확인 메일을 보냈어. 메일함을 확인해줘."}
        db.refresh(user)
        token = create_email_token(user.id, purpose="verify")
        link = f"{settings.frontend_base_url}/verify?token={token}"
        background.add_task(send_verification_email, user.email, link)
    elif not existing.email_verified:
        # 기존이지만 아직 미인증: 인증메일 재발송 (가입 완료 못 한 사람 도움)
        token = create_email_token(existing.id, purpose="verify")
        link = f"{settings.frontend_base_url}/verify?token={token}"
        background.add_task(send_verification_email, existing.email, link)
    else:
        # 기존 + 인증완료: '이미 가입됨' 안내메일 (HTTP 응답으로는 노출 안 함)
        background.add_task(
            send_already_registered_email,
            existing.email,
            f"{settings.frontend_base_url}/login",
        )
    return {"message": "확인 메일을 보냈어. 메일함을 확인해줘."}


@router.post("/verify", response_model=UserRead)
def verify_email(token: str, db: Session = Depends(get_db)):
    # 메일 링크의 토큰으로 이메일 인증 처리 (purpose=verify인 토큰만 통과)
    decoded = decode_email_token(token, purpose="verify")
    if decoded is None:
        raise HTTPException(status_code=400, detail="유효하지 않거나 만료된 링크야")
    user_id, _ = decoded
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
        # ver=현재 token_version → 재설정 후 token_version이 바뀌면 이 토큰은 무효(1회용)
        token = create_email_token(
            user.id, purpose="reset", expire_hours=1, ver=user.token_version
        )
        link = f"{settings.frontend_base_url}/reset?token={token}"
        background.add_task(send_reset_email, user.email, link)
    return {"message": "재설정 링크를 보냈어 (가입된 이메일이라면)"}


@router.post("/reset-password", response_model=UserRead)
def reset_password(data: ResetPasswordRequest, db: Session = Depends(get_db)):
    # reset 목적 토큰만 통과
    decoded = decode_email_token(data.token, purpose="reset")
    if decoded is None:
        raise HTTPException(status_code=400, detail="유효하지 않거나 만료된 링크야")
    user_id, tok_ver = decoded
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없음")
    # 토큰의 ver가 현재와 다르면 = 이미 한 번 쓴(또는 그 사이 비번 바뀐) 토큰 → 거부(1회용)
    if user.token_version != tok_ver:
        raise HTTPException(status_code=400, detail="이미 사용했거나 만료된 링크야")
    user.hashed_password = hash_password(data.new_password)
    user.token_version += 1  # 비번 바뀌면 기존 토큰·이 재설정 토큰 모두 무효화
    db.commit()
    db.refresh(user)
    return user


@router.get("/me", response_model=UserRead)
def me(current: User = Depends(get_current_user)):
    return current

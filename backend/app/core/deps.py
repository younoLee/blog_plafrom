from datetime import datetime, timezone

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User


def _expire_pro_if_due(user: User, db: Session) -> None:
    """구독 만료 시각이 지났으면 is_pro를 끈다(lazy expiration).
    별도 배치 없이, 그 사용자가 요청할 때마다 확인 → 지났으면 한 번만 꺼서 커밋."""
    if user.is_pro and user.pro_until is not None and user.pro_until <= datetime.now(timezone.utc):
        user.is_pro = False
        db.commit()

# Authorization: Bearer <토큰> 헤더에서 토큰을 꺼냄
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")
# auto_error=False: 토큰 없어도 에러 안 내고 None (선택적 로그인용)
oauth2_optional = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    decoded = decode_access_token(token)
    if decoded is None:
        raise HTTPException(status_code=401, detail="로그인이 필요해")
    user_id, ver = decoded
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="유효하지 않은 사용자")
    # 비번 재설정·차단 이후 발급 전 토큰이면 버전 불일치 → 무효
    if user.token_version != ver:
        raise HTTPException(status_code=401, detail="세션이 만료됐어 (다시 로그인)")
    # 차단된 계정은 토큰이 있어도 막음
    if user.role == "banned":
        raise HTTPException(status_code=403, detail="차단된 계정이야")
    # 구독 만료 확인(지났으면 is_pro off) — 이후 모든 게이팅이 최신 상태로 동작
    _expire_pro_if_due(user, db)
    return user


def get_current_user_optional(
    token: str | None = Depends(oauth2_optional), db: Session = Depends(get_db)
) -> User | None:
    """로그인했으면 User, 아니면 None (에러 안 냄)."""
    if not token:
        return None
    decoded = decode_access_token(token)
    if decoded is None:
        return None
    user_id, ver = decoded
    user = db.get(User, user_id)
    if user is None or user.token_version != ver:
        return None
    # 차단된 계정은 비로그인 취급
    if user.role == "banned":
        return None
    return user


def require_writer(user: User = Depends(get_current_user)) -> User:
    """글쓰기 권한 검사: 승인된 사람(writer)이나 관리자(admin)만 통과.
    pending(승인 대기)이면 403."""
    if user.role not in ("writer", "admin"):
        raise HTTPException(status_code=403, detail="글쓰기 권한이 없어 (승인 대기 중)")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """관리자 전용 (승인 처리 등). admin만 통과."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="관리자 전용")
    return user

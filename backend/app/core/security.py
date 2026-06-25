from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings

ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24


# --- 비밀번호 해싱 ---
def hash_password(plain: str) -> str:
    # bcrypt는 bytes를 받음. salt를 자동 생성해 해시
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# --- JWT 토큰 ---
def create_access_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),  # 토큰 주인(사용자 id)
        "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> int | None:
    """유효하면 user_id 반환, 만료/위조면 None."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


# --- 이메일 링크용 토큰 (이메일 인증 / 비밀번호 재설정 공용) ---
# 로그인 토큰과 구분하려고 purpose("verify"/"reset")를 넣음 → 용도 섞어쓰기 방지
def create_email_token(user_id: int, purpose: str, expire_hours: int = 24) -> str:
    payload = {
        "sub": str(user_id),
        "purpose": purpose,
        "exp": datetime.now(timezone.utc) + timedelta(hours=expire_hours),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_email_token(token: str, purpose: str) -> int | None:
    """purpose가 일치하고 유효하면 user_id, 아니면 None (만료·위조·용도불일치)."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        if payload.get("purpose") != purpose:
            return None
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.config import settings

ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 12  # 노출 시간 축소 (예전 24h)


# --- 비밀번호 해싱 ---
# bcrypt의 입력 상한. 알고리즘 자체의 제약이라 우회할 수 없다.
BCRYPT_MAX_BYTES = 72


def _bcrypt_input(plain: str) -> bytes:
    """bcrypt에 넣을 bytes. 72바이트를 넘으면 자른다.

    자르는 이유: bcrypt 5.0부터 초과 입력을 ValueError로 거부한다(4.x는 조용히 잘랐다).
    그대로 두면 긴 비밀번호로 이미 가입한 사용자가 로그인에서 500으로 잠긴다 —
    저장된 해시는 4.x가 '잘라서' 만든 것이라 같은 방식으로 잘라야 검증이 맞는다.

    schemas/user.py의 PW_MAX=72로 못 막는다: 그건 Pydantic max_length라 '글자 수'를
    세는데 bcrypt의 72는 '바이트'다. 한글은 글자당 3바이트라 24글자만 넘어도 걸린다.
    """
    return plain.encode()[:BCRYPT_MAX_BYTES]


def hash_password(plain: str) -> str:
    # bcrypt는 bytes를 받음. salt를 자동 생성해 해시
    return bcrypt.hashpw(_bcrypt_input(plain), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(_bcrypt_input(plain), hashed.encode())


# --- JWT 토큰 ---
def create_access_token(user_id: int, token_version: int) -> str:
    payload = {
        "sub": str(user_id),  # 토큰 주인(사용자 id)
        "ver": token_version,  # 사용자 token_version 스냅샷 (재설정/차단 시 불일치→무효)
        "exp": datetime.now(UTC) + timedelta(hours=TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> tuple[int, int] | None:
    """유효하면 (user_id, token_version) 반환, 만료/위조면 None."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        # 이메일용 토큰(verify/reset)은 purpose가 있음 → 로그인 토큰으로 못 쓰게 거부(토큰 혼동 방지)
        if "purpose" in payload:
            return None
        return int(payload["sub"]), int(payload.get("ver", 0))
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


# --- 이메일 링크용 토큰 (이메일 인증 / 비밀번호 재설정 공용) ---
# 로그인 토큰과 구분하려고 purpose("verify"/"reset")를 넣음 → 용도 섞어쓰기 방지
# ver: 발급 시점의 user.token_version 스냅샷. 재설정 토큰을 1회용으로 만드는 데 씀
# (재설정하면 token_version이 +1 → 같은 토큰을 다시 쓰면 ver 불일치로 거부)
def create_email_token(
    user_id: int, purpose: str, expire_hours: int = 24, ver: int = 0
) -> str:
    payload = {
        "sub": str(user_id),
        "purpose": purpose,
        "ver": ver,
        "exp": datetime.now(UTC) + timedelta(hours=expire_hours),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_email_token(token: str, purpose: str) -> tuple[int, int] | None:
    """purpose 일치+유효하면 (user_id, ver), 아니면 None (만료·위조·용도불일치)."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        if payload.get("purpose") != purpose:
            return None
        return int(payload["sub"]), int(payload.get("ver", 0))
    except (jwt.PyJWTError, KeyError, ValueError):
        return None

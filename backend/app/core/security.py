import hashlib
import secrets
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


# 없는 계정에도 **같은 비용의 해시 검사**를 돌리기 위한 가짜 해시.
#
# 왜 필요한가(2026-08-19 보안검사, 실측): 로그인이
# `if user is None or not verify_password(...)`였는데 이건 단락 평가라, 계정이 없으면
# bcrypt가 아예 안 돈다. 응답 시간이 **0.03초 대 1.9초**로 갈렸다 — 30~60배가 반복
# 재현됐다. 본문은 넷 다 바이트가 같은 401인데 시간 하나가 "이 이메일은 계정이 있다"를
# 확정해 준다. register(항상 202)와 forgot-password(항상 202)가 문자열로는 안 가리도록
# 공들여 막아둔 것을 사이드채널 하나가 되돌린다.
#
# 값은 import 시점에 한 번 만든다. 상수로 박아두면 cost가 바뀔 때 같이 안 바뀌어서,
# 진짜 해시와 비용이 어긋나는 순간 다시 새기 시작한다 — 그건 눈에 안 보인다.
_ABSENT_USER_HASH = hash_password("이 값은 아무 비밀번호와도 안 맞는다")


def verify_password_or_dummy(plain: str, hashed: str | None) -> bool:
    """계정이 없어도 해시 검사를 **거르지 않는다**. 없으면 항상 False.

    호출부가 `user is None`을 먼저 보고 빠져나가면 이 함수가 있어도 소용없다.
    반드시 `verify_password_or_dummy(pw, user.hashed_password if user else None)`
    형태로, 사용자 존재 여부와 **무관하게 한 번** 부를 것.
    """
    return verify_password(plain, hashed if hashed is not None else _ABSENT_USER_HASH) and (
        hashed is not None
    )


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
        # ⚠️ **`.get("ver", 0)`이면 안 된다.** `ver` 클레임이 **없는** 토큰이 0으로 채워져
        # 재설정·차단 이력이 없는 모든 계정(token_version=0)과 일치해 통과했다
        # (2026-08-12 검사에서 위조 토큰으로 200 실측). 뜻은 이렇다 — 키가 한 번 새면
        # `token_version`을 올려도 ver 없는 토큰은 그대로 먹어서 **사고 후 대응 수단이
        # 하나 사라진다.** 없는 클레임은 '0'이 아니라 '이 토큰은 우리가 만든 게 아니다'다.
        # 아래 except가 이미 KeyError를 잡으므로 대괄호 하나로 닫힌다.
        # (`options={"require": [...]}`로 가지 않은 이유: 거기에 `purpose`를 넣으면
        #  위 :55와 교집합이 공집합이 되어 **모든 인증이 죽는다.** 실측으로 확인했다.)
        return int(payload["sub"]), int(payload["ver"])
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


# --- 초대 토큰 (관리자 발급 1회용 가입 링크) ---
# 위의 이메일 토큰과 달리 **JWT가 아니다.** 이유가 있다:
#   1) JWT는 자체적으로 유효하므로 서버가 '이미 썼다'를 알 수 없다. 1회용을 만들려면
#      어차피 DB에 상태가 필요하고, 그러면 JWT일 이유가 없다.
#   2) 초대는 아직 계정이 없는 사람에게 나간다 → sub(user_id)에 넣을 게 없다.
# 그래서 그냥 난수를 발급하고 DB에는 해시만 둔다(models/invite.py).
def new_invite_token() -> str:
    """추측 불가능한 초대 토큰 원문. 32바이트=256비트 → 무차별 대입이 무의미하다.

    '사람이 손으로 칠 만한 짧은 코드'로 만들지 않는 게 요점이다. 짧게 만들면
    대입을 막느라 캡차·시도 제한 같은 장치가 또 필요해진다(그건 열린 가입을
    전제로 한 계획이라 2026-08-04에 기각됐다). 링크에 실어 보내면 칠 일이
    없으므로 길이는 공짜다."""
    return secrets.token_urlsafe(32)


def hash_invite_token(token: str) -> str:
    """DB 조회·저장에 쓰는 토큰 해시(sha256 hex 64자).

    bcrypt가 아니라 sha256인 이유: 이건 비밀번호가 아니라 고엔트로피 난수다.
    사전 공격 대상이 아니라서 느린 해시가 막아줄 게 없고, 매 조회마다 해시를
    쓰므로 빠른 편이 낫다. 조회 자체도 이 값의 동등 비교(인덱스)로 끝난다."""
    return hashlib.sha256(token.encode()).hexdigest()

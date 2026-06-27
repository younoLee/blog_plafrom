"""BYOK 키 보관 — 사용자의 외부 LLM(API) 키를 Fernet으로 암호화해 DB에 저장.

규칙:
- 평문 키는 DB에 절대 안 들어감(암호문만). 복호화는 generate_draft 호출 순간에만.
- 응답/로그에 키 원문 노출 금지 (있다/없다 + 마스킹만).
"""

import ipaddress
import socket
from urllib.parse import urlparse

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.llm_credential import LLMCredential

# BYOK를 지원하는 provider 목록
#  - compatible: OpenAI 호환 범용(Grok/DeepSeek/OpenRouter/로컬 등)
#  - anthropic: 자기 Claude 키(서버 키·티어와 별개)
#  - cohere: Cohere 자체 API
BYOK_PROVIDERS = ("openai", "gemini", "compatible", "anthropic", "cohere")
# base_url(엔드포인트)이 반드시 필요한 provider
NEEDS_BASE_URL = ("compatible",)


class BYOKNotConfiguredError(RuntimeError):
    """서버에 LLM_ENCRYPTION_KEY가 없어서 키 저장/사용 불가."""


class InvalidBaseURLError(ValueError):
    """base_url이 https가 아니거나 내부/사설 주소를 가리킬 때(SSRF 방지)."""


def validate_base_url(url: str) -> str:
    """compatible provider의 base_url을 SSRF 관점에서 검증한다.

    base_url은 '서버가 직접 요청을 보내는 주소'라, 검증 없이 두면 승인된 사용자가
    이 서버를 발판으로 내부망·클라우드 메타데이터(169.254.169.254) 등을 찌를 수 있다.
    - https만 허용 (평문/대부분의 내부 서비스 차단)
    - 호스트가 가리키는 모든 IP가 공인(global) 대역이어야 함
      → 사설/loopback/링크로컬/예약 대역이면 거부
    한계: 검증~호출 사이 DNS가 바뀌는 rebinding까지는 못 막는다.
    최종 방어선은 인프라(EC2 IMDSv2 강제 + hop-limit 1)다.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise InvalidBaseURLError("base URL은 https로 시작해야 해 (예: https://api.x.ai/v1)")
    host = parsed.hostname
    if not host:
        raise InvalidBaseURLError("base URL 형식이 올바르지 않아")
    # 호스트네임을 실제 IP로 풀어서(별칭으로 내부 IP 가리키는 것까지) 전부 검사
    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise InvalidBaseURLError("base URL의 주소를 확인할 수 없어 (호스트명 확인)")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise InvalidBaseURLError("내부/사설 주소는 base URL로 쓸 수 없어")
    return url


def _fernet() -> Fernet:
    if not settings.llm_encryption_key:
        raise BYOKNotConfiguredError("LLM_ENCRYPTION_KEY 미설정")
    return Fernet(settings.llm_encryption_key.encode())


def set_key(
    db: Session, user_id: int, provider: str, plain_key: str, base_url: str | None = None
) -> None:
    """사용자 키를 암호화해 저장(있으면 교체). compatible은 base_url도 함께 저장."""
    enc = _fernet().encrypt(plain_key.encode()).decode()
    cred = db.scalar(
        select(LLMCredential).where(
            LLMCredential.user_id == user_id, LLMCredential.provider == provider
        )
    )
    if cred is None:
        db.add(LLMCredential(user_id=user_id, provider=provider, encrypted_key=enc, base_url=base_url))
    else:
        cred.encrypted_key = enc
        cred.base_url = base_url
    db.commit()


def delete_key(db: Session, user_id: int, provider: str) -> bool:
    cred = db.scalar(
        select(LLMCredential).where(
            LLMCredential.user_id == user_id, LLMCredential.provider == provider
        )
    )
    if cred is None:
        return False
    db.delete(cred)
    db.commit()
    return True


def get_credential(db: Session, user_id: int, provider: str) -> tuple[str, str | None] | None:
    """호출 순간에만 복호화. (복호화된 키, base_url) 또는 없으면 None."""
    cred = db.scalar(
        select(LLMCredential).where(
            LLMCredential.user_id == user_id, LLMCredential.provider == provider
        )
    )
    if cred is None:
        return None
    return _fernet().decrypt(cred.encrypted_key.encode()).decode(), cred.base_url


def get_base_url(db: Session, user_id: int, provider: str) -> str | None:
    """설정 화면 표시용 (비밀 아님)."""
    cred = db.scalar(
        select(LLMCredential).where(
            LLMCredential.user_id == user_id, LLMCredential.provider == provider
        )
    )
    return cred.base_url if cred else None


def providers_with_key(db: Session, user_id: int) -> set[str]:
    """이 사용자가 키를 등록해둔 provider 집합 (드롭다운/허용목록 계산용)."""
    rows = db.scalars(
        select(LLMCredential.provider).where(LLMCredential.user_id == user_id)
    ).all()
    return set(rows)

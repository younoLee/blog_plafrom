from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LLMCredential(Base):
    """사용자가 맡긴 외부 LLM API 키(BYOK). 평문이 아니라 Fernet 암호문을 저장.
    사람당 provider별로 1개(openai/gemini). 계정 삭제 시 CASCADE로 함께 삭제."""

    __tablename__ = "llm_credentials"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_llm_user_provider"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # 'openai' | 'gemini' | 'compatible'(OpenAI 호환 범용)
    provider: Mapped[str] = mapped_column(String(20))
    # Fernet 암호문 (복호화는 호출 순간 메모리에서만, 응답/로그엔 절대 노출 안 함)
    encrypted_key: Mapped[str] = mapped_column(Text)
    # OpenAI 호환 provider용 엔드포인트 주소(비밀 아님). 그 외엔 NULL
    base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

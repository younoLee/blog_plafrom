from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, Integer, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    # 평문이 아니라 bcrypt 해시를 저장
    hashed_password: Mapped[str] = mapped_column(String(255))
    # 권한: pending(가입 직후·승인 대기) / writer(승인됨·글쓰기 가능) / admin(승인권자)
    # 기존 가입자도 server_default 덕분에 마이그레이션 시 pending으로 채워짐
    role: Mapped[str] = mapped_column(String(20), server_default="pending")
    # 이메일 인증 여부. 가입 직후 False → 확인메일 링크 클릭하면 True (봇 대량가입 차단)
    # 기존 계정은 마이그레이션에서 True로 백필 (잠기지 않게)
    email_verified: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # 토큰 버전. 비번 재설정·차단 시 +1 → 그 이전에 발급된 JWT는 즉시 무효(세션 강제 종료)
    token_version: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

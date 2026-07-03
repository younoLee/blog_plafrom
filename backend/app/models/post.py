from datetime import datetime
from sqlalchemy import String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    # 커버(대표) 이미지 URL — 선택. /api/upload 로 올린 이미지 URL을 저장. 없으면 None
    cover_image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 작성자. 기존(로그인 전) 글은 owner 없음 → nullable
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    # 공개범위: 'public'(전체공개) | 'subscribers'(구독자공개) | 'private'(나만 보기)
    # 'subscribers'가 11자라 varchar(20)으로 둠. 기존 글은 public
    visibility: Mapped[str] = mapped_column(String(20), server_default="public")
    # server_default=func.now(): DB가 INSERT 시 현재 시각을 채움
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # onupdate: UPDATE 될 때마다 시각 자동 갱신
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

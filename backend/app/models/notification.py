from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Notification(Base):
    """인앱 알림 — 구독+알림 켠 글쓴이가 새 글을 쓰면 구독자에게 한 줄 생성.
    헤더 종 아이콘의 안 읽음 배지·목록이 이 테이블을 읽는다."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 받는 사람. 계정 삭제 시 함께 삭제
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # 알림이 가리키는 새 글. 글 삭제 시 알림도 함께 삭제(깨진 링크 방지)
    post_id: Mapped[int] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), index=True
    )
    read: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

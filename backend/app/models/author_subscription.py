from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuthorSubscription(Base):
    """로그인 사용자(subscriber)가 글쓴이(author)를 구독하는 관계."""
    __tablename__ = "author_subscriptions"
    # 같은 사람을 두 번 구독 못 하게
    __table_args__ = (UniqueConstraint("subscriber_id", "author_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    subscriber_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # 글쓴이가 이 구독 신청을 승인했는지. 신청 직후엔 false(대기), 글쓴이가 승인하면 true.
    # 승인된 구독만 '구독자공개' 글 열람·알림 권한을 갖는다.
    approved: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # 이 글쓴이의 새 글을 이메일로 알림받을지 (승인된 뒤 별도로 켜는 opt-in). 기본 꺼짐.
    notify: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

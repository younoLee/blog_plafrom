from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Notification(Base):
    """인앱 알림 — 헤더 종 아이콘의 안 읽음 배지·목록이 이 테이블을 읽는다.

    두 종류가 한 테이블에 산다:
      - **새 글**  (comment_id IS NULL) — 구독+알림 켠 사람이 받는다.
      - **새 댓글**(comment_id 있음)   — 글쓴이 본인이 받는다.

    종류를 열(`kind`)로 따로 두지 않고 comment_id의 유무로 가른다. 값이 둘로 표현되면
    언젠가 어긋나고(kind='comment'인데 comment_id가 NULL 같은 행), 그때 어느 쪽이
    맞는지 알 수 없다. 링크를 걸려면 어차피 comment_id가 있어야 하므로 그것만 둔다.
    """

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 받는 사람. 계정 삭제 시 함께 삭제
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # 알림이 가리키는 글. 글 삭제 시 알림도 함께 삭제(깨진 링크 방지)
    post_id: Mapped[int] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), index=True
    )
    # 새 댓글 알림이면 그 댓글. 새 글 알림이면 NULL.
    # 댓글이 지워지면(모더레이션) 알림도 같이 지운다 — 안 지우면 종에는 남아 있는데
    # 눌러도 아무 데도 안 가는 줄이 된다.
    comment_id: Mapped[int | None] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE"), nullable=True, index=True
    )
    read: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

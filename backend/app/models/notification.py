from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# 글에 안 매인 알림의 종류. 문자열을 두 곳에 손으로 적으면 언젠가 오타로 갈라진다 —
# 이 저장소가 'banned' 철자를 BANNED_ROLE 로 모은 것과 같은 이유다.
NOTIFY_SUBSCRIBE_REQUEST = "subscribe_request"
NOTIFY_SUBSCRIBE_APPROVED = "subscribe_approved"


class Notification(Base):
    """인앱 알림 — 헤더 종 아이콘의 안 읽음 배지·목록이 이 테이블을 읽는다.

    세 종류가 한 테이블에 산다:
      - **새 글**      (post_id 있음 · comment_id 없음) — 구독+알림 켠 사람이 받는다.
      - **새 댓글**    (post_id 있음 · comment_id 있음) — 글쓴이 본인이 받는다.
      - **구독 신청**  (post_id 없음 · actor_id 있음 · kind='subscribe_request')
                       — 글쓴이가 받는다. 2026-08-27 추가.
      - **구독 승인**  (post_id 없음 · actor_id 있음 · kind='subscribe_approved')
                       — 신청자가 받는다. 2026-09-05 추가.

    종류를 열(`kind`)로 따로 두지 않고 **어느 칸이 채워졌는가**로 가른다. 값이 둘로
    표현되면 언젠가 어긋나고(kind='comment'인데 comment_id가 NULL 같은 행), 그때 어느
    쪽이 맞는지 알 수 없다. 링크를 걸려면 어차피 그 id가 있어야 하므로 그것만 둔다.

    ⚠️ **2026-09-05에 그 규칙에 예외를 하나 뒀다.** 위 규칙은 글에 안 매인 알림이
    한 종류일 때만 성립했는데, 구독 승인이 생기면서 둘이 됐다 — 신청과 승인은
    post_id NULL + actor_id 로 **모양이 완전히 같다**. 방향(누가 받는가)으로 갈리긴
    하지만 그걸 알려면 author_subscriptions 를 조인해야 하고, 구독을 취소한 뒤에는
    그 조인이 답을 못 준다. 화면 문구가 조인의 생사에 매이면 안 된다.
    그래서 `kind` 는 **post_id 가 NULL 일 때만 읽는다.** 글에 매인 알림에 대해서는
    아예 안 보므로, 위 주석이 경고한 어긋남(kind='comment'인데 comment_id NULL)은
    생기지 않는다.
    """

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 받는 사람. 계정 삭제 시 함께 삭제
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # 알림이 가리키는 글. 글 삭제 시 알림도 함께 삭제(깨진 링크 방지).
    # **NULL 이면 글에 안 매인 알림**이다(구독 신청). 2026-08-27까지 NOT NULL 이라
    # 그런 알림을 만들 수조차 없었고, 그래서 구독 신청이 글쓴이에게 아무 신호도 못 냈다.
    post_id: Mapped[int | None] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # 이 알림을 일으킨 사람. **글에 안 매인 알림에만 채운다.**
    # 새 글·새 댓글은 '누가'를 글을 통해 알 수 있어서(posts.owner_id) 채우지 않는다 —
    # 채우면 같은 정보가 두 곳에 살고 언젠가 어긋난다.
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # 새 댓글 알림이면 그 댓글. 새 글 알림이면 NULL.
    # 댓글이 지워지면(모더레이션) 알림도 같이 지운다 — 안 지우면 종에는 남아 있는데
    # 눌러도 아무 데도 안 가는 줄이 된다.
    comment_id: Mapped[int | None] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # 글에 **안 매인** 알림의 종류: 'subscribe_request' | 'subscribe_approved'.
    # 글에 매인 알림(새 글·새 댓글)에는 NULL 이고 아무도 읽지 않는다 — 위 주석 참고.
    kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

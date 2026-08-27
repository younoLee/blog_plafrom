"""notifications: post_id 를 nullable 로 풀고 actor_id 를 더한다 — 글에 안 매인 알림

## 왜

구독은 '신청 → 글쓴이 승인' 구조인데, 신청이 들어와도 **글쓴이에게 아무 신호도 안 갔다.**
신청한 사람은 '승인 대기중' 배지를 무기한 보고, 글쓴이는 신청이 온 사실 자체를 모른다.
결과적으로 구독자공개 글이 영영 안 열린다.

알림을 만들면 되는데 **지금 스키마로는 만들 수조차 없었다.** `post_id` 가 NOT NULL 이라
모든 알림이 글에 매여 있어야 했고, 구독 신청은 가리킬 글이 없다.

## actor_id 를 왜 같이 더하나

지금까지 '누가'는 글을 통해 알 수 있었다(`posts.owner_id`). 글에 안 매인 알림에는 그
경로가 없어서 "누가 구독을 신청했나"를 담을 자리가 필요하다.

기존 두 종류에는 채우지 않는다. 채우면 같은 정보가 두 곳에 살고(글쓴이 = 글의 주인 =
actor), 언젠가 어긋난다. 이 테이블은 그 원칙을 이미 쓰고 있다 — 종류를 `kind` 열이
아니라 `comment_id` 의 유무로 가르는 이유가 같다.

## 세 종류를 여전히 열 없이 가른다

  · post_id 있음 · comment_id 없음  → 새 글
  · post_id 있음 · comment_id 있음  → 새 댓글
  · post_id 없음 · actor_id 있음    → 구독 신청

## downgrade 는 데이터를 버린다

post_id 를 NOT NULL 로 되돌리려면 그 값이 없는 행(구독 신청 알림)을 지워야 한다.
되돌릴 수 없는 쪽이므로 여기 적어둔다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f8a9b0c1d2e3"
down_revision: str | None = "e7f8a9b0c1d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("notifications", "post_id", existing_type=sa.Integer(), nullable=True)
    op.add_column("notifications", sa.Column("actor_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_notifications_actor_id_users",
        "notifications",
        "users",
        ["actor_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_notifications_actor_id", "notifications", ["actor_id"])


def downgrade() -> None:
    # post_id 가 없는 행은 NOT NULL 로 되돌릴 수 없다. 지우고 되돌린다.
    op.execute("delete from notifications where post_id is null")
    op.drop_index("ix_notifications_actor_id", table_name="notifications")
    op.drop_constraint("fk_notifications_actor_id_users", "notifications", type_="foreignkey")
    op.drop_column("notifications", "actor_id")
    op.alter_column("notifications", "post_id", existing_type=sa.Integer(), nullable=False)

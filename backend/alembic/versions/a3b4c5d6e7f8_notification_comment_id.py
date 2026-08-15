"""notifications.comment_id — 댓글이 달려도 글쓴이는 아무 데서도 못 봤다

2026-08-14 격차검사 11번. 이 블로그는 **익명 댓글이 열려 있는데**(IP당 시간당 20개)
알림은 '새 글' 한 종류뿐이었다. 즉 누가 댓글을 달면 글쓴이가 그 글에 다시 들어가
직접 보기 전까지 아무도 모른다. 종은 있는데 이 사건만 종을 안 울렸다.

comment_id의 유무로 종류를 가른다(kind 열을 따로 두지 않는다 — 값이 둘로 표현되면
언젠가 어긋난다). NULL이면 새 글 알림, 값이 있으면 그 댓글 알림이다.

기존 행은 전부 새 글 알림이므로 NULL이 맞다 — 백필이 필요 없다.

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3b4c5d6e7f8"
down_revision: str | None = "f2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("comment_id", sa.Integer(), nullable=True))
    op.create_index(
        "ix_notifications_comment_id", "notifications", ["comment_id"], unique=False
    )
    # 댓글이 지워지면 알림도 같이 지운다. 안 지우면 종에는 남아 있는데 눌러도
    # 아무 데도 안 가는 줄이 된다(모더레이션으로 댓글을 지우는 경로가 실제로 있다).
    op.create_foreign_key(
        "notifications_comment_id_fkey",
        "notifications",
        "comments",
        ["comment_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("notifications_comment_id_fkey", "notifications", type_="foreignkey")
    op.drop_index("ix_notifications_comment_id", table_name="notifications")
    op.drop_column("notifications", "comment_id")

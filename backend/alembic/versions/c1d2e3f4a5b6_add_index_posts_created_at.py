"""add index on posts.created_at (정렬 핫패스)

Revision ID: c1d2e3f4a5b6
Revises: b7f1c4e29a03
Create Date: 2026-07-24

목록/검색/연재/최근글이 전부 ORDER BY created_at 인데 인덱스가 없어 매번 풀 정렬이었다.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "c1d2e3f4a5b6"
down_revision = "b7f1c4e29a03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(op.f("ix_posts_created_at"), "posts", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_posts_created_at"), table_name="posts")

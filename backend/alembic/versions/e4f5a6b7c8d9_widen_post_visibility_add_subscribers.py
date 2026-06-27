"""widen posts.visibility and split into 3 tiers (public/subscribers/private)

Revision ID: e4f5a6b7c8d9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-27 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4f5a6b7c8d9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 'subscribers'(11자) 저장 가능하도록 varchar(10) → varchar(20)
    op.alter_column(
        'posts', 'visibility',
        existing_type=sa.String(length=10),
        type_=sa.String(length=20),
        existing_nullable=False,
        existing_server_default='public',
    )
    # 기존 'private'는 UI상 '일부공개(구독자에게만)' 의미였음 → 의미 보존 위해 'subscribers'로 이관.
    # 이제 'private'는 '나만 보기'라는 새 의미로 사용됨.
    op.execute("UPDATE posts SET visibility='subscribers' WHERE visibility='private'")


def downgrade() -> None:
    # 되돌릴 때: 'subscribers'를 다시 'private'으로 합친 뒤(varchar(10)에 안 들어가므로) 컬럼 축소
    op.execute("UPDATE posts SET visibility='private' WHERE visibility='subscribers'")
    op.alter_column(
        'posts', 'visibility',
        existing_type=sa.String(length=20),
        type_=sa.String(length=10),
        existing_nullable=False,
        existing_server_default='public',
    )

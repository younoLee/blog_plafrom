"""add is_pro to users

Revision ID: a1b2c3d4e5f6
Revises: 3e99ae1b58c1
Create Date: 2026-06-27 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '3e99ae1b58c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 기존 계정은 server_default='false' 덕분에 모두 비유료로 채워짐
    op.add_column('users', sa.Column('is_pro', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    op.drop_column('users', 'is_pro')

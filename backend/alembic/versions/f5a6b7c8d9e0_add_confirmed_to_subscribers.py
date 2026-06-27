"""add confirmed to subscribers (double opt-in)

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-06-27 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f5a6b7c8d9e0'
down_revision: Union[str, None] = 'e4f5a6b7c8d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 더블옵트인 컬럼. server_default=true로 추가 → 기존 구독자(정책 이전 가입자)는
    # 모두 confirmed=True로 백필(메일 계속 수신). NOT NULL이라 기본값 없이 추가하면
    # 기존 행이 NULL이 돼 실패하므로 server_default가 꼭 필요.
    op.add_column(
        'subscribers',
        sa.Column('confirmed', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    # 백필 끝났으니 서버기본값 제거 → 이후 신규 INSERT는 앱(모델 default=False)이 정함.
    op.alter_column('subscribers', 'confirmed', server_default=None)


def downgrade() -> None:
    op.drop_column('subscribers', 'confirmed')

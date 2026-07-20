"""create ai_hourly_usage

Revision ID: b7f1c4e29a03
Revises: 2a2a9af10b7c
Create Date: 2026-07-20 04:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7f1c4e29a03'
down_revision: Union[str, None] = '2a2a9af10b7c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 시간당 '시도' 카운터. 인메모리 레이트리밋이 재시작에 지워지는 걸 메꾼다.
    # 기존 행을 건드리지 않는 신규 테이블이라 백필이 필요 없다(빈 카운터 = 0회 사용).
    op.create_table(
        'ai_hourly_usage',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('hour', sa.DateTime(timezone=True), nullable=False),
        sa.Column('count', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'hour', name='uq_ai_hourly_usage_user_hour'),
    )
    op.create_index(op.f('ix_ai_hourly_usage_user_id'), 'ai_hourly_usage', ['user_id'])
    op.create_index(op.f('ix_ai_hourly_usage_hour'), 'ai_hourly_usage', ['hour'])


def downgrade() -> None:
    op.drop_index(op.f('ix_ai_hourly_usage_hour'), table_name='ai_hourly_usage')
    op.drop_index(op.f('ix_ai_hourly_usage_user_id'), table_name='ai_hourly_usage')
    op.drop_table('ai_hourly_usage')

"""create ai_guard_violation

Revision ID: d4e5f6a7b8c9
Revises: c1d2e3f4a5b6
Create Date: 2026-08-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 시간당 '가드 위반' 카운터 — 반복 인젝션 시도를 비싸게 만든다.
    # ai_hourly_usage(시도)와 모양은 같지만 세는 대상이 다르다: 정상 사용자는 평생 0이라
    # 훨씬 낮은 임계로 끊을 수 있다. 신규 테이블이라 백필 없음(빈 카운터 = 위반 0회).
    op.create_table(
        'ai_guard_violation',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('hour', sa.DateTime(timezone=True), nullable=False),
        sa.Column('count', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'hour', name='uq_ai_guard_violation_user_hour'),
    )
    op.create_index(op.f('ix_ai_guard_violation_user_id'), 'ai_guard_violation', ['user_id'])
    op.create_index(op.f('ix_ai_guard_violation_hour'), 'ai_guard_violation', ['hour'])


def downgrade() -> None:
    op.drop_index(op.f('ix_ai_guard_violation_hour'), table_name='ai_guard_violation')
    op.drop_index(op.f('ix_ai_guard_violation_user_id'), table_name='ai_guard_violation')
    op.drop_table('ai_guard_violation')

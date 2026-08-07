"""create push_subscriptions

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 브라우저 푸시 구독('어느 기기로 보낼지'). 알림을 받겠다는 의사는 여전히
    # author_subscriptions.notify가 갖고, 여기는 경로만 갖는다 — 그래서 기존
    # 테이블을 건드리지 않는다. 신규 테이블이라 백필 없음(구독 0건에서 시작).
    op.create_table(
        'push_subscriptions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('endpoint', sa.Text(), nullable=False),
        sa.Column('p256dh', sa.String(length=255), nullable=False),
        sa.Column('auth', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_push_subscriptions_user_id'), 'push_subscriptions', ['user_id'])
    # endpoint 유니크 — 같은 브라우저가 재구독하면 벤더가 같은 endpoint를 돌려준다.
    # 이게 없으면 행이 쌓여 알림이 중복 발송된다. 모델의 unique=True와 같은 형태로
    # '유니크 인덱스'를 낸다(제약 + 별도 인덱스로 내면 autogenerate가 영구 드리프트를 본다).
    op.create_index(
        op.f('ix_push_subscriptions_endpoint'), 'push_subscriptions', ['endpoint'], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_push_subscriptions_endpoint'), table_name='push_subscriptions')
    op.drop_index(op.f('ix_push_subscriptions_user_id'), table_name='push_subscriptions')
    op.drop_table('push_subscriptions')

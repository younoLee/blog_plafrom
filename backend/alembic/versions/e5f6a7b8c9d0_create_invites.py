"""create invites

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 관리자 발급 1회용 가입 초대. 지금까지 '초대제'는 403 메시지였을 뿐 절차가
    # 코드에 없었다(계정은 DB 직접 수정으로 만들었다). 이 테이블이 그 절차다.
    #
    # 토큰은 원문이 아니라 sha256 해시로만 들어온다 → DB 유출만으로는 가입 불가.
    # used_at이 1회용을 강제하는 컬럼이고, 소각은 조건부 UPDATE(used_at IS NULL)로
    # 원자적으로 한다. 신규 테이블이라 백필 없음(기존 계정은 초대 없이 존재).
    op.create_table(
        'invites',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('used_by_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['used_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_invites_email'), 'invites', ['email'])
    # 유니크를 '제약'이 아니라 **유니크 인덱스**로 낸다. 모델의
    # mapped_column(..., unique=True, index=True)가 만드는 것이 정확히 이것이라서다.
    # 제약 + 별도 인덱스로 내면 같은 컬럼에 인덱스가 둘 생기고, 무엇보다
    # `alembic revision --autogenerate`가 이 테이블에 영구적인 가짜 드리프트를
    # 보고하게 된다 — 그러면 다음에 오는 진짜 드리프트를 못 알아본다.
    # 기존 테이블도 이 형태다(86ed6449b339_create_users_table.py).
    op.create_index(op.f('ix_invites_token_hash'), 'invites', ['token_hash'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_invites_token_hash'), table_name='invites')
    op.drop_index(op.f('ix_invites_email'), table_name='invites')
    op.drop_table('invites')

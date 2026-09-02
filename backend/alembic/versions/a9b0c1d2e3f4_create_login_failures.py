"""create login_failures

Revision ID: a9b0c1d2e3f4
Revises: f8a9b0c1d2e3
Create Date: 2026-09-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9b0c1d2e3f4'
down_revision: Union[str, None] = 'f8a9b0c1d2e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 계정 단위 로그인 실패 카운터. 지금까지 로그인 방어는 slowapi의 10/분뿐이었고
    # 그 키는 IP다 — 공격자가 주소를 나누면 한 계정에 대한 상한이 사실상 bcrypt
    # 처리량(vCPU당 30~40건/분)만 남는다. WAF rate-based 룰은 월 과금이라 안 쓰기로
    # 했으므로 계정 축은 앱이 든다. 판정 로직과 임계값은 routers/auth.py에 있다.
    #
    # 신규 테이블이라 백필이 없다. 행이 없는 것 = 최근 실패가 없는 것이라
    # 기존 계정은 전부 '깨끗한 상태'로 시작한다(마이그레이션이 아무도 안 잠근다).
    op.create_table(
        'login_failures',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('fail_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('window_start', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    # 유니크를 '제약'이 아니라 **유니크 인덱스**로 낸다. 모델의
    # mapped_column(..., unique=True, index=True)가 만드는 것이 정확히 이것이고,
    # 제약 + 별도 인덱스로 내면 autogenerate가 이 테이블에 영구적인 가짜 드리프트를
    # 본다(마이그레이션 e5f6a7b8c9d0 주석과 같은 처방).
    #
    # 유니크가 곧 '계정당 1행'이고, 그게 이 테이블이 무한히 자라지 않는 이유다.
    # 창이 지난 행은 지우는 게 아니라 다음 실패가 덮어쓰므로(ON CONFLICT DO UPDATE)
    # 정리 작업이 따로 필요 없다. 계정 삭제는 위 CASCADE가 같이 치운다.
    op.create_index(
        op.f('ix_login_failures_user_id'), 'login_failures', ['user_id'], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_login_failures_user_id'), table_name='login_failures')
    op.drop_table('login_failures')

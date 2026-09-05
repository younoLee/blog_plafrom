"""create admin_actions — 관리자 조치의 감사 기록

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-09-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2d3e4f5a6b7'
down_revision: Union[str, None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 차단·승인취소·계정삭제·Pro 토글은 남의 글과 접근 권한을 되돌릴 수 없게 바꾸는데
    # 그 사실이 어디에도 안 남았다(09-04 검사 GAP-2 — admin 라우터에 로깅 0줄).
    # 초대 목록이 '누구를 언제 들였나'의 답인 것과 짝으로, 이 표가 '누구를 언제
    # 내보냈나'의 답이다.
    #
    # target 에 FK 를 안 거는 이유는 models/admin_action.py 에 적었다 — 계정 삭제를
    # 기록하는 것이 주 용도라, FK 면 그 행이 CASCADE 로 같이 지워지거나 누구였는지를 잃는다.
    op.create_table(
        "admin_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("actor_email", sa.String(length=255), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("target_email", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("detail", sa.String(length=200), server_default="", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_admin_actions_target_id"), "admin_actions", ["target_id"])
    op.create_index(op.f("ix_admin_actions_action"), "admin_actions", ["action"])
    op.create_index(op.f("ix_admin_actions_created_at"), "admin_actions", ["created_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_admin_actions_created_at"), table_name="admin_actions")
    op.drop_index(op.f("ix_admin_actions_action"), table_name="admin_actions")
    op.drop_index(op.f("ix_admin_actions_target_id"), table_name="admin_actions")
    op.drop_table("admin_actions")

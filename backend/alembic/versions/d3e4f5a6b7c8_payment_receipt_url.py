"""payments: receipt_url 추가 — 영수증을 다시 볼 수 있게

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-09-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd3e4f5a6b7c8'
down_revision: Union[str, None] = 'c2d3e4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 토스 승인 응답에는 영수증 주소(receipt.url)가 들어 있는데 지금까지 버렸다.
    # 그래서 결제한 사람도 관리자도 '얼마를 언제 냈나'를 확인할 방법이 없었다
    # (09-04 검사 GAP-7). 카드사 명세서 말고는 근거가 없는 상태다.
    #
    # 옛 행은 NULL 이다 — 그때 응답을 저장 안 했으니 소급할 값이 없다. 화면은 값이
    # 있을 때만 링크를 그린다(없는 것을 '실패'로 읽지 않게).
    op.add_column("payments", sa.Column("receipt_url", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("payments", "receipt_url")

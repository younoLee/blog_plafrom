"""ai_usage에 실제 토큰 사용량 — 횟수 캡이 못 보던 비용

2026-08-11 공백검사: 이 저장소에는 **토큰을 세는 코드가 한 줄도 없었다.**
캡이 전부 '호출 횟수'라 Haiku 20회와 Fable 20회가 같게 취급되는데, max_tokens가
2500 대 8000이고 단가도 달라 실제 청구는 수십 배까지 벌어진다. 게다가 Anthropic
청구는 AWS 밖이라 watch.sh가 보는 AWS Budgets가 원리적으로 못 본다 — 알아채는
시점이 다음 명세서였다.

server_default="0"을 두는 이유: 기존 행이 NULL이 되면 SUM이 NULL을 만들고,
그걸 캡과 비교하면 조용히 통과한다(fail-open). 기본값을 DB에 박아 그 경로를 없앤다.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ai_usage",
        sa.Column("input_tokens", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "ai_usage",
        sa.Column("output_tokens", sa.BigInteger(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("ai_usage", "output_tokens")
    op.drop_column("ai_usage", "input_tokens")

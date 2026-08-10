"""status_checks에 disk_ok 추가 — 감시 창의 나머지 절반

2026-08-10에 `/api/status`에 `disk` 필드를 실었는데(pgdata가 EC2 루트 볼륨에 살고
감시는 AWS 밖에서 돌아 서버 안을 볼 수단이 그 응답뿐이다), **기록은 안 하고 있었다.**
그래서 매시 감시가 두 번 도는 사이에 임계를 넘었다가 돌아오면 흔적이 0이었다 —
같은 날 보안검사가 "그 창이 절반만 서 있다"고 지적한 자리다.

**nullable인 이유**: 이 컬럼이 생기기 전 행이 이미 수만 개다(운영 29,758행 이상).
소급할 값이 없으므로 NULL은 '그때는 안 쟀다'는 뜻이고, 집계(services/status.py의
get_history)가 NULL을 분모에서 빼서 **안 쟀던 과거가 초록으로 칠해지지 않게** 한다.
`server_default`를 주지 않는 것도 같은 이유다 — 기본값을 주면 과거가 전부 '정상'이 된다.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-08-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: str | None = "b8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("status_checks", sa.Column("disk_ok", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("status_checks", "disk_ok")

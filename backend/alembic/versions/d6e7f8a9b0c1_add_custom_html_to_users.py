"""users.custom_html 추가 — 블로그 '내 문장'(제목 아래·사이드바·푸터)

스킨(custom_css)이 '어떻게 보이나'라면 이건 '무엇이 적히나'다. 두 컬럼을 나란히 두는
이유는 성질이 다르기 때문이다 — CSS는 `<`를 통째로 막아 끝나지만, 여기는 `<`가 목적이라
허용 목록 재작성이 필요하다(app/core/html_slots.py).

왜 세 컬럼이 아니라 JSON 한 칸인가:
  자리가 셋(intro·aside·footer)이고, 넷째가 생길 때 또 마이그레이션을 하고 싶지 않다.
  이 값은 **검색하지도 조인하지도 않는다** — 한 사람 행을 읽을 때 통째로 딸려 오는
  덩어리다. 그런 데이터를 컬럼으로 펴는 건 이득이 없다.
  Postgres의 JSON 타입이 아니라 Text에 JSON 문자열로 담는다. 앱이 어차피 통째로
  읽고 통째로 쓰며, sqlite(테스트)와 Postgres(운영)에서 같은 코드가 돌아야 한다.

NULL = '아무것도 안 적었다'. 기본값을 `{}`로 채우지 않는다 — 백필은 3행짜리 테이블에서
아낄 게 없고, NULL과 빈 객체가 같은 뜻이면 상태가 둘로 갈린다.

revision: d6e7f8a9b0c1
down_revision: c5d6e7f8a9b0 (users.handle)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d6e7f8a9b0c1"
down_revision: str | None = "c5d6e7f8a9b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("custom_html", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "custom_html")

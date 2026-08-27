"""subscribers 테이블 제거 — 2026-07-31에 폐지된 뉴스레터의 마지막 흔적

## 왜 지우나

뉴스레터 구독은 2026-07-18에 글쓴이별 계정 구독(`author_subscriptions`)으로 일원화되면서
기능이 없어졌고, 07-31에 수집 라우트(POST/confirm/unsubscribe)를 뗐다. 그때 관리자용
조회·삭제 둘만 남겼는데, 이유가 이랬다:

  "운영 DB에 이미 쌓인 구독자 주소는 개인정보라, 폐지했다고 조회 수단까지 없애면
   남은 것을 확인하고 지울 방법이 사라진다."

**2026-08-27에 운영 DB를 세어보니 0행이었다.** 즉 그 문단이 걱정한 '이미 쌓인 주소'는
없다. 그리고 이 테이블에 **쓰는 코드가 저장소에 하나도 없다** — 모델 정의와 그 두
라우트뿐이라, 0행에 고정돼 있고 늘어날 수도 없다.

남겨둘 근거가 사라졌는데 화면도 없었다(`frontend/src/api/`에 subscribers.ts가 아예
없다). '만들어놨는데 못 쓰는' 상태라, 답은 정리 화면을 만드는 게 아니라 함께 없애는
것이었다.

## 왜 이 순서인가

테이블을 먼저 지우고 라우터를 남기면 그 라우트가 500을 낸다. 라우터를 먼저 지우고
테이블을 남기면 닿을 길이 없는 데이터가 남는다. 같은 커밋에서 둘 다 지운다.

## downgrade

테이블 구조만 되돌린다. **데이터는 못 되돌린다** — 0행이라 되돌릴 것이 없지만, 그
사실을 여기 적어두는 이유는 다음에 이 파일을 보는 사람이 "downgrade 하면 복구된다"고
읽지 않게 하려는 것이다. 진짜로 필요하면 백업(`keep/latest.sql.gz`)에서 꺼내야 한다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: str | None = "d6e7f8a9b0c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 인덱스는 테이블과 함께 사라진다. 명시적으로 지우면 이미 없는 경우에 실패한다.
    op.drop_table("subscribers")


def downgrade() -> None:
    op.create_table(
        "subscribers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_subscribers_email", "subscribers", ["email"], unique=True)

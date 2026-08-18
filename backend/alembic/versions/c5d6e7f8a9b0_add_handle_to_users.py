"""users.handle — 계정마다 자기 블로그 주소를 갖는다

2026-08-18. 지금까지 이 사이트의 블로그 주소는 `/blog` 하나였다. 같은 날 오전에 만든
스킨(users.custom_css)도 그래서 '주인의 것 하나'만 화면에 나갔다. 이 컬럼이 그 제약을
푸는 재료다 — `/@handle` 주소를 만들어 그 사람의 글과 그 사람의 스킨을 보여준다.

**이메일에서 유도하지 않는다.** 2026-08-10 보안검사에서 `email.split("@")[0]`이 무인증
경로로 새던 걸 끊었고(display_name이 그래서 생겼다), 핸들은 주소에 그대로 박히므로
그때보다 더 많이 노출된다. 그래서 NULL로 시작하고 **사람이 직접 정한다.**
NULL = '아직 안 정함' = 그 계정에는 개인 블로그 주소가 없다(404).

왜 display_name을 안 쓰나 — 그건 유니크가 아니고 한글·공백·이모지가 들어간다. 주소에
쓰면 인코딩 문제가 생기고(한글 태그 허브가 403이던 2026-08-17의 그 문제다), 두 사람이
같은 이름을 정하면 주소가 충돌한다.

**유니크 인덱스는 lower(handle)에 건다.** 컬럼 자체에도 unique를 걸지만, 그것만으로는
`Yuno`와 `yuno`가 둘 다 만들어진다. 주소는 대소문자를 구분하지 않는 게 상식이라
그 순간부터 어느 쪽이 열리는지가 행 순서에 달린다 — 이메일에서 이미 겪은 함정이고
같은 처방(uq_users_email_lower)을 쓴다.

길이 20: 주소에 들어가는 값이라 짧아야 하고, 입력 층(schemas)이 2~20자와 문자 집합을
강제한다. DB는 담을 수 있는 한계만 정한다.

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5d6e7f8a9b0"
down_revision: str | None = "b4c5d6e7f8a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("handle", sa.String(20), nullable=True))
    op.create_index(
        "uq_users_handle_lower",
        "users",
        [sa.text("lower(handle)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_users_handle_lower", table_name="users")
    op.drop_column("users", "handle")

"""users.custom_css — 블로그 외형을 코드 배포 없이 바꾼다

2026-08-18. 지금까지 이 블로그의 색·모서리는 화면 파일 16곳에 하드코딩돼 있었고
(애플 블루 #0071e3가 143번), 외형을 바꾸려면 프론트를 다시 빌드해 배포해야 했다.
같은 날 프론트의 그 값들을 CSS 변수로 뺐다(index.css의 @theme). 이 컬럼은 그
변수들을 **DB에서** 덮어쓰기 위한 자리다.

왜 users에 두나 — 이 사이트는 아직 블로그가 하나이고 주소도 /blog 하나뿐이라
'주인(admin)의 스킨'이 곧 사이트의 스킨이다. 그래도 컬럼을 사이트 설정 표가 아니라
users에 두는 이유는, 나중에 글쓴이마다 자기 블로그 주소가 생기면 **같은 컬럼이
그대로 쓰이기 때문**이다. 그때 마이그레이션이 다시 필요 없다.

Text인 이유 — 길이 상한은 입력 층(schemas/user.py의 SkinUpdate, 50KB)이 맡는다.
DB에서 String(n)으로 자르면 상한을 늘릴 때마다 마이그레이션이 필요하고, 넘칠 때
422가 아니라 DB 오류로 터진다.

NULL = '기본 스킨'. 빈 문자열과 구분한다 — 빈 문자열은 '스킨을 만들었다가 다 지웠다'는
뜻이라 화면 동작은 같아도 의미가 다르다.

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4c5d6e7f8a9"
down_revision: str | None = "a3b4c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("custom_css", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "custom_css")

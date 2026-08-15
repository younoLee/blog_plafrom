"""posts.owner_id FK에 ON DELETE CASCADE — users를 참조하는 FK 중 유일하게 없었다

2026-08-14 격차검사 13번. users를 참조하는 FK는 아홉 개인데(llm_credentials·
notifications·author_subscriptions×2·payments·ai_usage×3·push_subscriptions·
comments·invites×2) **posts.owner_id 하나만 ondelete가 비어 있었다.** 비어 있으면
Postgres 기본값은 NO ACTION이라, 글이 남아 있는 사용자를 지우려는 시도는 그냥
거부된다.

왜 SET NULL이 아니라 CASCADE인가 — **앱이 이미 CASCADE로 행동하고 있다.**
admin.delete_user는 사용자를 지우기 전에 `DELETE FROM posts WHERE owner_id=?`를
직접 돌린다. 즉 '사용자 삭제 = 그 사람 글도 삭제'가 이 저장소의 결정이고,
DB에는 그 결정이 안 적혀 있었을 뿐이다. SET NULL을 고르면 지운 사람의 글이
주인 없는 공개 글로 남는데, 그건 앱이 한 번도 의도한 적 없는 상태다.

그래서 이건 동작을 바꾸는 마이그레이션이 아니다 — **앱 코드에만 있던 규칙을 DB에
옮겨 적는 것**이다. 값은 그대로고, 대신 psql·복원 훈련·앞으로 생길 다른 삭제 경로가
그 규칙 밖으로 빠져나갈 수 없게 된다. (지금까지 그 경로들은 FK 위반으로 막히거나,
앱이 지우는 순서에 의존했다.)

제약 이름을 하드코딩하지 않고 조회하는 이유: 원래 마이그레이션(d6c9c2009ad6)이
`create_foreign_key(None, ...)`로 만들어 이름을 Postgres가 붙였다. 보통
`posts_owner_id_fkey`지만, 복원된 DB나 손으로 만든 환경에서 다를 수 있다.
이름을 틀리면 drop이 실패하고 그건 곧 컨테이너 기동 실패다.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: str | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FK_NAME = "posts_owner_id_fkey"

# posts.owner_id 하나만 거는 외래키의 실제 이름을 찾는다.
_FIND_FK = sa.text("""
    SELECT con.conname
    FROM pg_constraint con
    JOIN pg_class rel ON rel.oid = con.conrelid
    JOIN pg_namespace ns ON ns.oid = rel.relnamespace
    WHERE con.contype = 'f'
      AND rel.relname = 'posts'
      AND ns.nspname = current_schema()
      AND con.conkey = ARRAY[
        (SELECT attnum FROM pg_attribute
          WHERE attrelid = rel.oid AND attname = 'owner_id' AND NOT attisdropped)
      ]
""")


def _rebuild(ondelete: str | None) -> None:
    conn = op.get_bind()
    existing = conn.execute(_FIND_FK).scalar()
    if existing:
        op.drop_constraint(existing, "posts", type_="foreignkey")
    op.create_foreign_key(FK_NAME, "posts", "users", ["owner_id"], ["id"], ondelete=ondelete)


def upgrade() -> None:
    _rebuild("CASCADE")


def downgrade() -> None:
    # 되돌리면 ondelete 없는(=NO ACTION) 원래 모양으로.
    _rebuild(None)

"""users(lower(email)) 유니크 인덱스 — 대소문자만 다른 중복 계정을 구조적으로 차단

Revision ID: b8c9d0e1f2a3
Revises: f6a7b8c9d0e1
Create Date: 2026-08-09

2026-08-07에 조회를 대소문자 무시로 바꾸면서(`_find_user_by_email`) 백로그로 남긴 것.
그때 미룬 이유는 하나였다 — **기존 데이터에 중복이 있으면 이 마이그레이션이 실패하고,
프로드는 컨테이너 기동 시 `alembic upgrade head`를 돌리므로 그 실패가 곧 기동 실패다.**

2026-08-09에 확인했다. 정지 직전 백업(`keep/latest.sql.gz`)의 users는 3행이고
대소문자 무시 중복 0건이었다. 그래서 지금 올린다.

그래도 사전 점검을 남긴다. 백업을 본 시점과 실제로 올라가는 시점이 다르고,
복원된 DB나 다른 환경에서 돌 수도 있다. 점검 없이 실패하면 Postgres가 주는 건
"could not create unique index"와 인덱스 이름뿐이라 **어느 주소가 문제인지 모른다.**
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'b8c9d0e1f2a3'
down_revision: str | None = 'f6a7b8c9d0e1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 사전 점검 — 막을 수 없는 실패라면, 최소한 무엇을 고쳐야 하는지는 말해준다.
    dups = op.get_bind().execute(sa.text(
        "SELECT lower(email) AS e, count(*) AS n, string_agg(id::text, ',' ORDER BY id) AS ids "
        "FROM users GROUP BY 1 HAVING count(*) > 1 ORDER BY 1"
    )).all()
    if dups:
        detail = "; ".join(f"{d.e} (id {d.ids})" for d in dups)
        raise RuntimeError(
            "대소문자만 다른 중복 계정이 있어 유니크 인덱스를 만들 수 없습니다: "
            f"{detail}. 어느 쪽을 남길지는 사람이 정해야 합니다 — 글·댓글이 붙어 있는 "
            "계정을 남기고 나머지를 지운 뒤 다시 올리세요."
        )

    op.create_index(
        "uq_users_email_lower", "users", [sa.text("lower(email)")], unique=True
    )


def downgrade() -> None:
    op.drop_index("uq_users_email_lower", table_name="users")

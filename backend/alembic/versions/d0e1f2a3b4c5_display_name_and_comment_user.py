"""users.display_name + comments.user_id — 이메일이 화면으로 새던 경로를 끊는다

2026-08-10 보안검사에서 나온 두 건이 뿌리가 같아 한 마이그레이션으로 묶는다.

■ 왜 display_name이 필요한가
이 앱은 화면에 보일 이름이 필요할 때마다 **이메일에서 유도**했다
(`email.split("@")[0]`). 그 값이 무인증 경로 둘로 나갔다:
  · `GET /api/blog-owner` — 관리자의 로컬파트를 그대로 반환(무인증·무제한)
  · 공개 글의 댓글 목록 — 회원이 쓴 댓글의 작성자명으로 영구 저장·공개
가입이 초대제라 계정이 희소하고 admin은 **단 하나**다. 발신 도메인이 공개
제공자임이 설정 주석에 적혀 있어, 로컬파트만 알면 전체 주소가 완성된다.
그래서 표시용 이름을 신원과 분리한다. NULL이면 화면이 폴백을 쓴다(이메일로
되돌아가지 않는다 — 그게 이 컬럼의 존재 이유다).

■ 왜 comments.user_id가 필요한가
지금 댓글에는 '누가 썼는가'가 **표시 문자열로만** 남는다. 로그인 사용자는 서버가
이름을 고정하지만 비로그인은 자유 입력이라, 익명이 회원과 같은 문자열을 치면 저장된
행이 완전히 같아진다 — 2026-08-10에 무인증으로 관리자 사칭 댓글을 실제로 달아
재현했다(201, 목록에서 구분 불가). 문자열로는 사후에도 못 가른다.

**이름을 검사하는 쪽으로는 못 고친다.** 동형문자(Cyrillic е)·제로폭 공백으로
우회되고, 무엇보다 "그 이름은 계정이다"를 400으로 알려주게 되어 **무인증 계정 열거
오라클**이 된다 — 고치려던 것보다 나쁘다. 그래서 표시가 아니라 사실을 저장한다.

■ 둘 다 nullable이고 백필하지 않는다
`comments.user_id`의 NULL이 '익명'의 정의다. 기존 행을 이름으로 추측해 채우면 안
된다 — "문자열이 같다고 회원인 건 아니다"가 바로 이 버그의 내용이다. 지금 댓글은
0건이라 백필 대상 자체가 없다(이보다 싼 때는 다시 오지 않는다).
`users.display_name`의 NULL은 '안 정했다'이고, 그때 화면은 이메일이 아니라 폴백을 쓴다.

■ ondelete SET NULL
계정을 지우면 그 댓글은 익명으로 남는다. CASCADE면 관리자가 계정 하나를 지울 때
**남의 글에 달린 대화까지** 사라진다 — 삭제의 의도가 아니다(admin.delete_user는
그 사람의 '글'만 지운다). posts.owner_id가 nullable인 것과 같은 방침이다.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-08-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: str | None = "c9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("display_name", sa.String(length=50), nullable=True))

    op.add_column("comments", sa.Column("user_id", sa.Integer(), nullable=True))
    # 인덱스는 조회용이 아니다(user_id로 거르는 쿼리는 없다). users 삭제 시 SET NULL이
    # comments를 훑는 경로 때문이고, 이 저장소가 다른 FK에도 전부 인덱스를 거는 관례를 따른다.
    op.create_index(op.f("ix_comments_user_id"), "comments", ["user_id"], unique=False)
    op.create_foreign_key(
        "fk_comments_user_id_users",
        "comments",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_comments_user_id_users", "comments", type_="foreignkey")
    op.drop_index(op.f("ix_comments_user_id"), table_name="comments")
    op.drop_column("comments", "user_id")
    op.drop_column("users", "display_name")

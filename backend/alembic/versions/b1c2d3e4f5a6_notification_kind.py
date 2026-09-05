"""notifications: kind 열 추가 — 글에 안 매인 알림이 둘이 됐다

Revision ID: b1c2d3e4f5a6
Revises: a9b0c1d2e3f4
Create Date: 2026-09-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, None] = 'a9b0c1d2e3f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # models/notification.py 는 "종류를 열로 두지 않고 **어느 칸이 채워졌는가**로 가른다"고
    # 적어뒀고 그 근거는 지금도 옳다(값이 둘로 표현되면 언젠가 어긋난다). 그런데 그 규칙은
    # **글에 안 매인 알림이 한 종류일 때만** 성립했다. 2026-09-05에 '구독 승인' 알림이
    # 생기면서 둘이 됐고(신청·승인), 둘 다 post_id NULL + actor_id 라 모양이 같다.
    # 방향까지 보면 갈리긴 한다(신청은 받는 사람이 글쓴이, 승인은 받는 사람이 신청자) —
    # 하지만 그걸 알려면 매번 author_subscriptions 를 조인해야 하고, 구독을 취소한 뒤에는
    # 그 조인이 답을 못 준다. 화면 문구가 그 조인의 생사에 매이면 안 된다.
    #
    # 그래서 **post_id 가 NULL 인 알림에만** 쓰는 열로 좁혀 넣는다. 옛 주석이 경고한
    # 어긋남(kind='comment' 인데 comment_id 가 NULL)은 이 열을 글에 매인 알림에 대해
    # 아예 읽지 않으므로 생기지 않는다.
    op.add_column("notifications", sa.Column("kind", sa.String(length=20), nullable=True))
    # 지금까지 만들어진 post_id NULL 행은 전부 '구독 신청'이다(그 종류밖에 없었다).
    # 백필을 안 하면 옛 알림이 화면에서 종류 없는 줄이 된다.
    op.execute(
        "UPDATE notifications SET kind = 'subscribe_request' WHERE post_id IS NULL AND kind IS NULL"
    )


def downgrade() -> None:
    op.drop_column("notifications", "kind")

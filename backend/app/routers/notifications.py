from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, aliased

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.display import display_name_of
from app.models.comment import Comment
from app.models.notification import Notification
from app.models.post import Post
from app.models.user import User
from app.routers.posts import visible_condition

# 글쓴이(Post.owner)와 **다른 사람**을 같은 쿼리에서 조인하므로 별칭이 필요하다.
# 별칭 없이 User를 두 번 조인하면 SQLAlchemy가 같은 테이블로 보고 조건을 합쳐버린다.
Actor = aliased(User)

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: int
    # **None이면 글에 안 매인 알림**(구독 신청). 2026-08-27부터 nullable이다.
    post_id: int | None = None
    # 글이 없으면 제목도 없다. 화면이 종류에 맞는 문장을 스스로 만든다.
    title: str | None = None
    # 이 알림을 일으킨 사람. 새 글이면 글쓴이, 새 댓글이면 댓글 쓴 사람,
    # 구독 신청이면 신청한 사람이다.
    author: str
    read: bool
    created_at: datetime
    # 값이 있으면 '새 댓글' 알림. 종류는 어느 칸이 채워졌는가로 가른다
    # (models/notification.py 참고):
    #   post_id 있음 + comment_id 없음 → 새 글
    #   post_id 있음 + comment_id 있음 → 새 댓글
    #   post_id 없음                   → 구독 신청
    comment_id: int | None = None


class NotificationList(BaseModel):
    items: list[NotificationOut]
    unread: int  # 안 읽음 개수 (헤더 종 배지용)


@router.get("", response_model=NotificationList)
def list_notifications(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    # 내 알림 최신순 + 글 제목·글쓴이 (링크·표시용). 최근 20개만.
    # 조건은 한 번만 만들어 목록과 배지가 **같은 기준**을 쓰게 한다. 따로 만들면 아래처럼
    # 한쪽만 고쳐진다(2026-07-31 심층검사에서 나온 것: 목록은 걸러졌는데 배지는 아니었다).
    # visible_condition은 안에서 구독 목록을 조회하므로 재사용이 쿼리도 하나 아낀다.
    visible = visible_condition(user, db)
    rows = db.execute(
        select(
            Notification.id,
            Notification.post_id,
            Post.title,
            # ⚠️ User.id는 Notification.id와 이름이 겹친다 — 라벨을 붙여야
            # 폴백 이름이 알림 번호를 쓰는 사고를 안 낸다.
            User.id.label("author_id"),
            User.display_name,
            Notification.read,
            Notification.created_at,
            Notification.comment_id,
            # 댓글 쓴 사람 이름. 익명이면 자유 입력값이고 회원이면 서버가 고정한
            # 표시명이다(routers/comments.py). 어느 쪽이든 이미 화면에 나가는 값이다.
            Comment.author.label("comment_author"),
            # 글에 안 매인 알림(구독 신청)의 '누가'. 2026-08-27 추가.
            Actor.id.label("actor_id"),
            Actor.display_name.label("actor_display_name"),
        )
        # **셋 다 outer join이다.** post_id가 nullable이 되면서(2026-08-27) Post 조인도
        # outer여야 한다 — inner로 두면 구독 신청 알림이 목록에서 통째로 사라지고,
        # 증상은 '알림이 안 온다'라 원인이 조인이라는 걸 짐작하기 어렵다.
        # 새 글 알림에 댓글이 없는 것과 같은 이유다.
        .outerjoin(Post, Post.id == Notification.post_id)
        .outerjoin(User, User.id == Post.owner_id)
        .outerjoin(Comment, Comment.id == Notification.comment_id)
        .outerjoin(Actor, Actor.id == Notification.actor_id)
        # 지금 이 사용자에게 '보이는' 글만 — 알림 생성 후 글이 private로 바뀌거나 구독이
        # 끊기면 본문은 404여도 알림 목록엔 제목이 남아 새던 것(목록·메타와 같은 조건 재사용).
        #
        # ⚠️ **글에 안 매인 알림은 이 조건에서 면제한다.** outer join이라 Post 컬럼이
        # 전부 NULL이고, visible_condition은 그 NULL로 평가되어 결과가 NULL이 된다.
        # SQL에서 NULL은 참이 아니므로 WHERE가 그 행을 버린다 — 즉 면제하지 않으면
        # 구독 신청 알림이 만들어지자마자 안 보인다. 새는 쪽이 아니라 사라지는 쪽의
        # 실수라 조용하다.
        .where(
            Notification.user_id == user.id,
            or_(Notification.post_id.is_(None), visible),
        )
        .order_by(Notification.created_at.desc())
        .limit(20)
    ).all()
    items = [
        {
            "id": r.id,
            "post_id": r.post_id,
            "title": r.title,
            # 새 댓글이면 댓글 쓴 사람, 새 글이면 글쓴이, 구독 신청이면 신청한 사람.
            # 순서가 곧 우선순위다 — 구독 신청에는 앞의 둘이 없고, 앞의 둘에는 actor가 없다.
            "author": (
                r.comment_author
                or (
                    display_name_of(r.author_id, r.display_name)
                    if r.author_id is not None
                    else display_name_of(r.actor_id, r.actor_display_name)
                )
            ),
            "read": r.read,
            "created_at": r.created_at,
            "comment_id": r.comment_id,
        }
        for r in rows
    ]
    # 배지 개수도 목록과 같은 가시성 조건을 건다. 안 걸면 글이 private로 바뀌거나 구독이
    # 끊긴 뒤 **배지엔 3이 떠 있는데 열면 0개**가 된다(사용자는 사라지지 않는 배지를 본다).
    # 덤으로, 볼 수 없게 된 글이 있다는 사실 자체를 숫자로 흘리지 않는다.
    unread = db.scalar(
        select(func.count())
        .select_from(Notification)
        # 목록과 **같은 조인·같은 조건**이어야 한다. 한쪽만 고치면 배지엔 3이 떠 있는데
        # 열면 0개가 된다(2026-07-31 심층검사가 잡은 그 모양). 08-27에 목록을 outer로
        # 바꾸면서 여기도 같이 바꾼다.
        .outerjoin(Post, Post.id == Notification.post_id)
        .where(
            Notification.user_id == user.id,
            Notification.read.is_(False),
            or_(Notification.post_id.is_(None), visible),
        )
    )
    return {"items": items, "unread": unread or 0}


@router.post("/read", status_code=204)
def mark_all_read(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    # 내 알림 전부 읽음 처리 (종을 열어보면 배지 사라짐)
    db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read.is_(False))
        .values(read=True)
    )
    db.commit()

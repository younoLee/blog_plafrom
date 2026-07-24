from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.notification import Notification
from app.models.post import Post
from app.models.user import User
from app.routers.posts import visible_condition

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: int
    post_id: int
    title: str
    author: str
    read: bool
    created_at: datetime


class NotificationList(BaseModel):
    items: list[NotificationOut]
    unread: int  # 안 읽음 개수 (헤더 종 배지용)


@router.get("", response_model=NotificationList)
def list_notifications(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    # 내 알림 최신순 + 글 제목·글쓴이 (링크·표시용). 최근 20개만.
    rows = db.execute(
        select(
            Notification.id,
            Notification.post_id,
            Post.title,
            User.email,
            Notification.read,
            Notification.created_at,
        )
        .join(Post, Post.id == Notification.post_id)
        .join(User, User.id == Post.owner_id)
        # 지금 이 사용자에게 '보이는' 글만 — 알림 생성 후 글이 private로 바뀌거나 구독이
        # 끊기면 본문은 404여도 알림 목록엔 제목이 남아 새던 것(목록·메타와 같은 조건 재사용).
        .where(Notification.user_id == user.id, visible_condition(user, db))
        .order_by(Notification.created_at.desc())
        .limit(20)
    ).all()
    items = [
        {
            "id": r.id,
            "post_id": r.post_id,
            "title": r.title,
            "author": r.email.split("@")[0],
            "read": r.read,
            "created_at": r.created_at,
        }
        for r in rows
    ]
    unread = db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user.id, Notification.read.is_(False))
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

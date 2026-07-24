from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.author_subscription import AuthorSubscription
from app.models.user import User

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


class SubscribeIn(BaseModel):
    author_id: int


@router.get("", response_model=list[int])
def my_subscriptions(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    # 내가 구독 중인 글쓴이 id 목록
    return list(
        db.scalars(
            select(AuthorSubscription.author_id).where(
                AuthorSubscription.subscriber_id == user.id
            )
        ).all()
    )


class SubscriptionOut(BaseModel):
    id: int
    name: str


class SubscriptionDetailOut(BaseModel):
    id: int
    name: str
    approved: bool  # 글쓴이가 이 구독을 승인했는지 (false=승인 대기)
    notify: bool  # 이 글쓴이의 새 글 이메일 알림을 켰는지


class NotifyIn(BaseModel):
    notify: bool


@router.get("/detail", response_model=list[SubscriptionDetailOut])
def my_subscriptions_detail(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    # 내가 구독(신청)한 글쓴이 (id + 이름 + 승인여부 + 알림여부) — 구독 관리 목록 표시용
    rows = db.execute(
        select(User.id, User.email, AuthorSubscription.approved, AuthorSubscription.notify)
        .join(AuthorSubscription, AuthorSubscription.author_id == User.id)
        .where(AuthorSubscription.subscriber_id == user.id)
        .order_by(User.id)
    ).all()
    return [
        {"id": r.id, "name": r.email.split("@")[0], "approved": r.approved, "notify": r.notify}
        for r in rows
    ]


@router.put("/{author_id}/notify", response_model=SubscriptionDetailOut)
def set_notify(
    author_id: int,
    data: NotifyIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    sub = db.scalar(
        select(AuthorSubscription).where(
            AuthorSubscription.subscriber_id == user.id,
            AuthorSubscription.author_id == author_id,
        )
    )
    if sub is None:
        raise HTTPException(status_code=404, detail="먼저 구독해야 알림을 켤 수 있어")
    # 알림은 '승인된 다음에'만 켤 수 있다 (대기 중엔 열람 권한이 없으니 알림도 무의미)
    if not sub.approved:
        raise HTTPException(status_code=400, detail="아직 승인 대기중이라 알림을 켤 수 없어")
    sub.notify = data.notify
    db.commit()
    author = db.get(User, author_id)
    return {
        "id": author_id,
        "name": author.email.split("@")[0],
        "approved": sub.approved,
        "notify": sub.notify,
    }


@router.get("/authors", response_model=list[SubscriptionOut])
def subscribable_authors(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    # 구독할 수 있는 글쓴이(writer/admin) 목록 — 자기 자신은 제외
    rows = db.execute(
        select(User.id, User.email)
        .where(User.role.in_(("writer", "admin")), User.id != user.id)
        .order_by(User.id)
    ).all()
    return [{"id": r.id, "name": r.email.split("@")[0]} for r in rows]


@router.post("", status_code=201)
def subscribe(data: SubscribeIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    # 구독 = '신청'. 글쓴이가 승인해야 approved=true가 되어 열람/알림 권한이 생긴다.
    if data.author_id == user.id:
        raise HTTPException(status_code=400, detail="자기 자신은 구독할 수 없어")
    if db.get(User, data.author_id) is None:
        raise HTTPException(status_code=404, detail="글쓴이를 찾을 수 없음")
    # 이미 신청/구독 중이면 그 상태를 그대로 반환(멱등)
    exists = db.scalar(
        select(AuthorSubscription).where(
            AuthorSubscription.subscriber_id == user.id,
            AuthorSubscription.author_id == data.author_id,
        )
    )
    if exists is None:
        db.add(AuthorSubscription(subscriber_id=user.id, author_id=data.author_id))  # approved=false(대기)
        try:
            db.commit()
        except IntegrityError:  # 동시 중복 신청 레이스(유니크 충돌) — 500 대신 멱등으로 흡수
            db.rollback()
            exists = db.scalar(
                select(AuthorSubscription).where(
                    AuthorSubscription.subscriber_id == user.id,
                    AuthorSubscription.author_id == data.author_id,
                )
            )
            return {"approved": exists.approved if exists else False}
        return {"approved": False}
    return {"approved": exists.approved}


@router.delete("/{author_id}", status_code=204)
def unsubscribe(author_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    # 구독(또는 신청) 취소 = 관계 삭제
    sub = db.scalar(
        select(AuthorSubscription).where(
            AuthorSubscription.subscriber_id == user.id,
            AuthorSubscription.author_id == author_id,
        )
    )
    if sub is not None:
        db.delete(sub)
        db.commit()


# ── 글쓴이(author) 쪽: 나에게 온 구독 신청 관리 ──────────────────────────────
class RequestOut(BaseModel):
    id: int  # 신청한 사용자(subscriber) id
    name: str


@router.get("/requests", response_model=list[RequestOut])
def my_requests(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    # 나(글쓴이)에게 온 '승인 대기' 구독 신청 목록
    rows = db.execute(
        select(User.id, User.email)
        .join(AuthorSubscription, AuthorSubscription.subscriber_id == User.id)
        .where(
            AuthorSubscription.author_id == user.id,
            AuthorSubscription.approved.is_(False),
        )
        .order_by(AuthorSubscription.created_at)
    ).all()
    return [{"id": r.id, "name": r.email.split("@")[0]} for r in rows]


def _pending_request(db: Session, author_id: int, subscriber_id: int) -> AuthorSubscription | None:
    return db.scalar(
        select(AuthorSubscription).where(
            AuthorSubscription.author_id == author_id,
            AuthorSubscription.subscriber_id == subscriber_id,
        )
    )


@router.post("/requests/{subscriber_id}/approve", status_code=204)
def approve_request(
    subscriber_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    # 내 글에 대한 구독 신청 승인 (author = 나)
    sub = _pending_request(db, user.id, subscriber_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="구독 신청을 찾을 수 없어")
    sub.approved = True
    db.commit()


@router.delete("/requests/{subscriber_id}", status_code=204)
def reject_request(
    subscriber_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    # 거절 = 그 신청(구독 관계) 삭제. 신청자는 다시 신청할 수 있다.
    sub = _pending_request(db, user.id, subscriber_id)
    if sub is not None:
        db.delete(sub)
        db.commit()

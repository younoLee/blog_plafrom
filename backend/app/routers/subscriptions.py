from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.author_subscription import AuthorSubscription

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


@router.get("/detail", response_model=list[SubscriptionOut])
def my_subscriptions_detail(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    # 내가 구독 중인 글쓴이 (id + 이름) — '구독 중인 블로그' 목록 표시용
    rows = db.execute(
        select(User.id, User.email)
        .join(AuthorSubscription, AuthorSubscription.author_id == User.id)
        .where(AuthorSubscription.subscriber_id == user.id)
        .order_by(User.id)
    ).all()
    return [{"id": r.id, "name": r.email.split("@")[0]} for r in rows]


@router.post("", status_code=201)
def subscribe(data: SubscribeIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if data.author_id == user.id:
        raise HTTPException(status_code=400, detail="자기 자신은 구독할 수 없어")
    if db.get(User, data.author_id) is None:
        raise HTTPException(status_code=404, detail="글쓴이를 찾을 수 없음")
    # 이미 구독 중이면 그냥 OK 처리(멱등)
    exists = db.scalar(
        select(AuthorSubscription).where(
            AuthorSubscription.subscriber_id == user.id,
            AuthorSubscription.author_id == data.author_id,
        )
    )
    if exists is None:
        db.add(AuthorSubscription(subscriber_id=user.id, author_id=data.author_id))
        db.commit()
    return {"subscribed": True}


@router.delete("/{author_id}", status_code=204)
def unsubscribe(author_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sub = db.scalar(
        select(AuthorSubscription).where(
            AuthorSubscription.subscriber_id == user.id,
            AuthorSubscription.author_id == author_id,
        )
    )
    if sub is not None:
        db.delete(sub)
        db.commit()

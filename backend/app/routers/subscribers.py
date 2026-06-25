from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.subscriber import Subscriber
from app.schemas.subscriber import SubscriberCreate, SubscriberRead

router = APIRouter(prefix="/subscribers", tags=["subscribers"])


@router.post("", response_model=SubscriberRead, status_code=201)
def subscribe(data: SubscriberCreate, db: Session = Depends(get_db)):
    # 이미 구독 중인 이메일이면 409 (DB 유니크 제약이 최종 방어선이지만, 친절한 메시지용으로 먼저 확인)
    exists = db.scalar(select(Subscriber).where(Subscriber.email == data.email))
    if exists:
        raise HTTPException(status_code=409, detail="이미 구독 중인 이메일")
    sub = Subscriber(email=data.email)
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


@router.get("", response_model=list[SubscriberRead])
def list_subscribers(db: Session = Depends(get_db)):
    return db.scalars(select(Subscriber).order_by(Subscriber.created_at.desc())).all()

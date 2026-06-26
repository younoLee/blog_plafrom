from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_admin
from app.core.ratelimit import limiter
from app.models.subscriber import Subscriber
from app.models.user import User
from app.schemas.subscriber import SubscriberCreate, SubscriberRead

router = APIRouter(prefix="/subscribers", tags=["subscribers"])


@router.post("", response_model=SubscriberRead, status_code=201)
@limiter.limit("10/hour")  # 남의 이메일 무단등록·도배 방지
def subscribe(request: Request, data: SubscriberCreate, db: Session = Depends(get_db)):
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
def list_subscribers(
    db: Session = Depends(get_db), admin: User = Depends(require_admin)
):
    # 구독자 이메일 목록은 관리자만 (예전엔 무인증 노출 = PII 유출)
    return db.scalars(select(Subscriber).order_by(Subscriber.created_at.desc())).all()

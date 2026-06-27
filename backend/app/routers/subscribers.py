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


@router.post("/unsubscribe", status_code=200)
@limiter.limit("10/hour")  # 남용 방지
def unsubscribe(request: Request, data: SubscriberCreate, db: Session = Depends(get_db)):
    # 이메일로 구독 취소 (뉴스레터 표준: 본인확인 없이 이메일만으로).
    # 존재 여부는 노출하지 않음 → 등록 안 된 이메일이어도 동일하게 200
    sub = db.scalar(select(Subscriber).where(Subscriber.email == data.email))
    if sub is not None:
        db.delete(sub)
        db.commit()
    return {"message": "구독을 취소했어 (등록된 이메일이라면)"}


@router.get("", response_model=list[SubscriberRead])
def list_subscribers(
    db: Session = Depends(get_db), admin: User = Depends(require_admin)
):
    # 구독자 이메일 목록은 관리자만 (예전엔 무인증 노출 = PII 유출)
    return db.scalars(select(Subscriber).order_by(Subscriber.created_at.desc())).all()


@router.delete("/{subscriber_id}", status_code=204)
def remove_subscriber(
    subscriber_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    # 이메일 구독자 삭제는 관리자만 (PII 목록 관리)
    sub = db.get(Subscriber, subscriber_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="구독자를 찾을 수 없음")
    db.delete(sub)
    db.commit()

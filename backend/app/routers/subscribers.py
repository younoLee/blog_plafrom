from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user, require_admin
from app.core.ratelimit import limiter
from app.core.security import create_email_token, decode_email_token
from app.models.subscriber import Subscriber
from app.models.user import User
from app.schemas.subscriber import MySubscription, SubscriberCreate, SubscriberRead
from app.services.email import send_subscribe_confirm_email

router = APIRouter(prefix="/subscribers", tags=["subscribers"])


def _send_confirm(sub: Subscriber, background: BackgroundTasks) -> None:
    # 구독 확인 토큰(24h, purpose=subscribe) → 프론트 확인 페이지 링크
    token = create_email_token(sub.id, purpose="subscribe")
    link = f"{settings.frontend_base_url}/subscribe/confirm?token={token}"
    background.add_task(send_subscribe_confirm_email, sub.email, link)


@router.post("", status_code=200)
@limiter.limit("10/hour")  # 남의 이메일 무단등록·도배 방지
def subscribe(
    request: Request,
    data: SubscriberCreate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    # 더블옵트인: 등록 즉시 구독시키지 않고 '확인메일'만 보냄.
    # 본인이 링크를 눌러 confirmed=True가 된 사람에게만 알림이 감 → 남의 이메일 무단구독 차단.
    # 응답은 어느 경우든 동일 → 그 이메일의 구독 여부를 노출하지 않음(enumeration 방지).
    sub = db.scalar(select(Subscriber).where(Subscriber.email == data.email))
    if sub is None:
        # 신규: 미확인 상태로 만들고 확인메일 발송
        sub = Subscriber(email=data.email, confirmed=False)
        db.add(sub)
        try:
            db.commit()
            db.refresh(sub)
        except IntegrityError:  # 동시 첫 구독 레이스(email 유니크) — 멱등(그쪽 요청이 메일 보냄)
            db.rollback()
            return {"message": "확인 메일을 보냈어. 메일함에서 구독 확인을 눌러줘."}
        _send_confirm(sub, background)
    elif not sub.confirmed:
        # 이미 있지만 미확인: 확인메일 재발송(분실 대비)
        _send_confirm(sub, background)
    # 이미 확인된 구독자면 아무것도 안 보냄(중복 발송 방지). 응답은 위와 동일.
    return {"message": "확인 메일을 보냈어. 메일함에서 구독 확인을 눌러줘."}


@router.post("/confirm", response_model=SubscriberRead)
@limiter.limit("20/hour")  # 토큰 대입 완화(서명된 JWT라 사실상 불가하지만 방어)
def confirm_subscription(
    request: Request, token: str, db: Session = Depends(get_db)
):
    # 확인메일 링크의 토큰(purpose=subscribe)으로 구독 확정
    decoded = decode_email_token(token, purpose="subscribe")
    if decoded is None:
        raise HTTPException(status_code=400, detail="유효하지 않거나 만료된 링크야")
    sub_id, _ = decoded
    sub = db.get(Subscriber, sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="구독 정보를 찾을 수 없음")
    sub.confirmed = True
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


# --- 로그인 사용자 본인 구독 (구독 관리 페이지 전용) ---
# '내 계정 이메일'로만 다룬다. 소유권이 로그인으로 증명되므로 더블옵트인(확인메일) 없이
# 바로 confirmed 처리 → '새 글 알림'(계정 구독)을 구독 직후 바로 설정할 수 있음.
# 라우트 순서 주의: 아래 DELETE "/{subscriber_id}"(int)가 "me"를 삼키지 않도록 그 앞에 둔다.


@router.get("/me", response_model=MySubscription)
def my_subscription(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    sub = db.scalar(select(Subscriber).where(Subscriber.email == user.email))
    return MySubscription(
        email=user.email, subscribed=(sub is not None and sub.confirmed)
    )


@router.post("/me", response_model=MySubscription, status_code=200)
def subscribe_me(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    # 내 계정 이메일로 구독(멱등). 본인 인증이 로그인으로 끝났으니 즉시 confirmed.
    sub = db.scalar(select(Subscriber).where(Subscriber.email == user.email))
    if sub is None:
        sub = Subscriber(email=user.email, confirmed=True)
        db.add(sub)
    else:
        sub.confirmed = True
    try:
        db.commit()
    except IntegrityError:  # 동시 첫 구독 레이스(email 유니크) — 재조회해 confirmed 보장
        db.rollback()
        sub = db.scalar(select(Subscriber).where(Subscriber.email == user.email))
        if sub is not None and not sub.confirmed:
            sub.confirmed = True
            db.commit()
    return MySubscription(email=user.email, subscribed=True)


@router.delete("/me", status_code=204)
def unsubscribe_me(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    # 내 계정 이메일 구독 해제 (없으면 그냥 204)
    sub = db.scalar(select(Subscriber).where(Subscriber.email == user.email))
    if sub is not None:
        db.delete(sub)
        db.commit()


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

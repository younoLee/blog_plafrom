from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.ratelimit import limiter
from app.models.push_subscription import PushSubscription
from app.models.user import User
from app.schemas.push import PushKey, PushStatus, PushSubscribe

router = APIRouter(prefix="/push", tags=["push"])


@router.get("/key", response_model=PushKey)
def public_key():
    """브라우저가 구독할 때 쓰는 VAPID 공개키.

    **비밀이 아니다** — 이 값으로 구독해야 우리 서버가 보낸 알림임을 브라우저가
    검증할 수 있으니 어차피 클라이언트에 나가야 한다. 로그인도 요구하지 않는다.

    키가 설정 안 됐으면 503. 프론트는 이걸 보고 '알림 켜기'를 아예 숨긴다 —
    누를 수 없는 버튼을 보여주는 것보다 없는 게 낫다."""
    if not settings.push_enabled:
        raise HTTPException(status_code=503, detail="푸시 알림이 설정돼 있지 않아")
    return PushKey(public_key=settings.vapid_public_key)


@router.get("", response_model=PushStatus)
def my_subscriptions(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """이 계정이 몇 개 기기에서 알림을 받고 있는지.

    개수만 준다. endpoint는 사실상 기기 식별자라 돌려줄 이유가 없고, 화면에서
    필요한 건 '켜져 있나'와 '몇 대냐'뿐이다."""
    count = db.scalar(
        select(func.count())
        .select_from(PushSubscription)
        .where(PushSubscription.user_id == user.id)
    )
    return PushStatus(enabled=settings.push_enabled, devices=int(count or 0))


@router.post("", status_code=204)
@limiter.limit("30/hour")
def subscribe(
    request: Request,
    data: PushSubscribe,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """이 기기를 알림 수신 대상으로 등록한다.

    **같은 endpoint가 이미 있으면 주인만 갱신한다.** 브라우저는 재구독 시 같은
    endpoint를 돌려주는 경우가 많은데, 그때 행을 새로 만들면 같은 기기에 알림이
    두 번 간다. 그리고 공용 PC에서 A가 켜둔 뒤 B가 로그인해 켜면 endpoint는
    같으므로, 주인을 B로 옮겨야 A의 알림이 B 화면에 뜨지 않는다.

    키(p256dh·auth)도 함께 갱신한다 — 브라우저가 구독을 갱신하면서 키만 바꾸는
    경우가 있어서, endpoint만 보고 넘기면 이후 발송이 전부 복호화 실패한다."""
    if not settings.push_enabled:
        raise HTTPException(status_code=503, detail="푸시 알림이 설정돼 있지 않아")

    existing = db.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == data.endpoint)
    )
    if existing is not None:
        existing.user_id = user.id
        existing.p256dh = data.p256dh
        existing.auth = data.auth
    else:
        db.add(
            PushSubscription(
                user_id=user.id,
                endpoint=data.endpoint,
                p256dh=data.p256dh,
                auth=data.auth,
            )
        )
    db.commit()


@router.delete("", status_code=204)
def unsubscribe(
    endpoint: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """알림 끄기. endpoint를 주면 그 기기만, 안 주면 이 계정의 전 기기.

    **남의 구독은 못 지운다** — user_id 조건을 항상 함께 건다. endpoint만으로
    지우게 두면 남의 기기 endpoint를 아는 사람이 그 사람 알림을 꺼버릴 수 있다."""
    stmt = delete(PushSubscription).where(PushSubscription.user_id == user.id)
    if endpoint:
        stmt = stmt.where(PushSubscription.endpoint == endpoint)
    db.execute(stmt)
    db.commit()

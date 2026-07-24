import base64
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.ratelimit import limiter
from app.models.payment import Payment
from app.models.user import User
from app.schemas.user import UserRead

# 토스페이먼츠 일회성 결제.
# 흐름: /checkout(주문생성) → 프론트가 토스 결제창 → 성공 리다이렉트 → /confirm(서버가 토스 승인검증) → is_pro 켬.
# 시크릿키는 서버에서만 사용(프론트 노출 금지). 승인 성공을 서버가 검증한 뒤에만 구독을 켠다.
# 실제 라이브 결제는 토스 대시보드에서 발급한 라이브 키 + 사업자 심사가 필요(테스트 키는 돈 안 나감).
router = APIRouter(prefix="/payments", tags=["payments"])

PRO_ORDER_NAME = "블로그 Pro 구독 (1개월)"
TOSS_CONFIRM_URL = "https://api.tosspayments.com/v1/payments/confirm"


def _guard_live():
    """운영 안전장치: payments_require_live면 테스트 키로는 결제를 못 하게 막는다.
    운영에 테스트 키가 실수로 남아도 '공짜 Pro'가 뿌려지지 않게 하는 원천 차단."""
    if settings.payments_require_live and settings.toss_secret_key.startswith("test_"):
        raise HTTPException(
            status_code=503,
            detail="결제가 아직 라이브로 전환되지 않았어 (운영에 라이브 키 필요). 잠시 후 다시 시도해줘.",
        )


class CheckoutResponse(BaseModel):
    order_id: str
    amount: int
    order_name: str


class ConfirmRequest(BaseModel):
    payment_key: str
    order_id: str
    amount: int


@router.post("/checkout", response_model=CheckoutResponse)
@limiter.limit("20/hour")
def checkout(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _guard_live()  # 운영에 테스트 키 방치 시 결제 시작부터 차단
    # 관리자는 role상 이미 전 모델 사용 가능 → 결제 자체가 불필요(돈 안 나감)
    if user.role == "admin":
        raise HTTPException(status_code=400, detail="관리자는 결제할 필요가 없어 (이미 모든 모델 사용 가능)")
    if user.is_pro:
        raise HTTPException(status_code=400, detail="이미 Pro 구독 중이야")

    order_id = "order_" + uuid.uuid4().hex
    p = Payment(
        user_id=user.id,
        order_id=order_id,
        amount=settings.pro_price_krw,
        status="pending",
        order_name=PRO_ORDER_NAME,
    )
    db.add(p)
    db.commit()
    return CheckoutResponse(order_id=order_id, amount=settings.pro_price_krw, order_name=PRO_ORDER_NAME)


@router.post("/confirm", response_model=UserRead)
@limiter.limit("20/hour")
def confirm(
    request: Request,
    body: ConfirmRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _guard_live()  # 운영에 테스트 키 방치 시 승인(=Pro 부여) 원천 차단
    # 행 잠금(FOR UPDATE): 동시 confirm(더블클릭·재시도·2개 태스크)을 직렬화한다. 없으면 둘 다
    # status="pending"을 읽고, 하나가 paid로 만든 뒤 다른 하나가 토스 '이미 처리됨'(비200)을 받아
    # paid 행을 "failed"로 덮어썼다(유저는 Pro인데 기록은 실패 = 회계 불일치 + 멱등성 붕괴).
    # 잠그면 뒤 요청은 앞이 커밋한 paid를 읽고 아래 멱등 분기로 빠진다.
    p = (
        db.query(Payment)
        .filter(Payment.order_id == body.order_id)
        .with_for_update()
        .first()
    )
    # 남의 주문/없는 주문 차단
    if p is None or p.user_id != user.id:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없어")
    # 멱등: 이미 승인된 주문이면 그대로 성공 (새로고침·중복 호출 방어)
    if p.status == "paid":
        return user
    # 금액 위변조 방지: 서버가 만든 주문 금액과 반드시 일치해야 함
    if body.amount != p.amount:
        raise HTTPException(status_code=400, detail="결제 금액이 주문과 일치하지 않아")
    if not settings.toss_secret_key:
        raise HTTPException(status_code=503, detail="결제가 설정되지 않았어 (TOSS_SECRET_KEY 필요)")

    # 서버 → 토스 승인 API. 시크릿키는 Basic 인증(secret + ':')으로만 사용, 프론트에 절대 안 나감
    auth = base64.b64encode((settings.toss_secret_key + ":").encode()).decode()
    try:
        resp = httpx.post(
            TOSS_CONFIRM_URL,
            headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
            json={"paymentKey": body.payment_key, "orderId": body.order_id, "amount": body.amount},
            timeout=15,
        )
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="결제 승인 요청에 실패했어 (잠시 후 다시)")

    if resp.status_code != 200:
        p.status = "failed"
        db.commit()
        detail = "결제 승인이 거절됐어"
        try:
            detail = resp.json().get("message") or detail
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=detail)

    # 승인 성공 → 결제 확정 + 구독 활성화(만료 = now + pro_days)
    now = datetime.now(UTC)
    p.status = "paid"
    p.payment_key = body.payment_key
    p.paid_at = now
    user.is_pro = True
    user.pro_until = now + timedelta(days=settings.pro_days)
    db.commit()
    db.refresh(user)
    return user


@router.post("/unsubscribe", response_model=UserRead)
@limiter.limit("10/hour")
def unsubscribe(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # 구독 해지: is_pro 끔 + 만료일 제거 (환불은 별도. 데모라 상태만 토글)
    user.is_pro = False
    user.pro_until = None
    db.commit()
    db.refresh(user)
    return user

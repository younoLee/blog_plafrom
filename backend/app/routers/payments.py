import base64
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.ratelimit import limiter
from app.models.payment import Payment
from app.models.user import User
from app.schemas.base import SafeModel
from app.schemas.user import UserRead

# 토스페이먼츠 일회성 결제.
# 흐름: /checkout(주문생성) → 프론트가 토스 결제창 → 성공 리다이렉트 → /confirm(서버가 토스 승인검증) → is_pro 켬.
# 시크릿키는 서버에서만 사용(프론트 노출 금지). 승인 성공을 서버가 검증한 뒤에만 구독을 켠다.
# 실제 라이브 결제는 토스 대시보드에서 발급한 라이브 키 + 사업자 심사가 필요(테스트 키는 돈 안 나감).
# payments.status: pending(주문생성) → confirming(토스 호출 직전, 잠금을 놓기 위한 중간 상태)
#                  → paid(승인 확정) 또는 failed(확정 거절). 2026-09-02에 confirming을 넣었다.
router = APIRouter(prefix="/payments", tags=["payments"])
logger = logging.getLogger(__name__)

PRO_ORDER_NAME = "블로그 Pro 구독 (1개월)"

# 만료 며칠 전부터 연장 결제를 허용하는가. 창이 넓으면 같은 달에 두 번 낼 수 있고,
# 0 이면 구독이 끊기는 날까지 기다렸다 결제해야 한다(그 사이 상위 모델이 잠긴다).
# 연장은 `now + pro_days` 로 덮으므로 남은 기간이 잘린다 — 7일이면 잘려도 손해가 작다.
RENEW_WINDOW_DAYS = 7
TOSS_CONFIRM_URL = "https://api.tosspayments.com/v1/payments/confirm"
# 주문번호로 결제 상태를 되묻는 조회 API. 중복 승인 요청 뒤 '토스는 승인했는데 우리는
# 결과를 못 받은' 상태를 푸는 근거다(2026-09-02).
TOSS_ORDER_URL = "https://api.tosspayments.com/v1/payments/orders/"
# 같은 결제키로 두 번 승인 요청했을 때 토스가 주는 코드. 거절이 아니라 '이미 됐다'는 뜻이다.
_ALREADY_PROCESSED_CODES = frozenset({"ALREADY_PROCESSED_PAYMENT"})


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


class ConfirmRequest(SafeModel):
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
    # **만료가 임박하면 다시 결제할 수 있다** (09-04 검사 GAP-7).
    # 그전에는 is_pro 이기만 하면 무조건 막아서, 구독이 끊기는 날까지 기다렸다가 결제해야
    # 했다 — 그 사이 상위 모델이 잠기고, 하필 그날 서버가 꺼져 있으면 더 길어진다.
    # 그렇다고 아무 때나 열면 같은 달에 두 번 낼 수 있으므로 창을 좁게 둔다.
    # 연장은 confirm 이 `now + pro_days` 로 덮으므로 남은 기간이 잘린다 —
    # 그래서 '임박'이 아니면 여전히 막는다(잘려도 손해가 작은 구간에서만 연다).
    if user.is_pro:
        remaining = (user.pro_until - datetime.now(UTC)).days if user.pro_until else None
        if remaining is None or remaining > RENEW_WINDOW_DAYS:
            raise HTTPException(
                status_code=400,
                detail=(
                    "이미 Pro 구독 중이야"
                    if remaining is None
                    else f"이미 Pro 구독 중이야 (만료 {remaining}일 전부터 연장할 수 있어)"
                ),
            )

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


class _ApprovalRejected(Exception):
    """승인이 '결제 완료'로 확정되지 못했다.

    mark_failed=True는 되돌릴 수 없는 거절(토스가 거절했거나 응답이 주문과 다름)이라
    payments.status를 failed로 굳혀도 되는 경우다. False는 '모름'이다(네트워크 오류·5xx·
    입금 대기). 모름을 failed로 굳히면 2026-08-26에 겪은 회계 불일치가 그대로 재발한다.
    """

    def __init__(self, detail: str, *, status_code: int = 400, mark_failed: bool = False):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.mark_failed = mark_failed


def _toss_headers() -> dict[str, str]:
    # 시크릿키는 Basic 인증(secret + ':')으로만 사용, 프론트에 절대 안 나감
    auth = base64.b64encode((settings.toss_secret_key + ":").encode()).decode()
    return {"Authorization": f"Basic {auth}", "Content-Type": "application/json"}


def _json_or_none(resp: Any) -> dict[str, Any] | None:
    """응답 본문을 dict로 읽는다. 못 읽으면 None.

    2026-09-02: '못 읽었다'를 '괜찮다'로 읽지 않기 위해 파싱 실패를 명시적으로 None으로
    돌린다. 호출부는 None을 성공으로 취급하지 않는다."""
    try:
        data = resp.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _verify_approved(payload: dict[str, Any] | None, *, order_id: str, expected_amount: int) -> None:
    """토스 승인 응답이 '진짜 결제 완료'인지 확인한다. 셋이 전부 맞아야 통과.

    2026-09-02: 예전엔 HTTP 200 여부만 보고 Pro를 켰다. 가상계좌는 승인 API가
    200 + status="WAITING_FOR_DEPOSIT"을 돌려주므로 **입금 전에 Pro가 열렸다.**
    클라이언트 키는 공개값이라 프론트에서 결제수단을 카드로 고정한 것은 방어가 아니다
    (공격자가 자기 페이지에서 가상계좌로 요청할 수 있다). 지금은 _guard_live의 503이
    가리고 있을 뿐, 라이브 키를 넣는 날 바로 열리는 구멍이었다.

    금액·주문번호는 위변조 신호라 더 강하게 다룬다(로그 + failed 확정). 반대로 필드가
    아예 없거나 본문을 못 읽은 경우는 '거절'이 아니라 '모름'이라 failed로 굳히지 않는다
    (토스가 스키마를 바꾼 날 멀쩡한 결제를 실패로 못 박는 쪽이 더 위험하다)."""
    if payload is None:
        raise _ApprovalRejected(
            "결제 승인 결과를 확인하지 못했어 (잠시 후 다시 시도해줘)", status_code=502
        )
    status = payload.get("status")
    total = payload.get("totalAmount")
    resp_order_id = payload.get("orderId")
    if status is None or total is None or resp_order_id is None:
        logger.warning(
            "토스 승인 응답에 필요한 필드가 없다 order_id=%s keys=%s", order_id, sorted(payload)
        )
        raise _ApprovalRejected(
            "결제 승인 결과를 확인하지 못했어 (잠시 후 다시 시도해줘)", status_code=502
        )
    if resp_order_id != order_id or total != expected_amount:
        # 위변조 신호: 남의 결제를 내 주문에 붙이거나 금액을 낮춰 부르는 시도
        logger.warning(
            "토스 승인 응답이 주문과 다르다 주문=%s/%s원 응답=%r/%r원 status=%r",
            order_id,
            expected_amount,
            resp_order_id,
            total,
            status,
        )
        raise _ApprovalRejected("결제 정보가 주문과 일치하지 않아", mark_failed=True)
    if status != "DONE":
        # 가상계좌(WAITING_FOR_DEPOSIT)·진행중(IN_PROGRESS) 등. 돈이 아직 안 들어왔으니
        # Pro를 열지 않는다. failed로 굳히지도 않는다 — 입금이 끝난 뒤 같은 결제키로
        # 다시 confirm하면 DONE을 받고 그때 열려야 하기 때문이다.
        raise _ApprovalRejected(f"아직 결제가 완료되지 않았어 (상태: {status})")


def _confirm_with_toss(payment_key: str, order_id: str, amount: int) -> dict[str, Any] | None:
    """토스 승인 API 호출. 성공 응답 본문을 그대로 돌려준다(검증은 _verify_approved)."""
    headers = _toss_headers()
    try:
        resp = httpx.post(
            TOSS_CONFIRM_URL,
            headers=headers,
            json={"paymentKey": payment_key, "orderId": order_id, "amount": amount},
            timeout=15,
        )
    except httpx.HTTPError:
        raise _ApprovalRejected("결제 승인 요청에 실패했어 (잠시 후 다시)", status_code=502)

    if resp.status_code == 200:
        return _json_or_none(resp)

    payload = _json_or_none(resp)
    # **5xx 와 4xx 를 가른다.** 예전엔 한 갈래로 보내 둘 다 `failed` + 400 이었다.
    # 2026-08-26 카오스 훈련에서 토스에 503 을 주입해 드러난 것:
    #   ① 400 은 프론트의 isAsleepStatus(502/503/504)에 없어 '일시적 장애' 경로를
    #      안 탄다. 게이트웨이가 아픈데 사용자는 "내 카드가 거절됐다"를 본다 —
    #      돈 경로에서 원인을 정반대로 알려주는 셈이다.
    #   ② 더 나쁜 건 장부다. 토스는 승인 여부를 **판단한 적이 없는데**
    #      payments.status 가 failed 로 굳었다. 5xx 는 '거절'이 아니라 '모름'이다.
    if resp.status_code >= 500:
        raise _ApprovalRejected(
            "결제사가 일시적으로 응답하지 못했어. 잠시 후 다시 시도해줘", status_code=502
        )

    code = payload.get("code") if payload else None
    if code in _ALREADY_PROCESSED_CODES:
        # 2026-09-02: 우리 쪽 타임아웃/재시도로 같은 결제키를 두 번 승인 요청한 경우다.
        # 토스는 이미 승인된 건이라 400을 준다. 여기서 failed로 굳히면 '돈은 냈는데
        # Pro는 안 열린' 상태가 영구화된다. 그래서 주문번호로 실제 결제 상태를 되묻고,
        # 그 응답을 승인 응답과 똑같이 검증한다(중복 청구는 없다. 토스의 승인은
        # paymentKey 기준이라 두 번째 호출은 돈을 다시 받지 않는다).
        return _fetch_payment_by_order(order_id)

    detail = "결제 승인이 거절됐어"
    if payload:
        detail = payload.get("message") or detail
    raise _ApprovalRejected(detail, mark_failed=True)


def _fetch_payment_by_order(order_id: str) -> dict[str, Any] | None:
    """주문번호로 결제 상태를 되묻는다(중복 승인 뒤 실제 결과를 확인하는 유일한 근거)."""
    try:
        resp = httpx.get(TOSS_ORDER_URL + order_id, headers=_toss_headers(), timeout=10)
    except httpx.HTTPError:
        raise _ApprovalRejected("결제 상태를 확인하지 못했어 (잠시 후 다시)", status_code=502)
    if resp.status_code != 200:
        # 조회조차 실패면 '모름'이다. confirming으로 두고 재시도에 맡긴다.
        raise _ApprovalRejected("결제 상태를 확인하지 못했어 (잠시 후 다시)", status_code=502)
    return _json_or_none(resp)


def _mark_failed(db: Session, order_id: str) -> None:
    """확정된 거절만 장부에 굳힌다. 이미 paid인 행은 절대 덮지 않는다(회계 불일치 방지)."""
    p = (
        db.query(Payment)
        .filter(Payment.order_id == order_id)
        .with_for_update()
        .first()
    )
    if p is not None and p.status == "confirming":
        p.status = "failed"
    db.commit()


@router.post("/confirm", response_model=UserRead)
@limiter.limit("20/hour")
def confirm(
    request: Request,
    body: ConfirmRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _guard_live()  # 운영에 테스트 키 방치 시 승인(=Pro 부여) 원천 차단
    if not settings.toss_secret_key:
        raise HTTPException(status_code=503, detail="결제가 설정되지 않았어 (TOSS_SECRET_KEY 필요)")

    # ── 1단계: 짧은 트랜잭션. 잠그고 검증하고 confirming으로 커밋한 뒤 곧바로 놓는다.
    # 행 잠금(FOR UPDATE): 동시 confirm(더블클릭·재시도·2개 태스크)을 직렬화한다. 없으면 둘 다
    # status="pending"을 읽고, 하나가 paid로 만든 뒤 다른 하나가 토스 '이미 처리됨'(비200)을 받아
    # paid 행을 "failed"로 덮어썼다(유저는 Pro인데 기록은 실패 = 회계 불일치 + 멱등성 붕괴).
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
    # 금액 위변조 방지: 서버가 만든 주문 금액과 반드시 일치해야 함.
    # (토스 응답의 totalAmount 검증은 _verify_approved 한 자리에 모여 있다. 여기 것은
    #  토스까지 가기 전에 끊는 입력 검증이고, 저쪽 것은 '실제로 얼마가 승인됐나'다.)
    if body.amount != p.amount:
        raise HTTPException(status_code=400, detail="결제 금액이 주문과 일치하지 않아")
    if p.status == "confirming" and p.payment_key != body.payment_key:
        # 같은 주문에 다른 결제키가 붙는 건 정상 흐름에 없다(주문 하나 = 결제 하나).
        logger.warning(
            "confirming 주문에 다른 결제키 order_id=%s user=%s", body.order_id, user.id
        )
        raise HTTPException(status_code=409, detail="이 주문은 다른 결제로 승인 처리 중이야")

    # ⚠️ 커밋 뒤에는 ORM 객체를 만지지 않는다(expire_on_commit=True라 접근 즉시 refresh
    #    SELECT가 나가 방금 반납한 커넥션을 외부 호출 내내 다시 물고 있게 된다.
    #    routers/ai.py의 같은 함정과 그 주석 참고). 필요한 값은 여기서 떠 둔다.
    uid = user.id
    expected_amount = p.amount
    # 2026-09-02: confirming으로 '먼저 커밋'해 행 잠금과 커넥션을 놓는다. 예전엔 FOR UPDATE로
    # 잠근 채 토스를 최대 15초 기다려서, 토스가 느린 동안 그 사용자의 다른 요청과 풀 전체가
    # 묶였다(t2.micro라 풀이 크지 않다).
    #
    # [중간 상태가 남는 경우] 프로세스가 죽거나 토스가 타임아웃이면 행이 confirming으로 남는다.
    # 이때 잔여(죽은 것)와 in-flight(다른 요청이 지금 처리 중)를 구분할 타임스탬프 컬럼이 없다
    # (새 컬럼/마이그레이션은 이번 작업 범위 밖이다). 그래서 **같은 결제키면 재시도를 허용**한다.
    #   · 중복 청구 없음: 토스 승인은 paymentKey 기준이라 두 번째 호출은 돈을 다시 받지 않고
    #     ALREADY_PROCESSED_PAYMENT를 준다 → _confirm_with_toss가 주문 조회로 실제 상태를
    #     확인해 정상적으로 Pro를 연다.
    #   · '돈은 냈는데 Pro가 안 열림' 없음: confirming은 막다른 상태가 아니라 재시도 가능한
    #     상태다. 최종 확정(paid)은 아래에서 행을 다시 잠근 채 한 번만 일어난다.
    #   · 다른 결제키로 오는 요청만 위에서 409로 끊는다.
    p.status = "confirming"
    p.payment_key = body.payment_key
    db.commit()

    # ── 2단계: 외부 호출. 이 15초 동안 우리는 DB 커넥션도 행 잠금도 쥐고 있지 않다.
    try:
        payload = _confirm_with_toss(body.payment_key, body.order_id, body.amount)
        _verify_approved(payload, order_id=body.order_id, expected_amount=expected_amount)
    except _ApprovalRejected as e:
        if e.mark_failed:
            _mark_failed(db, body.order_id)
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    # ── 3단계: 다시 짧은 트랜잭션. 승인 성공 → 결제 확정 + 구독 활성화(만료 = now + pro_days)
    now = datetime.now(UTC)
    p = (
        db.query(Payment)
        .filter(Payment.order_id == body.order_id)
        .with_for_update()
        .first()
    )
    u = db.get(User, uid)
    if p is None or u is None:
        # 승인 도중 주문/계정이 사라진 경우(계정 삭제 등). 돈은 나갔으니 조용히 삼키지 않는다.
        logger.warning("승인은 됐는데 주문/사용자가 없다 order_id=%s user=%s", body.order_id, uid)
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없어")
    if p.status != "paid":
        # 동시 confirm 중 하나가 이미 확정했다면 여기 안 들어온다 = 기간을 두 번 연장하지 않는다.
        p.status = "paid"
        p.paid_at = now
        # 영수증 주소를 저장한다(09-04 검사 GAP-7). 승인 응답에 실려 오는데 버리고 있었고,
        # 그래서 '얼마를 언제 냈나'의 근거가 카드사 명세서뿐이었다. 모양이 다를 수 있으므로
        # 없으면 그냥 NULL 로 둔다 — 여기서 KeyError 로 죽으면 **돈은 나갔는데 확정이 안 된다**.
        receipt = payload.get("receipt") if payload else None
        if isinstance(receipt, dict):
            url = receipt.get("url")
            if isinstance(url, str):
                p.receipt_url = url[:500]
        u.is_pro = True
        u.pro_until = now + timedelta(days=settings.pro_days)
    db.commit()
    db.refresh(u)
    return u


@router.post("/unsubscribe", response_model=UserRead)
@limiter.limit("10/hour")
def unsubscribe(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """구독 해지 — **남은 기간이 즉시 사라진다.**

    환불은 없다(데모라 상태만 토글한다). 그래서 이 동작은 '다음 결제를 안 한다'가 아니라
    '지금 산 것을 지금 버린다'에 가깝다 — 화면이 그 사실을 확인창에 적어야 하고,
    2026-09-05에 그렇게 고쳤다(09-04 검사 GAP-7).
    """
    user.is_pro = False
    user.pro_until = None
    db.commit()
    db.refresh(user)
    return user


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    order_id: str
    order_name: str
    amount: int
    status: str
    receipt_url: str | None = None
    created_at: datetime
    paid_at: datetime | None = None


@router.get("/me", response_model=list[PaymentOut])
def my_payments(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """내 결제 내역 (09-04 검사 GAP-7).

    **왜 필요한가** — 그전까지 '얼마를 언제 냈나'를 확인할 방법이 카드사 명세서뿐이었다.
    결제는 이 사이트에서 돈이 오가는 유일한 자리이고, 그 기록을 사용자가 못 보면
    문의가 와도 서로 볼 수 있는 근거가 없다.

    **실패·대기 주문도 보여준다.** 성공만 보여주면 '결제가 안 됐는데 돈이 빠져나간 것
    같다'는 상황에서 화면이 아무 말도 안 하게 된다. status 를 그대로 싣고 화면이 문장을
    만든다(confirming = '확인 중'이지 실패가 아니다 — models/payment.py 참고).
    """
    rows = db.scalars(
        select(Payment)
        .where(Payment.user_id == user.id)
        .order_by(Payment.created_at.desc(), Payment.id.desc())
        .limit(50)
    ).all()
    return rows

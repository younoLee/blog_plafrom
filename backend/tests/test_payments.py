"""토스 결제: 주문생성/승인검증. 돈을 켜는 로직이라 거부·위변조·멱등·라이브가드에 집중.
외부 토스 API 호출(app.routers.payments.httpx.post)은 목킹한다."""
import httpx
import pytest

from app.core.config import settings
from app.models.payment import Payment


class _FakeResp:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


@pytest.fixture
def toss(monkeypatch):
    """토스 승인 API를 가짜로 교체. .configure(...)로 응답 지정, .calls로 호출 횟수 확인."""
    state = {"status_code": 200, "body": {"status": "DONE"}, "raise": None}
    calls = []

    def fake_post(url, **kwargs):
        calls.append(kwargs)
        if state["raise"] is not None:
            raise state["raise"]
        return _FakeResp(state["status_code"], state["body"])

    monkeypatch.setattr("app.routers.payments.httpx.post", fake_post)

    class Handle:
        calls = None

        def configure(self, *, status_code=200, body=None, raise_exc=None):
            state["status_code"] = status_code
            state["body"] = body if body is not None else {"status": "DONE"}
            state["raise"] = raise_exc

    h = Handle()
    h.calls = calls
    return h


def _checkout(client, headers):
    r = client.post("/api/payments/checkout", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# ── checkout ───────────────────────────────────────────────────────────────
def test_checkout_requires_auth(client):
    assert client.post("/api/payments/checkout").status_code == 401


def test_checkout_admin_rejected(client, make_user, auth_headers):
    admin = make_user(role="admin")
    r = client.post("/api/payments/checkout", headers=auth_headers(admin))
    assert r.status_code == 400  # 관리자는 이미 전 모델 사용 가능


def test_checkout_already_pro_rejected(client, make_user, auth_headers):
    pro = make_user(role="writer", is_pro=True)
    r = client.post("/api/payments/checkout", headers=auth_headers(pro))
    assert r.status_code == 400


def test_checkout_creates_pending_order(client, make_user, auth_headers):
    user = make_user(role="writer")
    body = _checkout(client, auth_headers(user))
    assert body["amount"] == settings.pro_price_krw
    assert body["order_id"].startswith("order_")


# ── confirm: 거부 경로 ───────────────────────────────────────────────────────
def test_confirm_unknown_order_404(client, make_user, auth_headers, toss):
    user = make_user(role="writer")
    r = client.post(
        "/api/payments/confirm",
        headers=auth_headers(user),
        json={"payment_key": "pk", "order_id": "order_nope", "amount": 9900},
    )
    assert r.status_code == 404
    assert toss.calls == []  # 토스까지 안 감


def test_confirm_other_users_order_404(client, make_user, auth_headers, toss):
    owner = make_user(role="writer")
    other = make_user(role="writer")
    order = _checkout(client, auth_headers(owner))
    r = client.post(
        "/api/payments/confirm",
        headers=auth_headers(other),
        json={"payment_key": "pk", "order_id": order["order_id"], "amount": 9900},
    )
    assert r.status_code == 404


def test_confirm_amount_mismatch_400(client, make_user, auth_headers, toss):
    user = make_user(role="writer")
    order = _checkout(client, auth_headers(user))
    r = client.post(
        "/api/payments/confirm",
        headers=auth_headers(user),
        # 서버가 만든 금액(9900)과 다른 값 → 위변조로 간주
        json={"payment_key": "pk", "order_id": order["order_id"], "amount": 100},
    )
    assert r.status_code == 400
    assert toss.calls == []  # 금액 검증에서 이미 끊김


# ── confirm: 토스 응답별 ─────────────────────────────────────────────────────
def test_confirm_success_activates_pro(client, make_user, auth_headers, toss):
    user = make_user(role="writer")
    order = _checkout(client, auth_headers(user))
    toss.configure(status_code=200, body={"status": "DONE"})

    r = client.post(
        "/api/payments/confirm",
        headers=auth_headers(user),
        json={"payment_key": "pk_live", "order_id": order["order_id"], "amount": 9900},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["is_pro"] is True
    assert body["pro_until"] is not None
    assert len(toss.calls) == 1  # 토스 승인 1회 호출


def test_confirm_toss_rejection_marks_failed(client, make_user, auth_headers, toss):
    user = make_user(role="writer")
    order = _checkout(client, auth_headers(user))
    toss.configure(status_code=400, body={"message": "카드 한도 초과"})

    r = client.post(
        "/api/payments/confirm",
        headers=auth_headers(user),
        json={"payment_key": "pk", "order_id": order["order_id"], "amount": 9900},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "카드 한도 초과"  # 토스 메시지 전달


def test_confirm_network_error_502(client, make_user, auth_headers, toss):
    user = make_user(role="writer")
    order = _checkout(client, auth_headers(user))
    toss.configure(raise_exc=httpx.ConnectError("boom"))

    r = client.post(
        "/api/payments/confirm",
        headers=auth_headers(user),
        json={"payment_key": "pk", "order_id": order["order_id"], "amount": 9900},
    )
    assert r.status_code == 502


def test_confirm_idempotent_when_already_paid(client, make_user, auth_headers, toss, db):
    user = make_user(role="writer")
    # 이미 paid인 주문을 직접 시드 → 재승인 호출은 토스를 다시 부르면 안 됨(멱등)
    db.add(
        Payment(
            user_id=user.id,
            order_id="order_paid",
            amount=9900,
            status="paid",
            order_name="x",
        )
    )
    db.commit()
    r = client.post(
        "/api/payments/confirm",
        headers=auth_headers(user),
        json={"payment_key": "pk", "order_id": "order_paid", "amount": 9900},
    )
    assert r.status_code == 200
    assert toss.calls == []  # 멱등: 토스 재호출 없음


# ── 라이브 가드: 테스트 키로는 결제 못 함 (운영 '공짜 Pro' 사고 차단) ─────────────
def test_guard_blocks_checkout_when_require_live_and_test_key(
    client, make_user, auth_headers, monkeypatch
):
    monkeypatch.setattr(settings, "payments_require_live", True)
    # 기본 toss_secret_key는 test_로 시작 → 가드 발동
    assert settings.toss_secret_key.startswith("test_")
    user = make_user(role="writer")
    r = client.post("/api/payments/checkout", headers=auth_headers(user))
    assert r.status_code == 503


def test_guard_blocks_confirm_when_require_live_and_test_key(
    client, make_user, auth_headers, monkeypatch, toss
):
    monkeypatch.setattr(settings, "payments_require_live", True)
    user = make_user(role="writer")
    r = client.post(
        "/api/payments/confirm",
        headers=auth_headers(user),
        json={"payment_key": "pk", "order_id": "order_x", "amount": 9900},
    )
    assert r.status_code == 503
    assert toss.calls == []


# ── 해지 ─────────────────────────────────────────────────────────────────────
def test_unsubscribe_turns_off_pro(client, make_user, auth_headers):
    pro = make_user(role="writer", is_pro=True)
    r = client.post("/api/payments/unsubscribe", headers=auth_headers(pro))
    assert r.status_code == 200
    assert r.json()["is_pro"] is False

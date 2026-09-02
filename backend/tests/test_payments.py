"""토스 결제: 주문생성/승인검증. 돈을 켜는 로직이라 거부·위변조·멱등·라이브가드에 집중.
외부 토스 API 호출(app.routers.payments.httpx의 post/get)은 목킹한다."""
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.core.config import settings
from app.models.payment import Payment
from app.models.user import User


class _FakeResp:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


def _done_body(req_json):
    """토스 승인 성공 응답의 최소 형태.

    2026-09-02: 서버가 실제로 읽는 세 필드(status·orderId·totalAmount)를 요청과 같게
    돌려준다. 예전 기본 응답은 {"status": "DONE"} 하나뿐이었는데, 그때는 서버가 응답 본문을
    아예 안 읽었기 때문에 통과했다. 즉 이 픽스처의 "DONE"은 아무것도 검증하지 않는
    장식이었다(그래서 가상계좌 200 + WAITING_FOR_DEPOSIT 구멍을 아무 테스트도 못 봤다)."""
    return {
        "status": "DONE",
        "orderId": req_json["orderId"],
        "totalAmount": req_json["amount"],
    }


@pytest.fixture
def toss(monkeypatch):
    """토스 API를 가짜로 교체.

    .configure(...)로 승인(POST) 응답을, .configure_lookup(...)으로 주문조회(GET) 응답을
    지정한다. .calls는 승인 호출, .lookups는 조회 호출 기록이다.
    body를 안 주면 요청과 일치하는 정상 승인(_done_body)을 돌려준다."""
    state = {"status_code": 200, "body": None, "raise": None}
    lookup = {"status_code": 200, "body": None, "raise": None}
    calls = []
    lookups = []
    hooks = []

    def fake_post(url, **kwargs):
        calls.append(kwargs)
        for hook in hooks:
            hook()
        if state["raise"] is not None:
            raise state["raise"]
        body = state["body"]
        if body is None:
            body = _done_body(kwargs["json"])
        return _FakeResp(state["status_code"], body)

    def fake_get(url, **kwargs):
        lookups.append(url)
        if lookup["raise"] is not None:
            raise lookup["raise"]
        return _FakeResp(lookup["status_code"], lookup["body"] or {})

    monkeypatch.setattr("app.routers.payments.httpx.post", fake_post)
    monkeypatch.setattr("app.routers.payments.httpx.get", fake_get)

    class Handle:
        calls = None
        lookups = None

        def configure(self, *, status_code=200, body=None, raise_exc=None):
            state["status_code"] = status_code
            state["body"] = body
            state["raise"] = raise_exc

        def configure_lookup(self, *, status_code=200, body=None, raise_exc=None):
            lookup["status_code"] = status_code
            lookup["body"] = body
            lookup["raise"] = raise_exc

        def on_call(self, fn):
            """승인 호출이 일어나는 '그 순간'에 실행할 검사(외부 호출 전 커밋 확인용)."""
            hooks.append(fn)

    h = Handle()
    h.calls = calls
    h.lookups = lookups
    return h


def _payment(db, order_id):
    return db.query(Payment).filter(Payment.order_id == order_id).one()


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
def test_confirm_success_activates_pro(client, make_user, auth_headers, toss, db):
    user = make_user(role="writer")
    order = _checkout(client, auth_headers(user))
    # (a) 승인 응답이 status=DONE + 금액·주문번호 일치일 때만 Pro가 열린다
    toss.configure(
        status_code=200,
        body={"status": "DONE", "orderId": order["order_id"], "totalAmount": 9900},
    )

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
    p = _payment(db, order["order_id"])
    assert p.status == "paid"
    assert p.payment_key == "pk_live"


# ── confirm: 승인 응답 본문 검증 (2026-09-02) ────────────────────────────────
# 여기까지 없던 자리다. 예전 코드는 HTTP 200 하나만 보고 Pro를 켰고, 그래서 아래 네 개는
# 전부 초록이 났을 것이다(=아무것도 안 막고 있었다).
def test_confirm_waiting_for_deposit_does_not_activate_pro(client, make_user, auth_headers, toss, db):
    """(b) 가상계좌: 승인 API는 200 + WAITING_FOR_DEPOSIT을 준다. 입금 전이니 Pro는 안 열린다.

    이게 이번 수정의 핵심이다. 프론트에서 결제수단을 카드로 고정해 둔 건 방어가 아니다
    (클라이언트 키는 공개값이라 공격자가 자기 페이지에서 가상계좌로 요청할 수 있다)."""
    user = make_user(role="writer")
    order = _checkout(client, auth_headers(user))
    toss.configure(
        status_code=200,
        body={
            "status": "WAITING_FOR_DEPOSIT",
            "orderId": order["order_id"],
            "totalAmount": 9900,
        },
    )

    r = client.post(
        "/api/payments/confirm",
        headers=auth_headers(user),
        json={"payment_key": "pk", "order_id": order["order_id"], "amount": 9900},
    )
    assert r.status_code == 400
    assert db.get(User, user.id).is_pro is False, "입금 전인데 Pro가 열렸다"
    # 거절이 아니라 '아직'이다 → failed로 굳히지 않는다(입금 뒤 재승인이 살아 있어야 한다)
    assert _payment(db, order["order_id"]).status == "confirming"


def test_confirm_amount_mismatch_in_toss_response_rejected(client, make_user, auth_headers, toss, db):
    """(c) 승인된 실제 금액이 주문 금액과 다르면 위변조로 보고 거절 + failed로 굳힌다."""
    user = make_user(role="writer")
    order = _checkout(client, auth_headers(user))
    toss.configure(
        status_code=200,
        body={"status": "DONE", "orderId": order["order_id"], "totalAmount": 100},
    )

    r = client.post(
        "/api/payments/confirm",
        headers=auth_headers(user),
        json={"payment_key": "pk", "order_id": order["order_id"], "amount": 9900},
    )
    assert r.status_code == 400
    assert db.get(User, user.id).is_pro is False, "100원 결제로 Pro가 열렸다"
    assert _payment(db, order["order_id"]).status == "failed"


def test_confirm_order_id_mismatch_rejected(client, make_user, auth_headers, toss, db):
    """(d) 남의 결제 응답을 내 주문에 붙이는 시도 → 거절 + failed."""
    user = make_user(role="writer")
    order = _checkout(client, auth_headers(user))
    toss.configure(
        status_code=200,
        body={"status": "DONE", "orderId": "order_somebody_else", "totalAmount": 9900},
    )

    r = client.post(
        "/api/payments/confirm",
        headers=auth_headers(user),
        json={"payment_key": "pk", "order_id": order["order_id"], "amount": 9900},
    )
    assert r.status_code == 400
    assert db.get(User, user.id).is_pro is False
    assert _payment(db, order["order_id"]).status == "failed"


def test_confirm_unreadable_response_is_not_success(client, make_user, auth_headers, toss, db):
    """본문이 비었거나 필드가 없으면 '못 읽었다'다. 그걸 '괜찮다'로 읽지 않는다.

    거절도 아니므로 failed로 굳히지도 않는다(토스가 스키마를 바꾼 날 멀쩡한 결제를
    실패로 못 박는 쪽이 더 위험하다) → confirming으로 두고 재시도에 맡긴다."""
    user = make_user(role="writer")
    order = _checkout(client, auth_headers(user))
    toss.configure(status_code=200, body={})

    r = client.post(
        "/api/payments/confirm",
        headers=auth_headers(user),
        json={"payment_key": "pk", "order_id": order["order_id"], "amount": 9900},
    )
    assert r.status_code == 502
    assert db.get(User, user.id).is_pro is False
    assert _payment(db, order["order_id"]).status == "confirming"


# ── confirm: 잠금을 놓고 외부 호출 (2026-09-02) ──────────────────────────────
def test_confirm_commits_intermediate_state_before_calling_toss(
    client, make_user, auth_headers, toss, db
):
    """토스를 부르는 순간 결제 행은 이미 confirming으로 커밋돼 있어야 한다.

    행 잠금과 커넥션을 쥔 채 외부 API를 15초 기다리던 걸 고친 자리다.
    **이 테스트가 못 보는 것**: 잠금이 실제로 풀렸는지는 다른 커넥션에서 같은 행을
    잠가 봐야 알 수 있는데, 여기 테스트는 커넥션 하나를 통째로 롤백하는 구조라
    두 번째 커넥션을 쓸 수 없다. 그래서 '커밋이 외부 호출 앞에 있다'까지만 본다."""
    user = make_user(role="writer")
    order = _checkout(client, auth_headers(user))
    seen = {}

    def peek():
        seen["status"] = _payment(db, order["order_id"]).status

    toss.on_call(peek)
    r = client.post(
        "/api/payments/confirm",
        headers=auth_headers(user),
        json={"payment_key": "pk", "order_id": order["order_id"], "amount": 9900},
    )
    assert r.status_code == 200
    assert seen["status"] == "confirming", "토스 호출 전에 중간 상태가 커밋되지 않았다"


def test_confirm_already_processed_recovers_via_order_lookup(
    client, make_user, auth_headers, toss, db
):
    """중간 상태(confirming)가 남은 뒤의 재시도: 토스는 '이미 처리됨'을 준다.

    여기서 failed로 굳히면 '돈은 냈는데 Pro는 안 열린' 상태가 영구화된다. 그래서
    주문번호로 실제 결제 상태를 되묻고, 그 응답을 승인 응답과 똑같이 검증해 확정한다."""
    user = make_user(role="writer")
    order = _checkout(client, auth_headers(user))
    toss.configure(
        status_code=400,
        body={"code": "ALREADY_PROCESSED_PAYMENT", "message": "이미 처리된 결제입니다"},
    )
    toss.configure_lookup(
        status_code=200,
        body={"status": "DONE", "orderId": order["order_id"], "totalAmount": 9900},
    )

    r = client.post(
        "/api/payments/confirm",
        headers=auth_headers(user),
        json={"payment_key": "pk", "order_id": order["order_id"], "amount": 9900},
    )
    assert r.status_code == 200
    assert r.json()["is_pro"] is True
    assert len(toss.lookups) == 1
    assert _payment(db, order["order_id"]).status == "paid"


def test_confirm_already_processed_but_lookup_says_waiting(
    client, make_user, auth_headers, toss, db
):
    """되묻기의 답이 DONE이 아니면 그대로 안 연다(조회 결과도 똑같이 검증한다)."""
    user = make_user(role="writer")
    order = _checkout(client, auth_headers(user))
    toss.configure(status_code=400, body={"code": "ALREADY_PROCESSED_PAYMENT"})
    toss.configure_lookup(
        status_code=200,
        body={
            "status": "WAITING_FOR_DEPOSIT",
            "orderId": order["order_id"],
            "totalAmount": 9900,
        },
    )

    r = client.post(
        "/api/payments/confirm",
        headers=auth_headers(user),
        json={"payment_key": "pk", "order_id": order["order_id"], "amount": 9900},
    )
    assert r.status_code == 400
    assert db.get(User, user.id).is_pro is False


def test_confirm_toss_rejection_marks_failed(client, make_user, auth_headers, toss, db):
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
    # 이름이 marks_failed인데 여기까지가 전부였다 — DB를 한 번도 안 읽어서
    # payments.py의 `p.status = "failed"`를 지워도 초록이었다(2026-08-11 공백검사).
    # "유저는 Pro인데 기록은 실패"라는 회계 불일치가 정확히 이 자리에서 샌다.
    from app.models.payment import Payment

    p = db.query(Payment).filter(Payment.order_id == order["order_id"]).one()
    assert p.status == "failed"
    assert db.get(User, user.id).is_pro is False, "결제가 거절됐는데 Pro가 켜졌다"


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


# ── 구독 만료(lazy expiry) ───────────────────────────────────────────────────
# 2026-09-02: 결제가 켠 Pro가 **기간이 끝나면 실제로 꺼지는가**를 아무도 증명하지 않고
# 있었다. core/deps.py의 _expire_pro_if_due 본문을 통째로 비워도 백엔드 테스트가 전부
# 초록이었다(461개). 결제 흐름의 반대쪽 끝이라 여기에 둔다.
# 판정 기준은 상태 컬럼이 아니라 users.pro_until 시각이다(배치 없이, 요청이 올 때마다 확인).
# 만료일을 과거로 직접 넣는 방식은 test_admin.py가 같은 자리에서 쓰는 방식과 같다.
def test_pro_expires_and_relocks_premium_models(client, make_user, auth_headers, db):
    """기간이 지난 구독은 다음 요청에서 꺼지고, 유료 전용 모델이 다시 잠긴다."""
    user = make_user(role="writer", is_pro=True)
    db.query(User).filter(User.id == user.id).update(
        {"pro_until": datetime.now(UTC) - timedelta(minutes=1)}
    )
    db.commit()

    me = client.get("/api/auth/me", headers=auth_headers(user))
    assert me.json()["is_pro"] is False, "만료된 구독이 그대로 켜져 있다"
    # DB에도 반영돼야 한다(한 번 끄고 커밋 = 다음 요청부터 판정 없이도 꺼진 상태)
    assert db.get(User, user.id).is_pro is False

    ids = [m["id"] for m in client.get("/api/ai/models", headers=auth_headers(user)).json()["models"]]
    assert "claude-opus-4-8" not in ids, "만료됐는데 유료 전용 모델이 목록에 남았다"
    # 목록만이 아니라 실제 사용도 막혀야 한다(목록은 UI, 이쪽이 집행이다)
    r = client.post(
        "/api/ai/draft",
        headers=auth_headers(user),
        json={"memo": "만료 확인용 메모", "model": "claude-opus-4-8"},
    )
    assert r.status_code == 403, "만료된 사용자가 유료 전용 모델을 그대로 썼다"


def test_pro_within_period_keeps_premium_models(client, make_user, auth_headers, db):
    """유효기간이 남았으면 건드리지 않는다(만료 판정이 과하게 꺼버리는 회귀 방지)."""
    user = make_user(role="writer", is_pro=True)
    db.query(User).filter(User.id == user.id).update(
        {"pro_until": datetime.now(UTC) + timedelta(days=3)}
    )
    db.commit()

    me = client.get("/api/auth/me", headers=auth_headers(user))
    assert me.json()["is_pro"] is True, "기간이 남았는데 구독이 꺼졌다"
    ids = [m["id"] for m in client.get("/api/ai/models", headers=auth_headers(user)).json()["models"]]
    assert "claude-opus-4-8" in ids
    assert db.get(User, user.id).is_pro is True

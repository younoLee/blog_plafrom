"""이메일 뉴스레터 구독 — 더블옵트인(확인메일) + 관리자 PII 목록 보호.
확인메일 발송은 목킹(백그라운드 태스크가 실제 SMTP를 치지 않게)."""
import pytest
from sqlalchemy import select

from app.core.security import create_email_token
from app.models.subscriber import Subscriber


@pytest.fixture(autouse=True)
def _no_email(monkeypatch):
    # 확인메일 발송을 no-op으로 (테스트에 메일서버 불필요)
    monkeypatch.setattr(
        "app.routers.subscribers.send_subscribe_confirm_email", lambda *a, **k: None
    )


# ── 더블옵트인 ───────────────────────────────────────────────────────────────
def test_subscribe_creates_unconfirmed(client, db):
    r = client.post("/api/subscribers", json={"email": "new@test.com"})
    assert r.status_code == 200
    sub = db.scalar(
        select(Subscriber).where(Subscriber.email == "new@test.com")
    )
    assert sub is not None
    assert sub.confirmed is False  # 확인 전까진 미확인


def test_confirm_sets_confirmed(client, db):
    sub = Subscriber(email="s@test.com", confirmed=False)
    db.add(sub)
    db.commit()
    db.refresh(sub)
    token = create_email_token(sub.id, purpose="subscribe")

    r = client.post(f"/api/subscribers/confirm?token={token}")
    assert r.status_code == 200
    assert r.json()["confirmed"] is True


def test_confirm_invalid_token_400(client):
    assert client.post("/api/subscribers/confirm?token=bad").status_code == 400


def test_unsubscribe_is_enumeration_safe(client, db):
    # 등록된 것: 삭제됨. 안 된 것: 그래도 동일 200 (존재 여부 노출 안 함)
    db.add(Subscriber(email="has@test.com", confirmed=True))
    db.commit()
    assert client.post("/api/subscribers/unsubscribe", json={"email": "has@test.com"}).status_code == 200
    assert client.post("/api/subscribers/unsubscribe", json={"email": "nope@test.com"}).status_code == 200
    assert db.scalar(
        select(Subscriber).where(Subscriber.email == "has@test.com")
    ) is None


# ── 로그인 사용자 본인 구독(즉시 confirmed) ──────────────────────────────────
def test_me_subscription_lifecycle(client, make_user, auth_headers):
    user = make_user(role="writer")
    h = auth_headers(user)

    # 처음엔 미구독
    assert client.get("/api/subscribers/me", headers=h).json()["subscribed"] is False
    # 구독(로그인 인증이라 즉시 confirmed)
    assert client.post("/api/subscribers/me", headers=h).json()["subscribed"] is True
    assert client.get("/api/subscribers/me", headers=h).json()["subscribed"] is True
    # 해제
    assert client.delete("/api/subscribers/me", headers=h).status_code == 204
    assert client.get("/api/subscribers/me", headers=h).json()["subscribed"] is False


def test_me_requires_auth(client):
    assert client.get("/api/subscribers/me").status_code == 401


# ── 관리자만 PII 목록 ────────────────────────────────────────────────────────
def test_list_subscribers_admin_only(client, make_user, auth_headers, db):
    db.add(Subscriber(email="a@test.com", confirmed=True))
    db.commit()
    writer = make_user(role="writer")
    admin = make_user(role="admin")

    assert client.get("/api/subscribers", headers=auth_headers(writer)).status_code == 403
    assert client.get("/api/subscribers").status_code == 401
    ok = client.get("/api/subscribers", headers=auth_headers(admin))
    assert ok.status_code == 200
    assert any(s["email"] == "a@test.com" for s in ok.json())


def test_remove_subscriber_unknown_404(client, make_user, auth_headers):
    admin = make_user(role="admin")
    assert client.delete("/api/subscribers/999999", headers=auth_headers(admin)).status_code == 404

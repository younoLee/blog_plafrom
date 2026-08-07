"""Web Push — 구독 관리와 암호화 배선.

브라우저 없이 확인할 수 있는 것과 없는 것을 나눠 둔다.
  확인 가능: 구독 등록·갱신·소유권·정리, **암호화가 실제로 열리는지**(왕복)
  확인 불가: 알림이 화면에 뜨는가 → 사람이 봐야 한다
그래서 '알림이 온다'가 아니라 '보낼 수 있는 상태가 맞다'까지를 여기서 건다.
"""
import base64
import os

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.push_subscription import PushSubscription

# 브라우저가 주는 것과 같은 형식의 가짜 구독 값
FAKE = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/abc123",
    "p256dh": base64.urlsafe_b64encode(b"\x04" + os.urandom(64)).rstrip(b"=").decode(),
    "auth": base64.urlsafe_b64encode(os.urandom(16)).rstrip(b"=").decode(),
}


@pytest.fixture
def push_on(monkeypatch):
    """VAPID 키가 설정된 상태."""
    monkeypatch.setattr(settings, "vapid_public_key", "test-public-key")
    monkeypatch.setattr(
        settings,
        "vapid_private_key",
        base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode(),
    )


@pytest.fixture
def push_off(monkeypatch):
    """VAPID 키가 없는 상태 — **명시적으로** 비운다.

    코드 기본값이 빈 문자열이라 처음엔 아무것도 안 하고 '꺼짐'을 전제했는데,
    개발자가 .env에 키를 넣는 순간 그 테스트가 빨간불이 됐다. 환경에 따라
    결과가 갈리는 테스트라 CI에서만 혹은 로컬에서만 초록인 물건이 된다
    (conftest의 no_smtp가 경고하는 바로 그 유형). 전제를 코드로 고정한다."""
    monkeypatch.setattr(settings, "vapid_public_key", "")
    monkeypatch.setattr(settings, "vapid_private_key", "")


# ── 기능 스위치 ──────────────────────────────────────────────────────────────


def test_key_endpoint_503_when_not_configured(client, push_off):
    """키가 없으면 503. 프론트는 이걸 보고 '알림 켜기'를 아예 숨긴다 —
    누를 수 없는 버튼을 보여주는 것보다 없는 게 낫다."""
    assert client.get("/api/push/key").status_code == 503


def test_key_endpoint_needs_no_login(client, push_on):
    """공개키는 비밀이 아니다. 로그인을 요구하면 구독 자체를 못 한다."""
    r = client.get("/api/push/key")
    assert r.status_code == 200
    assert r.json()["public_key"] == "test-public-key"


def test_subscribe_503_when_not_configured(client, make_user, auth_headers, push_off):
    user = make_user(role="pending")
    r = client.post("/api/push", json=FAKE, headers=auth_headers(user))
    assert r.status_code == 503


# ── 구독 등록 ────────────────────────────────────────────────────────────────


def test_subscribe_requires_login(client, push_on):
    assert client.post("/api/push", json=FAKE).status_code == 401


def test_subscribe_registers_device(client, make_user, auth_headers, db, push_on):
    user = make_user(role="pending")  # 구독자도 켤 수 있어야 한다(글쓰기 권한 무관)
    assert client.post("/api/push", json=FAKE, headers=auth_headers(user)).status_code == 204
    row = db.scalar(select(PushSubscription).where(PushSubscription.user_id == user.id))
    assert row.endpoint == FAKE["endpoint"]


def test_resubscribe_updates_instead_of_duplicating(
    client, make_user, auth_headers, db, push_on
):
    """브라우저는 재구독 시 같은 endpoint를 돌려주는 경우가 많다.
    행이 쌓이면 같은 기기에 알림이 두 번 간다."""
    user = make_user(role="pending")
    h = auth_headers(user)
    client.post("/api/push", json=FAKE, headers=h)
    client.post("/api/push", json=FAKE, headers=h)
    rows = db.scalars(
        select(PushSubscription).where(PushSubscription.endpoint == FAKE["endpoint"])
    ).all()
    assert len(rows) == 1


def test_resubscribe_refreshes_keys(client, make_user, auth_headers, db, push_on):
    """endpoint는 같은데 키만 바뀌는 갱신이 있다. 키를 안 갱신하면
    이후 발송이 전부 복호화 실패로 조용히 죽는다."""
    user = make_user(role="pending")
    h = auth_headers(user)
    client.post("/api/push", json=FAKE, headers=h)
    new_auth = base64.urlsafe_b64encode(os.urandom(16)).rstrip(b"=").decode()
    client.post("/api/push", json={**FAKE, "auth": new_auth}, headers=h)
    row = db.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == FAKE["endpoint"])
    )
    assert row.auth == new_auth


def test_shared_browser_transfers_ownership(
    client, make_user, auth_headers, db, push_on
):
    """공용 PC: A가 켜둔 뒤 B가 로그인해 켜면 endpoint는 같다.
    주인을 옮기지 않으면 A의 알림이 B 화면에 뜬다."""
    a = make_user(role="pending")
    b = make_user(role="pending")
    client.post("/api/push", json=FAKE, headers=auth_headers(a))
    client.post("/api/push", json=FAKE, headers=auth_headers(b))
    rows = db.scalars(
        select(PushSubscription).where(PushSubscription.endpoint == FAKE["endpoint"])
    ).all()
    assert len(rows) == 1 and rows[0].user_id == b.id


# ── 해제 ────────────────────────────────────────────────────────────────────


def test_unsubscribe_only_touches_own(client, make_user, auth_headers, db, push_on):
    """남의 endpoint를 아는 사람이 그 사람 알림을 꺼버릴 수 있으면 안 된다."""
    victim = make_user(role="pending")
    attacker = make_user(role="pending")
    client.post("/api/push", json=FAKE, headers=auth_headers(victim))

    r = client.delete(
        f"/api/push?endpoint={FAKE['endpoint']}", headers=auth_headers(attacker)
    )
    assert r.status_code == 204  # 조용히 아무것도 안 지운다
    assert db.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == FAKE["endpoint"])
    ) is not None


def test_unsubscribe_all_devices(client, make_user, auth_headers, db, push_on):
    user = make_user(role="pending")
    h = auth_headers(user)
    client.post("/api/push", json=FAKE, headers=h)
    client.post("/api/push", json={**FAKE, "endpoint": FAKE["endpoint"] + "-2"}, headers=h)
    assert client.delete("/api/push", headers=h).status_code == 204
    assert db.scalars(
        select(PushSubscription).where(PushSubscription.user_id == user.id)
    ).all() == []


def test_status_counts_devices(client, make_user, auth_headers, push_on):
    user = make_user(role="pending")
    h = auth_headers(user)
    client.post("/api/push", json=FAKE, headers=h)
    client.post("/api/push", json={**FAKE, "endpoint": FAKE["endpoint"] + "-2"}, headers=h)
    body = client.get("/api/push", headers=h).json()
    assert body == {"enabled": True, "devices": 2}


def test_status_hides_endpoints(client, make_user, auth_headers, push_on):
    """endpoint는 사실상 기기 식별자라 돌려줄 이유가 없다."""
    user = make_user(role="pending")
    h = auth_headers(user)
    client.post("/api/push", json=FAKE, headers=h)
    assert "endpoint" not in client.get("/api/push", headers=h).text


def test_account_deletion_removes_subscriptions(
    client, make_user, auth_headers, db, push_on
):
    """FK가 CASCADE — 계정이 사라지면 그 기기로 가던 알림도 멈춰야 한다."""
    admin = make_user(role="admin")
    user = make_user(role="pending")
    client.post("/api/push", json=FAKE, headers=auth_headers(user))
    client.delete(f"/api/admin/users/{user.id}", headers=auth_headers(admin))
    assert db.scalars(select(PushSubscription)).all() == []


# ── 암호화 배선 ──────────────────────────────────────────────────────────────


def test_payload_encryption_roundtrips():
    """**브라우저 없이 검증할 수 있는 유일한 지점.**

    가짜 구독자 키쌍으로 봉인했다가 그 개인키로 열어본다. 열리면 aes128gcm
    파라미터(dh·auth_secret·버전) 배선이 맞다는 뜻이다. 여기가 틀리면 알림은
    '안 온다'로만 보이고 서버 로그엔 아무 단서도 안 남는다."""
    from app.services.push import _selftest_roundtrip

    assert _selftest_roundtrip() is True


def test_vapid_audience_is_origin_not_full_endpoint(push_on):
    """`aud`에 경로까지 넣으면 푸시 서비스가 401로 거절한다(RFC 8292).
    눈으로는 잘 안 보이는 실수라 값을 직접 확인한다."""
    import jwt

    from app.services.push import _vapid_headers

    headers = _vapid_headers("https://fcm.googleapis.com/fcm/send/abc123?x=1")
    token = headers["Authorization"].split("t=")[1].split(",")[0]
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["aud"] == "https://fcm.googleapis.com"


def test_vapid_uses_rfc8292_scheme(push_on):
    """Vapid01(draft)이 아니라 Vapid02여야 한다 — Apple이 후자만 받는다."""
    from app.services.push import _vapid_headers

    auth = _vapid_headers("https://web.push.apple.com/x")["Authorization"]
    assert auth.startswith("vapid t=") and ",k=" in auth

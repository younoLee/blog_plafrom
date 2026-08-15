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


# ── 엔드포인트 허용목록 (SSRF 차단) ─────────────────────────────────────────


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://10.0.1.23:8080/probe",  # 내부망
        "http://127.0.0.1:8000/api/health",  # 자기 자신
        "http://169.254.169.254/latest/meta-data/",  # 메타데이터
        "https://evil.example/x",  # 외부지만 푸시 서비스 아님
        "http://fcm.googleapis.com/fcm/send/x",  # 평문 https 아님
        "https://fcm.googleapis.com.evil.com/x",  # 접미사 위장
    ],
)
def test_subscribe_rejects_non_push_endpoints(
    client, make_user, auth_headers, push_on, endpoint
):
    """서버가 나중에 이 URL로 POST한다 — 검사 없으면 SSRF다."""
    user = make_user(role="pending")
    r = client.post(
        "/api/push", json={**FAKE, "endpoint": endpoint}, headers=auth_headers(user)
    )
    assert r.status_code == 422, f"{endpoint} 가 통과했다"


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://fcm.googleapis.com/fcm/send/abc",
        "https://updates.push.services.mozilla.com/wpush/v2/abc",
        "https://web.push.apple.com/abc",
        "https://xyz.notify.windows.com/w/?token=abc",
    ],
)
def test_subscribe_accepts_real_push_services(
    client, make_user, auth_headers, push_on, endpoint
):
    """허용목록이 실제 브라우저를 막으면 기능이 죽는다."""
    user = make_user(role="pending")
    r = client.post(
        "/api/push", json={**FAKE, "endpoint": endpoint}, headers=auth_headers(user)
    )
    assert r.status_code == 204


def test_send_push_refuses_disallowed_endpoint_even_if_stored():
    """등록을 막아도 이 검사 이전에 저장된 행·DB 직접 수정이 남는다.
    발송 시점에도 한 번 더 본다."""
    from app.services.push import PushGone, send_push

    with pytest.raises(PushGone):
        send_push("http://169.254.169.254/x", FAKE["p256dh"], FAKE["auth"], {"a": 1})


def test_endpoint_only_cannot_steal_another_users_device(
    client, make_user, auth_headers, db, push_on
):
    """endpoint만 아는 사람이 남의 구독을 가져가면 안 된다.

    정당한 구독자는 브라우저에서 endpoint·p256dh·auth를 함께 받으므로 셋을 다
    갖는다. 키가 다르면 그 기기를 실제로 쥔 사람이 아니다."""
    victim = make_user(role="pending")
    attacker = make_user(role="pending")
    client.post("/api/push", json=FAKE, headers=auth_headers(victim))

    other_key = base64.urlsafe_b64encode(os.urandom(16)).rstrip(b"=").decode()
    r = client.post(
        "/api/push", json={**FAKE, "auth": other_key}, headers=auth_headers(attacker)
    )
    assert r.status_code == 409
    row = db.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == FAKE["endpoint"])
    )
    assert row.user_id == victim.id  # 주인이 그대로다


# ── 발송 경로 (notify_new_post_push) ─────────────────────────────────────────
#
# 이 경로가 통째로 미검증이었다(2026-08-07 검사). 대상 조건을 뒤집거나, 죽은 구독
# 정리를 지우거나, 기기별 예외 격리를 없애도 전부 초록이었다 — 셋 다 프로덕션에서만
# 드러나는 종류다(옵트아웃한 사람에게 알림이 가거나, 일시적 장애에 멀쩡한 구독이
# 전멸하거나, 잘못된 행 하나가 뒤의 모든 기기를 막거나).


def _sub(client, headers, endpoint):
    client.post("/api/push", json={**FAKE, "endpoint": endpoint}, headers=headers)


class _KeepOpen:
    """테스트 세션을 넘겨주되 close()만 무시하는 껍데기.

    notify_new_post_push는 자기 세션을 열고 finally에서 닫는다(백그라운드라 맞는
    동작이다). 그런데 테스트에선 그 자리에 테스트 세션을 끼워넣으므로, 그대로
    닫히면 이후 객체가 전부 detached가 되어 검증을 못 한다."""

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        pass


def test_push_goes_only_to_approved_and_notifying_subscribers(
    client, make_user, auth_headers, db, push_on, monkeypatch
):
    from app.models.author_subscription import AuthorSubscription
    from app.services import push as push_svc

    author = make_user(role="writer")
    want = make_user(role="pending")  # 승인 + 알림 켬
    optout = make_user(role="pending")  # 승인됐지만 알림 끔
    pending_sub = make_user(role="pending")  # 알림 켰지만 미승인

    db.add_all(
        [
            AuthorSubscription(subscriber_id=want.id, author_id=author.id, approved=True, notify=True),
            AuthorSubscription(subscriber_id=optout.id, author_id=author.id, approved=True, notify=False),
            AuthorSubscription(subscriber_id=pending_sub.id, author_id=author.id, approved=False, notify=True),
        ]
    )
    db.commit()
    base = "https://fcm.googleapis.com/fcm/send/"
    _sub(client, auth_headers(want), base + "want")
    _sub(client, auth_headers(optout), base + "optout")
    _sub(client, auth_headers(pending_sub), base + "pending")

    sent = []
    monkeypatch.setattr(push_svc, "send_push", lambda e, p, a, d: sent.append(e))
    monkeypatch.setattr(push_svc, "SessionLocal", lambda: _KeepOpen(db))

    author_id = author.id
    push_svc.notify_new_post_push(1, "새 글", author_id)
    assert sent == [base + "want"]


def test_dead_subscription_is_removed_and_others_still_get_sent(
    client, make_user, auth_headers, db, push_on, monkeypatch
):
    """410은 영구 무효라 지운다. 하지만 **일시적 실패는 지우면 안 되고**,
    한 기기의 실패가 뒤의 기기를 막아서도 안 된다."""
    from app.models.author_subscription import AuthorSubscription
    from app.services import push as push_svc

    author = make_user(role="writer")
    sub_user = make_user(role="pending")
    db.add(
        AuthorSubscription(
            subscriber_id=sub_user.id, author_id=author.id, approved=True, notify=True
        )
    )
    db.commit()
    base = "https://fcm.googleapis.com/fcm/send/"
    for name in ("dead", "flaky", "ok"):
        _sub(client, auth_headers(sub_user), base + name)

    tried = []

    def fake_send(endpoint, p256dh, auth, data):
        tried.append(endpoint)
        if endpoint.endswith("dead"):
            raise push_svc.PushGone("410")
        if endpoint.endswith("flaky"):
            raise RuntimeError("일시적 오류")

    monkeypatch.setattr(push_svc, "send_push", fake_send)
    monkeypatch.setattr(push_svc, "SessionLocal", lambda: _KeepOpen(db))
    author_id, user_id = author.id, sub_user.id
    push_svc.notify_new_post_push(1, "새 글", author_id)

    assert len(tried) == 3, "한 기기 실패가 나머지를 막았다"
    left = {
        e
        for (e,) in db.execute(
            select(PushSubscription.endpoint).where(
                PushSubscription.user_id == user_id
            )
        ).all()
    }
    assert base + "dead" not in left  # 영구 무효는 정리됐다
    assert base + "flaky" in left and base + "ok" in left  # 일시 실패는 살아 있다


def test_push_is_noop_when_keys_missing(client, make_user, auth_headers, db, monkeypatch):
    """키가 없으면 기능이 통째로 꺼진다 — 조회조차 하지 않아야 한다."""
    from app.services import push as push_svc

    called = []
    monkeypatch.setattr(push_svc, "send_push", lambda *a: called.append(a))
    monkeypatch.setattr(push_svc, "SessionLocal", lambda: _KeepOpen(db))
    push_svc.notify_new_post_push(1, "새 글", 1)
    assert called == []


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


# ── 알림 묶음 키(tag) — 종류가 다른 알림이 서로를 지우면 안 된다 ─────────────
#
# 2026-08-14에 `tag`만 있고 `renotify`가 없어 두 번째 알림부터 조용히 교체되는 걸
# 겪었다. 2026-08-15에 댓글 알림을 붙이면서 **같은 실패의 다른 얼굴**이 드러났다:
# sw.js의 tag가 'new-post' 고정이라, 댓글 알림이 새 글 알림을 갈아치웠다.
# 화면에 아무 흔적이 없는 실패라 여기서 값으로 잠근다(짝인 sw.js 쪽은 프론트
# swNotify.test.ts가 소스를 읽어 본다).
#
# ⚠️ **대상 조회는 여기서 검사할 수 없다.** 이 함수들은 자체 SessionLocal을 여는데
#    테스트 db 픽스처는 롤백되는 트랜잭션이라, 테스트가 넣은 구독 행이 그 세션에는
#    안 보인다. 그래서 subs는 항상 비고, 여기서 거는 건 **payload**뿐이다.
#    (그 성질 자체는 conftest의 no_push 주석이 이미 경고하는 것과 같은 사정이다)


def _capture_payload(monkeypatch, func, *args):
    """_deliver를 가로채 payload만 꺼낸다. 실제 발송은 하지 않는다."""
    from app.services import push as push_mod

    seen = {}

    def fake_deliver(subs, payload):
        seen["payload"] = payload

    monkeypatch.setattr(push_mod, "_deliver", fake_deliver)
    func(*args)
    return seen["payload"]


def test_new_post_and_comment_push_use_different_tags(monkeypatch, push_on):
    from app.services.push import notify_new_comment_push, notify_new_post_push

    post = _capture_payload(monkeypatch, notify_new_post_push, 7, "제목", 1)
    comment = _capture_payload(
        monkeypatch, notify_new_comment_push, 7, "제목", "지나가던 사람", 1
    )

    assert post["tag"] == "new-post"
    # 글 번호가 들어가야 다른 글의 댓글끼리도 안 겹친다.
    assert comment["tag"] == "comment-7"
    assert post["tag"] != comment["tag"]
    # 댓글 알림은 댓글 자리로 데려간다(긴 글에서 맨 위에 떨어지면 뭘 봐야 할지 모른다).
    assert comment["url"].endswith("#comments")


def test_comment_push_does_not_carry_the_comment_body(monkeypatch, push_on):
    """익명 입력이라 잠금화면에 그대로 띄우면 아무나 남의 잠금화면에 글자를 쓸 수 있다.

    누가 어느 글에 달았는지만 알린다."""
    from app.services.push import notify_new_comment_push

    payload = _capture_payload(
        monkeypatch, notify_new_comment_push, 7, "글 제목", "작성자", 1
    )
    assert payload["body"] == "글 제목"
    assert "작성자" in payload["title"]


def test_push_does_nothing_when_keys_are_missing(monkeypatch, push_off):
    """키가 없으면 payload를 만들지도 않는다(기능 통째로 꺼짐)."""
    from app.services import push as push_mod
    from app.services.push import notify_new_comment_push

    called = []
    monkeypatch.setattr(push_mod, "_deliver", lambda s, p: called.append(p))
    notify_new_comment_push(7, "제목", "작성자", 1)
    assert called == []

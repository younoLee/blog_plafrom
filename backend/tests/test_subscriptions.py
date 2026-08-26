"""글쓴이 구독: 등록/목록/해제 + 자기 자신 구독 차단."""


def test_subscribe_and_list(client, make_user, auth_headers):
    author = make_user(role="writer")
    reader = make_user(role="writer")

    r = client.post(
        "/api/subscriptions",
        headers=auth_headers(reader),
        json={"author_id": author.id},
    )
    assert r.status_code == 201

    lst = client.get("/api/subscriptions", headers=auth_headers(reader))
    assert lst.status_code == 200
    assert author.id in lst.json()


def test_cannot_subscribe_self(client, make_user, auth_headers):
    user = make_user(role="writer")
    r = client.post(
        "/api/subscriptions",
        headers=auth_headers(user),
        json={"author_id": user.id},
    )
    assert r.status_code == 400


def test_subscribe_unknown_author_404(client, make_user, auth_headers):
    reader = make_user(role="writer")
    r = client.post(
        "/api/subscriptions",
        headers=auth_headers(reader),
        json={"author_id": 999999},
    )
    assert r.status_code == 404


def test_unsubscribe(client, make_user, auth_headers):
    author = make_user(role="writer")
    reader = make_user(role="writer")
    client.post(
        "/api/subscriptions",
        headers=auth_headers(reader),
        json={"author_id": author.id},
    )

    r = client.delete(
        f"/api/subscriptions/{author.id}", headers=auth_headers(reader)
    )
    assert r.status_code == 204

    lst = client.get("/api/subscriptions", headers=auth_headers(reader))
    assert author.id not in lst.json()


def test_subscriptions_require_auth(client):
    assert client.get("/api/subscriptions").status_code == 401


# ── 글쓴이별 알림 (구독한 다음에만) ───────────────────────────────────────────
def test_notify_requires_subscription_first(client, make_user, auth_headers):
    author = make_user(role="writer")
    reader = make_user(role="writer")
    # 구독 안 한 상태에서 알림 켜기 → 404 (구독이 먼저)
    r = client.put(
        f"/api/subscriptions/{author.id}/notify",
        headers=auth_headers(reader),
        json={"notify": True},
    )
    assert r.status_code == 404


def _subscribe_and_approve(client, auth_headers, reader, author):
    client.post(
        "/api/subscriptions", headers=auth_headers(reader), json={"author_id": author.id}
    )
    client.post(
        f"/api/subscriptions/requests/{reader.id}/approve", headers=auth_headers(author)
    )


def test_notify_blocked_until_approved(client, make_user, auth_headers):
    author = make_user(role="writer")
    reader = make_user(role="writer")
    # 신청만 하고 승인 전 → 알림 켜기 400 (승인 대기)
    client.post(
        "/api/subscriptions", headers=auth_headers(reader), json={"author_id": author.id}
    )
    pending = client.put(
        f"/api/subscriptions/{author.id}/notify",
        headers=auth_headers(reader),
        json={"notify": True},
    )
    assert pending.status_code == 400


def test_notify_toggle_after_approval(client, make_user, auth_headers):
    author = make_user(role="writer")
    reader = make_user(role="writer")
    _subscribe_and_approve(client, auth_headers, reader, author)

    # 승인 후 기본 알림은 꺼짐
    detail = client.get("/api/subscriptions/detail", headers=auth_headers(reader)).json()
    assert detail[0]["approved"] is True
    assert detail[0]["notify"] is False

    on = client.put(
        f"/api/subscriptions/{author.id}/notify",
        headers=auth_headers(reader),
        json={"notify": True},
    )
    assert on.status_code == 200
    assert on.json()["notify"] is True


# ── 구독 승인 흐름 (2단계) ────────────────────────────────────────────────────
def test_subscribe_is_pending_and_author_sees_request(client, make_user, auth_headers):
    author = make_user(role="writer")
    reader = make_user(role="writer")
    sub = client.post(
        "/api/subscriptions", headers=auth_headers(reader), json={"author_id": author.id}
    )
    assert sub.json()["approved"] is False  # 신청 = 대기

    # 글쓴이에게 신청이 보임
    reqs = client.get("/api/subscriptions/requests", headers=auth_headers(author))
    assert reqs.status_code == 200
    assert any(r["id"] == reader.id for r in reqs.json())


def test_approve_moves_out_of_requests(client, make_user, auth_headers):
    author = make_user(role="writer")
    reader = make_user(role="writer")
    client.post(
        "/api/subscriptions", headers=auth_headers(reader), json={"author_id": author.id}
    )
    ap = client.post(
        f"/api/subscriptions/requests/{reader.id}/approve", headers=auth_headers(author)
    )
    assert ap.status_code == 204
    # 승인되면 대기 목록에서 사라짐
    reqs = client.get("/api/subscriptions/requests", headers=auth_headers(author)).json()
    assert all(r["id"] != reader.id for r in reqs)


def test_reject_deletes_request(client, make_user, auth_headers):
    author = make_user(role="writer")
    reader = make_user(role="writer")
    client.post(
        "/api/subscriptions", headers=auth_headers(reader), json={"author_id": author.id}
    )
    rej = client.delete(
        f"/api/subscriptions/requests/{reader.id}", headers=auth_headers(author)
    )
    assert rej.status_code == 204
    # 거절되면 구독 자체가 사라짐(내 구독 목록에 없음)
    mine = client.get("/api/subscriptions", headers=auth_headers(reader)).json()
    assert author.id not in mine


def test_approve_unknown_request_404(client, make_user, auth_headers):
    author = make_user(role="writer")
    assert (
        client.post(
            "/api/subscriptions/requests/999999/approve", headers=auth_headers(author)
        ).status_code
        == 404
    )


def test_banned_subscriber_gets_no_new_post_mail(make_user, db, sent_mail, monkeypatch):
    """차단된 구독자의 계정 메일함으로 새 글 알림이 가지 않는다.

    푸시(test_push.py)와 쌍둥이인 경로다. 이쪽은 조회가 이미 User를 join하고 있었으면서도
    역할을 안 봐서, 차단된 계정으로 구독자 전용 글의 제목이 계속 나갔다(2026-08-26).
    """
    from app.models.author_subscription import AuthorSubscription
    from app.services import email as email_svc

    author = make_user(role="writer")
    ok = make_user(role="pending", email="ok-sub@test.com")
    banned = make_user(role="banned", email="banned-sub@test.com")

    db.add_all(
        [
            AuthorSubscription(subscriber_id=ok.id, author_id=author.id, approved=True, notify=True),
            AuthorSubscription(subscriber_id=banned.id, author_id=author.id, approved=True, notify=True),
        ]
    )
    db.commit()

    monkeypatch.setattr(email_svc, "SessionLocal", lambda: _KeepOpenSession(db))
    email_svc.notify_new_post(1, "구독자 전용 글", author.id)

    recipients = [to for m in sent_mail for to in str(m["To"]).split(", ")]
    assert "ok-sub@test.com" in recipients
    assert "banned-sub@test.com" not in recipients


class _KeepOpenSession:
    """서비스가 자체 세션을 열고 close()하는데, 테스트는 롤백 트랜잭션을 살려둬야 한다."""

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def close(self):
        pass

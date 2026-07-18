"""인앱 알림 — 승인+알림 켠 구독자만, 글 작성 시 생성, 읽음 처리."""


def _subscribe_approve_notify(client, auth_headers, reader, author):
    client.post("/api/subscriptions", headers=auth_headers(reader), json={"author_id": author.id})
    client.post(f"/api/subscriptions/requests/{reader.id}/approve", headers=auth_headers(author))
    client.put(
        f"/api/subscriptions/{author.id}/notify",
        headers=auth_headers(reader),
        json={"notify": True},
    )


def _create_post(client, headers, visibility="public"):
    r = client.post(
        "/api/posts",
        headers=headers,
        json={"title": "새 글", "content": "C", "visibility": visibility},
    )
    assert r.status_code == 201
    return r.json()


def test_new_post_notifies_notify_subscriber(client, make_user, auth_headers):
    author = make_user(role="writer")
    reader = make_user(role="writer")
    _subscribe_approve_notify(client, auth_headers, reader, author)

    _create_post(client, auth_headers(author))

    body = client.get("/api/notifications", headers=auth_headers(reader)).json()
    assert body["unread"] == 1
    assert body["items"][0]["title"] == "새 글"
    assert body["items"][0]["author"] == author.email.split("@")[0]
    assert body["items"][0]["read"] is False


def test_no_notification_when_notify_off(client, make_user, auth_headers):
    author = make_user(role="writer")
    reader = make_user(role="writer")
    # 승인까지만, 알림은 안 켬
    client.post("/api/subscriptions", headers=auth_headers(reader), json={"author_id": author.id})
    client.post(f"/api/subscriptions/requests/{reader.id}/approve", headers=auth_headers(author))

    _create_post(client, auth_headers(author))

    body = client.get("/api/notifications", headers=auth_headers(reader)).json()
    assert body["unread"] == 0
    assert body["items"] == []


def test_no_notification_when_pending(client, make_user, auth_headers):
    # 승인 안 된(대기) 구독은 알림 대상 아님
    author = make_user(role="writer")
    reader = make_user(role="writer")
    client.post("/api/subscriptions", headers=auth_headers(reader), json={"author_id": author.id})
    _create_post(client, auth_headers(author))
    assert client.get("/api/notifications", headers=auth_headers(reader)).json()["unread"] == 0


def test_private_post_notifies_nobody(client, make_user, auth_headers):
    author = make_user(role="writer")
    reader = make_user(role="writer")
    _subscribe_approve_notify(client, auth_headers, reader, author)
    _create_post(client, auth_headers(author), visibility="private")
    assert client.get("/api/notifications", headers=auth_headers(reader)).json()["unread"] == 0


def test_mark_all_read(client, make_user, auth_headers):
    author = make_user(role="writer")
    reader = make_user(role="writer")
    _subscribe_approve_notify(client, auth_headers, reader, author)
    _create_post(client, auth_headers(author))

    assert client.get("/api/notifications", headers=auth_headers(reader)).json()["unread"] == 1
    assert client.post("/api/notifications/read", headers=auth_headers(reader)).status_code == 204

    body = client.get("/api/notifications", headers=auth_headers(reader)).json()
    assert body["unread"] == 0
    assert body["items"][0]["read"] is True  # 목록엔 남되 읽음 표시


def test_notifications_require_auth(client):
    assert client.get("/api/notifications").status_code == 401

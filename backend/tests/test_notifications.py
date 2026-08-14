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
    # 표시명은 display_name에서만 온다 — **이메일 유도가 아니다**(2026-08-10 보안검사).
    # display_name을 안 정한 계정은 "회원 #<id>"로 뭉갠다. 이메일 로컬파트가 새지 않는 게 요점이다.
    #
    # ⚠️ **글쓴이의 user id여야 한다.** 이 쿼리는 Notification.id와 User.id를 한 행에
    # 담는데, 폴백에 `r.id`를 넘기면 조용히 '회원 #<알림번호>'가 된다 — 고치는 중에
    # 실제로 그렇게 썼다가 이 테스트가 잡았다.
    assert body["items"][0]["author"] == f"회원 #{author.id}"
    assert author.email.split("@")[0] not in body["items"][0]["author"]
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


def test_unread_badge_drops_when_post_becomes_invisible(client, make_user, auth_headers):
    """글이 안 보이게 되면 목록뿐 아니라 **배지 숫자도** 같이 줄어야 한다.

    2026-07-31 심층검사에서 나온 것: 목록에는 가시성 조건이 걸려 있었는데 unread 카운트에는
    없어서, 글이 private로 바뀌면 **배지엔 1이 떠 있는데 열면 0개**가 됐다. 사용자는 눌러도
    사라지지 않는 배지를 보게 된다. 한쪽만 고쳐진 전형적인 모양이라 계약으로 못박는다.
    """
    author = make_user(role="writer")
    reader = make_user(role="writer")
    _subscribe_approve_notify(client, auth_headers, reader, author)
    post = _create_post(client, auth_headers(author))

    body = client.get("/api/notifications", headers=auth_headers(reader)).json()
    assert body["unread"] == 1 and len(body["items"]) == 1

    # 글쓴이가 공개범위를 '나만 보기'로 내린다 → 구독자는 더 이상 볼 수 없다
    r = client.patch(
        f"/api/posts/{post['id']}/visibility",
        headers=auth_headers(author),
        json={"visibility": "private"},
    )
    assert r.status_code == 200

    body = client.get("/api/notifications", headers=auth_headers(reader)).json()
    assert body["items"] == []
    assert body["unread"] == 0  # 수정 전: 목록은 비었는데 여기만 1이었다

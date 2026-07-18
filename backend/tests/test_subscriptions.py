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


def test_notify_toggle_after_subscribe(client, make_user, auth_headers):
    author = make_user(role="writer")
    reader = make_user(role="writer")
    client.post(
        "/api/subscriptions", headers=auth_headers(reader), json={"author_id": author.id}
    )
    # 구독 직후 알림은 기본 꺼짐
    detail = client.get("/api/subscriptions/detail", headers=auth_headers(reader)).json()
    assert detail[0]["notify"] is False

    # 켜기 → 반영
    on = client.put(
        f"/api/subscriptions/{author.id}/notify",
        headers=auth_headers(reader),
        json={"notify": True},
    )
    assert on.status_code == 200
    assert on.json()["notify"] is True
    detail2 = client.get("/api/subscriptions/detail", headers=auth_headers(reader)).json()
    assert detail2[0]["notify"] is True

    # 끄기
    off = client.put(
        f"/api/subscriptions/{author.id}/notify",
        headers=auth_headers(reader),
        json={"notify": False},
    )
    assert off.json()["notify"] is False

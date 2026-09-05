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


# ── 구독 신청 대상 검사 (2026-09-02) ─────────────────────────────────────────
#
# 신청 한 번이 알림 행을 하나 만든다. 대상 검사가 없으면 그 알림을 **아무 계정에게나**
# 만들 수 있고, 응답이 갈리면 그 과정에서 계정 존재까지 읽힌다.


def test_구독_신청은_글쓴이가_아닌_계정에는_안_된다(client, make_user, auth_headers, db):
    """pending·reader 계정은 공개 블로그가 없다(PUBLIC_BLOG_ROLES). 구독 대상이 아니다.

    화면의 '구독할 수 있는 글쓴이' 목록(GET /authors)은 원래 writer·admin만 보여줬는데
    POST는 그 목록 밖으로 나갈 수 있었다 — 화면만 좁고 API는 열린 형태였다."""
    from app.models.notification import Notification

    target = make_user(role="pending")
    reader = make_user(role="writer")

    r = client.post(
        "/api/subscriptions",
        headers=auth_headers(reader),
        json={"author_id": target.id},
    )
    assert r.status_code == 404
    # 거절만으로는 부족하다 — 알림 행이 안 생겼는지까지 본다. 이 라우트의 부작용이
    # 정확히 그것이고, 남용의 대가도 그것이다.
    from sqlalchemy import select

    assert db.scalars(
        select(Notification).where(Notification.user_id == target.id)
    ).all() == []


def test_구독_신청은_차단된_계정에도_안_된다(client, make_user, auth_headers):
    # banned는 글이 이미 안 나가는데(test_banned_subscriber_gets_no_new_post_mail),
    # 구독 신청만 받아주면 승인할 사람 없는 대기 행이 쌓인다.
    banned = make_user(role="banned")
    reader = make_user(role="writer")
    r = client.post(
        "/api/subscriptions",
        headers=auth_headers(reader),
        json={"author_id": banned.id},
    )
    assert r.status_code == 404


def test_없는_id와_글쓴이_아닌_id의_응답이_같다(client, make_user, auth_headers):
    """존재 열거 차단. 두 응답이 갈리면 이 라우트가 계정 존재 확인기가 된다 —
    id를 세면서 '없다'와 '있지만 글쓴이가 아니다'를 구분하면 가입자 수와 id 배치가
    읽힌다. 글쓴이 목록은 이미 공개지만(GET /authors) 독자·pending의 존재는 아니다."""
    reader = make_user(role="writer")
    existing_non_author = make_user(role="pending")

    missing = client.post(
        "/api/subscriptions",
        headers=auth_headers(reader),
        json={"author_id": 999999},
    )
    non_author = client.post(
        "/api/subscriptions",
        headers=auth_headers(reader),
        json={"author_id": existing_non_author.id},
    )
    assert missing.status_code == non_author.status_code == 404
    # 본문까지 같아야 한다. 코드만 맞추고 detail이 갈리면 오라클은 그대로 남는다.
    assert missing.json() == non_author.json()


def test_구독_신청에_레이트리밋이_걸려_있다():
    """한도 자체는 conftest가 limiter.enabled=False로 꺼둬서 요청 수로는 못 잰다.
    그래서 **등록된 한도**를 본다. 이게 없으면 pending 계정 하나로 남의 알림함을
    채울 수 있고, 대상마다 새 신청이라 아래의 멱등 처리로도 안 막힌다.

    slowapi는 `모듈.함수명`을 키로 한도를 들고 있다(extension.py의 __limit_decorator).
    데코레이터를 지우면 이 키가 통째로 사라지므로 회귀가 바로 빨간불이 된다."""
    from app.core.ratelimit import limiter

    limits = limiter._route_limits["app.routers.subscriptions.subscribe"]
    assert [str(lim.limit) for lim in limits] == ["30 per 1 hour"]


# ── 구독 가능한 글쓴이 목록이 한 번도 안 불렸다 (09-04 검사 BQ-9) ────────────
#
# `GET /api/subscriptions/authors` 는 tests 전체에서 문자열이 0건이었다. 이 목록의
# 규칙은 POST /subscriptions 의 404 판정과 **짝이어야 한다** — 목록에 없는 사람을
# 구독할 수 있거나, 목록에 있는 사람을 구독할 수 없으면 화면이 거짓말을 한다.


def test_구독_목록은_글쓴이만_주고_자기_자신은_뺀다(client, make_user, auth_headers):
    me = make_user(role="writer")
    other_writer = make_user(role="writer")
    admin = make_user(role="admin")
    pending = make_user(role="pending")
    banned = make_user(role="banned")

    r = client.get("/api/subscriptions/authors", headers=auth_headers(me))
    assert r.status_code == 200
    ids = {a["id"] for a in r.json()}

    assert other_writer.id in ids
    assert admin.id in ids  # 관리자도 글을 쓴다
    assert me.id not in ids  # 자기 자신은 구독할 수 없다(POST 가 400 을 준다)
    assert pending.id not in ids
    assert banned.id not in ids


def test_구독_목록과_구독_가능_판정이_같은_규칙이다(client, make_user, auth_headers):
    """목록에 없는 사람에게 신청하면 404 여야 한다 — 두 규칙이 갈라지면 화면이 거짓말한다."""
    me = make_user(role="writer")
    pending = make_user(role="pending")
    ah = auth_headers(me)

    ids = {a["id"] for a in client.get("/api/subscriptions/authors", headers=ah).json()}
    assert pending.id not in ids
    assert client.post("/api/subscriptions", json={"author_id": pending.id}, headers=ah).status_code == 404

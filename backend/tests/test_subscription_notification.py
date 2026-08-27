"""구독 신청이 글쓴이에게 실제로 닿는가 (2026-08-27 신설).

구독은 '신청 → 글쓴이 승인' 구조인데, 신청이 들어와도 **글쓴이에게 아무 신호도 안 갔다.**
신청한 사람은 '승인 대기중' 배지를 무기한 보고, 글쓴이는 신청이 온 사실 자체를 모르니
승인이 안 나고, 결과적으로 구독자공개 글이 영영 안 열렸다.

알림을 만들면 되는데 **지금 스키마로는 만들 수조차 없었다.** `notifications.post_id`가
NOT NULL 이라 모든 알림이 글에 매여 있어야 했고, 구독 신청은 가리킬 글이 없다.
마이그레이션 f8a9b0c1d2e3 이 그걸 풀었다.

여기서 잠그는 것 중 가장 중요한 건 **가시성 조건 면제**다. 알림 목록은 Post 를 조인해
'지금 이 사용자에게 보이는 글'만 남기는데, 글에 안 매인 알림은 그 조인이 전부 NULL 이
되어 조건이 NULL 로 평가되고 WHERE 가 행을 버린다. 면제를 빠뜨리면 알림이 만들어지자마자
사라지는데, **새는 쪽이 아니라 사라지는 쪽의 실수라 조용하다.**
"""

from sqlalchemy import select

from app.models.notification import Notification


def test_subscribe_notifies_author(client, make_user, auth_headers, db):
    author = make_user(role="writer", display_name="글쓴이")
    reader = make_user(role="writer", display_name="읽는이")

    r = client.post("/api/subscriptions", json={"author_id": author.id}, headers=auth_headers(reader))
    assert r.status_code == 201

    n = db.scalar(select(Notification).where(Notification.user_id == author.id))
    assert n is not None
    assert n.post_id is None  # 글에 안 매인 알림
    assert n.actor_id == reader.id


def test_author_sees_request_in_notification_list(client, make_user, auth_headers):
    """**가시성 조건 면제가 안 되면 여기서 걸린다.**

    글에 안 매인 알림은 Post outer join이 전부 NULL 이라 visible_condition 이 NULL 로
    평가된다. SQL 에서 NULL 은 참이 아니므로 면제하지 않으면 행이 버려지고, 이 테스트가
    빈 목록을 본다.
    """
    author = make_user(role="writer", display_name="글쓴이")
    reader = make_user(role="writer", display_name="읽는이")
    client.post("/api/subscriptions", json={"author_id": author.id}, headers=auth_headers(reader))

    body = client.get("/api/notifications", headers=auth_headers(author)).json()
    assert body["unread"] == 1
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["post_id"] is None
    assert item["title"] is None
    assert item["comment_id"] is None
    assert item["author"] == "읽는이"  # 신청한 사람이 나와야 한다


def test_badge_and_list_agree(client, make_user, auth_headers):
    """배지와 목록이 같은 기준을 쓰는가.

    2026-07-31 심층검사가 잡은 모양: 한쪽만 고쳐서 배지엔 숫자가 떠 있는데 열면 0개.
    08-27 에 목록을 outer join 으로 바꾸면서 배지 쪽도 같이 바꿔야 했다.
    """
    author = make_user(role="writer")
    for _ in range(3):
        reader = make_user(role="writer")
        client.post("/api/subscriptions", json={"author_id": author.id}, headers=auth_headers(reader))

    body = client.get("/api/notifications", headers=auth_headers(author)).json()
    assert body["unread"] == len(body["items"]) == 3


def test_idempotent_resubscribe_does_not_pile_up(client, make_user, auth_headers, db):
    """같은 사람이 다시 신청해도 알림이 쌓이면 안 된다.

    subscribe() 는 이미 신청/구독 중이면 그 상태를 그대로 돌려주는 멱등 경로가 있다.
    알림 생성을 그 분기 밖에 두면 누를 때마다 종이 울린다.
    """
    author = make_user(role="writer")
    reader = make_user(role="writer")
    for _ in range(3):
        client.post("/api/subscriptions", json={"author_id": author.id}, headers=auth_headers(reader))

    n = db.scalars(select(Notification).where(Notification.user_id == author.id)).all()
    assert len(n) == 1


def test_post_notifications_still_work(client, make_user, auth_headers):
    """기존 두 종류가 안 깨졌는가.

    Post 조인을 inner 에서 outer 로 바꾸면서 가시성 조건이 헐거워지지 않았는지 본다.
    비공개 글의 알림은 여전히 안 보여야 한다 — 그게 원래 이 조건이 있는 이유다.
    """
    author = make_user(role="writer")
    reader = make_user(role="writer")
    ah = auth_headers(author)

    post = client.post(
        "/api/posts",
        json={"title": "T", "content": "C", "visibility": "public"},
        headers=ah,
    ).json()
    # 글쓴이 본인에게 가는 '새 댓글' 알림을 만든다
    client.post(f"/api/posts/{post['id']}/comments", json={"author": "손님", "content": "안녕"})

    body = client.get("/api/notifications", headers=ah).json()
    assert any(i["post_id"] == post["id"] and i["comment_id"] for i in body["items"])

    # 글을 비공개로 바꾸면 구독자 쪽에서는 안 보여야 한다(원래 조건이 지키던 것).
    client.patch(f"/api/posts/{post['id']}/visibility", json={"visibility": "private"}, headers=ah)
    reader_body = client.get("/api/notifications", headers=auth_headers(reader)).json()
    assert all(i["post_id"] != post["id"] for i in reader_body["items"])

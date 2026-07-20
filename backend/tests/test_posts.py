"""글 권한 매트릭스가 이 앱의 가장 복잡한 로직이라 여기에 테스트를 집중한다.
공개범위(public/subscribers/private) × 열람자(익명/남/본인/구독자) + 소유자 게이팅.
"""
import pytest


def _create_post(client, headers, *, visibility="public", title="T", content="C"):
    r = client.post(
        "/api/posts",
        headers=headers,
        json={"title": title, "content": content, "visibility": visibility},
    )
    assert r.status_code == 201, r.text
    return r.json()


# ── 생성 권한 ──────────────────────────────────────────────────────────────
def test_create_requires_auth(client):
    r = client.post("/api/posts", json={"title": "T", "content": "C"})
    assert r.status_code == 401


def test_pending_user_cannot_create(client, make_user, auth_headers):
    pending = make_user(role="pending")
    r = client.post(
        "/api/posts",
        headers=auth_headers(pending),
        json={"title": "T", "content": "C"},
    )
    assert r.status_code == 403  # require_writer


def test_writer_creates_public_post(client, make_user, auth_headers):
    writer = make_user(role="writer")
    post = _create_post(client, auth_headers(writer))
    assert post["owner_id"] == writer.id
    assert post["visibility"] == "public"


# ── public: 누구나 ─────────────────────────────────────────────────────────
def test_public_visible_to_anonymous(client, make_user, auth_headers):
    writer = make_user(role="writer")
    post = _create_post(client, auth_headers(writer), visibility="public")
    assert client.get(f"/api/posts/{post['id']}").status_code == 200


# ── private: 본인·admin만, 나머지는 존재를 숨김(404) ────────────────────────
def test_private_hidden_from_anonymous(client, make_user, auth_headers):
    writer = make_user(role="writer")
    post = _create_post(client, auth_headers(writer), visibility="private")
    assert client.get(f"/api/posts/{post['id']}").status_code == 404


def test_private_hidden_from_other_user(client, make_user, auth_headers):
    owner = make_user(role="writer")
    other = make_user(role="writer")
    post = _create_post(client, auth_headers(owner), visibility="private")
    r = client.get(f"/api/posts/{post['id']}", headers=auth_headers(other))
    assert r.status_code == 404


def test_private_visible_to_owner(client, make_user, auth_headers):
    owner = make_user(role="writer")
    post = _create_post(client, auth_headers(owner), visibility="private")
    r = client.get(f"/api/posts/{post['id']}", headers=auth_headers(owner))
    assert r.status_code == 200


def test_private_visible_to_admin(client, make_user, auth_headers):
    owner = make_user(role="writer")
    admin = make_user(role="admin")
    post = _create_post(client, auth_headers(owner), visibility="private")
    r = client.get(f"/api/posts/{post['id']}", headers=auth_headers(admin))
    assert r.status_code == 200


# ── subscribers: 구독하면 열림 ─────────────────────────────────────────────
def test_subscribers_only_visible_only_after_approval(
    client, make_user, auth_headers
):
    author = make_user(role="writer")
    reader = make_user(role="writer")
    post = _create_post(client, auth_headers(author), visibility="subscribers")

    # 구독(신청) 전: 숨김
    assert client.get(f"/api/posts/{post['id']}", headers=auth_headers(reader)).status_code == 404

    # 구독 신청 → 아직 '대기'라 열람 안 됨
    sub = client.post(
        "/api/subscriptions", headers=auth_headers(reader), json={"author_id": author.id}
    )
    assert sub.status_code == 201
    assert sub.json()["approved"] is False
    assert client.get(f"/api/posts/{post['id']}", headers=auth_headers(reader)).status_code == 404

    # 글쓴이가 승인 → 이제 열림
    approve = client.post(
        f"/api/subscriptions/requests/{reader.id}/approve", headers=auth_headers(author)
    )
    assert approve.status_code == 204
    assert client.get(f"/api/posts/{post['id']}", headers=auth_headers(reader)).status_code == 200


# ── 수정/삭제: 소유자만 ────────────────────────────────────────────────────
def test_non_owner_cannot_update(client, make_user, auth_headers):
    owner = make_user(role="writer")
    other = make_user(role="writer")
    post = _create_post(client, auth_headers(owner))
    r = client.put(
        f"/api/posts/{post['id']}",
        headers=auth_headers(other),
        json={"title": "hacked", "content": "C", "visibility": "public"},
    )
    assert r.status_code == 403


def test_non_owner_cannot_delete(client, make_user, auth_headers):
    owner = make_user(role="writer")
    other = make_user(role="writer")
    post = _create_post(client, auth_headers(owner))
    r = client.delete(f"/api/posts/{post['id']}", headers=auth_headers(other))
    assert r.status_code == 403


def test_owner_can_update_and_delete(client, make_user, auth_headers):
    owner = make_user(role="writer")
    post = _create_post(client, auth_headers(owner))

    upd = client.put(
        f"/api/posts/{post['id']}",
        headers=auth_headers(owner),
        json={"title": "new title", "content": "C", "visibility": "public"},
    )
    assert upd.status_code == 200
    assert upd.json()["title"] == "new title"

    dele = client.delete(f"/api/posts/{post['id']}", headers=auth_headers(owner))
    assert dele.status_code == 204
    # 삭제 후 조회 불가
    assert client.get(f"/api/posts/{post['id']}").status_code == 404


# ── 커버 이미지 URL 검증 ─────────────────────────────────────────────────────
# CSP가 img-src를 https로 제한하므로 http 커버는 브라우저가 차단해 '조용히' 안 보인다.
# 저장 시점에 막아 원인 모를 실패를 없앤다.
@pytest.mark.parametrize(
    "cover,expect",
    [
        ("https://cdn.example.com/a.png", 201),  # 외부 https
        ("/uploads/abc.png", 201),  # same-origin 상대경로
        ("http://localhost:8000/uploads/a.png", 201),  # 로컬 개발 업로더
        ("", 201),  # 빈 값 = 미지정
        ("http://evil.example.com/a.png", 422),  # 평문 http
        ("//evil.example.com/a.png", 422),  # 프로토콜 상대 = 외부 호스트
        ("javascript:alert(1)", 422),
        ("data:image/svg+xml,<svg onload=alert(1)>", 422),
    ],
)
def test_cover_image_scheme(client, make_user, auth_headers, cover, expect):
    user = make_user(role="writer")
    r = client.post(
        "/api/posts",
        headers=auth_headers(user),
        json={"title": "T", "content": "C", "cover_image": cover},
    )
    assert r.status_code == expect, r.text

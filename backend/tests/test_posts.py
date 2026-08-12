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


# ── 연재 네비 ──────────────────────────────────────────────────────────────
# SERIES_ITEMS_MAX(=100)를 넘어가는 연재. 여기 있던 주석은 "이 글이 목록에 없을 수는
# 없다"였는데, 가시성만 보고 바로 위의 `.limit()`을 안 본 서술이라 거짓이었다.
# 상한 밖 글의 상세를 열면 `ids.index()`가 ValueError를 던져 500 text/plain이 났다.
# 100편을 실제로 만들면 느리므로 상한을 3으로 낮춰 같은 경계를 만든다.
def test_series_nav_beyond_limit_returns_null_not_500(
    client, make_user, auth_headers, monkeypatch
):
    from app.routers import posts as posts_router

    monkeypatch.setattr(posts_router, "SERIES_ITEMS_MAX", 3)
    user = make_user(role="writer")
    headers = auth_headers(user)
    # series는 생성 시점에 넣는다 — `PATCH /api/posts/{id}`는 존재하지 않는다
    # (PUT 전체수정과 PATCH /{id}/visibility 둘뿐). 처음엔 그걸 몰라 405가 조용히
    # 무시되면서 series가 안 붙어, 상한 안쪽 글까지 null이 나왔다.
    ids = []
    for i in range(4):
        r = client.post(
            "/api/posts",
            headers=headers,
            json={"title": f"S{i}", "content": "C", "series": "연재"},
        )
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])

    # 상한 안(1편)은 네비가 나온다
    r_in = client.get(f"/api/posts/{ids[0]}/series")
    assert r_in.status_code == 200, r_in.text
    assert r_in.json()["index"] == 1

    # 상한 밖(4편째)은 500이 아니라 null — 네비를 못 그리는 게 글이 안 열리는 것보다 낫다
    r_out = client.get(f"/api/posts/{ids[3]}/series")
    assert r_out.status_code == 200, r_out.text
    assert r_out.json() is None

    # 글 자체는 정상적으로 열려야 한다(이게 500의 실제 피해였다)
    assert client.get(f"/api/posts/{ids[3]}").status_code == 200


def test_nul_byte_in_query_is_422_not_500(client):
    """NUL 바이트가 든 검색어는 **인증 없이 500을 만들 수 있었다.**

    psycopg2가 `\\x00`이 든 문자열에서 DB에 닿기도 전에 ValueError를 던지는데 핸들러가
    없어 `500 text/plain`이 나갔다(2026-08-12 동적 분석에서 실제 HTTP로 재현).
    프론트는 JSON을 기대하므로 그 응답은 파싱조차 못 한다.

    `q=%00` 단독은 min_length=2에 걸리지만 **`a%00b`는 길이 검사를 통과한다** — 그게
    이 테스트가 두 모양을 다 보는 이유다.
    """
    for params in ({"q": "a\x00b"}, {"tag": "\x00"}, {"tag": "a\x00b"}):
        r = client.get("/api/posts", params=params)
        assert r.status_code == 422, f"{params} → {r.status_code} {r.text[:120]}"
        # 프론트가 파싱할 수 있는 모양이어야 한다(500 text/plain이 문제였다)
        assert r.headers["content-type"].startswith("application/json")


def test_tag_has_length_limit_like_q(client):
    """`q`엔 max_length=100이 있는데 **바로 옆 `tag`엔 아무 제약이 없었다.**

    6,000자 태그가 200으로 인덱스 조회까지 갔다(2026-08-12 실측).
    '고친 자리 옆의 안 쓸린 입구'라 같은 검사에 함께 둔다.
    """
    assert client.get("/api/posts", params={"tag": "x" * 6000}).status_code == 422
    assert client.get("/api/posts", params={"tag": "x" * 50}).status_code == 200

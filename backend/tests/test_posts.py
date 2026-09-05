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


# ── 2026-08-12 검사: 무인증으로 500을 만들 수 있던 다섯 갈래 ───────────────────
# 이 저장소에서 500은 "핸들러가 없다"는 뜻이고, 응답이 text/plain이면 프론트가 파싱조차
# 못 한다. 아래는 전부 실제 HTTP로 재현된 것들이라 회귀하면 조용히 같은 상태로 돌아간다.


def test_infinity_in_json_body_does_not_500(client):
    """`Infinity`/`NaN`이 들어오면 **422를 만들다가** 터졌다.

    FastAPI 기본 핸들러가 문제의 입력을 `detail[].input`에 그대로 담는데 starlette은
    `allow_nan=False`로 직렬화한다 → ValueError → 500 text/plain.
    **숫자 필드가 아니어도 난다**(문자열 필드에 넣어도 같다) → JSON 본문을 받는 모든
    POST/PUT/PATCH가 해당됐다. 무인증 로그인으로도 가능했다.
    """
    for body in (b'{"email":1e999,"password":"x"}', b'{"email":-1e999,"password":"x"}'):
        r = client.post("/api/auth/login", content=body, headers={"content-type": "application/json"})
        assert r.status_code == 422, f"{body!r} → {r.status_code} {r.text[:120]}"
        assert r.headers["content-type"].startswith("application/json")
        # 입력값을 되돌려주지 않는다(그게 터진 원인이자, 반사하지 않는 게 낫다)
        assert "input" not in r.text


def test_infinity_does_not_bypass_rate_limit(client):
    """**리밋 우회가 진짜 피해였다.** 검증은 slowapi 데코레이터보다 먼저 도는 계층이라,
    터지는 입력을 보내면 429가 영원히 안 뜨고 500만 무제한으로 나왔다(실측 25연발 500×25,
    정상 값 대조군은 401×10 → 429×15). 이제는 422로 끝나므로 500이 0건이어야 한다."""
    codes = [
        client.post(
            "/api/auth/login",
            content=b'{"email":1e999,"password":"x"}',
            headers={"content-type": "application/json"},
        ).status_code
        for _ in range(25)
    ]
    assert 500 not in codes, f"500이 {codes.count(500)}건 — 핸들러가 다시 빠졌다"


def test_lone_surrogate_does_not_500(client):
    """고아 서로게이트(`\\ud800`)는 두 갈래로 500을 만들었다 —
    422를 UTF-8로 인코딩하다가, 그리고 검증을 통과해 DB에 닿아서. 둘 다 무인증 경로였다."""
    r = client.post(
        "/api/posts/1/comments",
        content=b'{"author":"a","content":"x\\ud800y"}',
        headers={"content-type": "application/json"},
    )
    assert r.status_code != 500, r.text[:200]
    assert r.headers["content-type"].startswith("application/json")


def test_nul_byte_in_write_paths_does_not_500(client, make_user, auth_headers):
    """오전에 `list_posts`의 q·tag만 막았는데 **쓰기 경로엔 그대로 남아 있었다.**
    라우터마다가 아니라 DataError 핸들러로 받는다 — 필드마다 막으면 필드가 늘 때 또 샌다."""
    writer = make_user(role="writer")
    r = client.post(
        "/api/posts",
        headers={**auth_headers(writer), "content-type": "application/json"},
        content=b'{"title":"a\\u0000b","content":"c","tags":[],"visibility":"public"}',
    )
    assert r.status_code != 500, r.text[:200]
    assert r.headers["content-type"].startswith("application/json")


def test_offset_has_upper_bound_like_limit(client):
    """`limit`엔 le=50이 있는데 `offset`엔 상한이 없었다 → `2**63`에서 bigint 초과로
    **무인증 500**. 임계값이 정확히 2^63인 것도 실측됐다."""
    assert client.get("/api/posts", params={"offset": 2**63}).status_code == 422
    assert client.get("/api/posts", params={"offset": 0}).status_code == 200


def test_nul_byte_blocked_in_comments_too(client, make_user, auth_headers):
    """**한 라우터가 아니라 스키마 기반 클래스에서 막는다**는 걸 잠근다.

    오전에 필드 단위로 막았다가 다섯 라우터를 놓쳤다. 익명 댓글은 그중 하나이자
    **무인증**이라 가장 넓은 입구였다. 여기가 막히면 같은 기반을 쓰는 나머지도 막힌다.
    """
    writer = make_user(role="writer")
    post = _create_post(client, auth_headers(writer))
    r = client.post(
        f"/api/posts/{post['id']}/comments",
        content=b'{"author":"a","content":"x\\u0000y"}',
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 422, f"{r.status_code} {r.text[:150]}"
    assert r.headers["content-type"].startswith("application/json")


def test_같은_시각_글도_순서가_흔들리지_않는다(client, make_user, auth_headers):
    """정렬에 동점 처리가 없어서 나던 흔들림을 잠근다(2026-08-19).

    **Postgres의 `now()`는 한 트랜잭션 안에서 고정이다.** 그리고 이 저장소의 테스트는
    하나를 트랜잭션 하나로 묶는다(conftest). 그래서 한 테스트에서 만든 글들은
    `created_at`이 **전부 같다** — 그 상태에서 `ORDER BY created_at`만 있으면 순서가
    DB 마음이고, 실행마다 달라진다.

    실제로 `test_series_nav_beyond_limit_returns_null_not_500`이 그것 때문에 전체
    실행에서만 가끔 빨간불이었다(단독 실행·파일 단위로는 통과). CI가 흔들리면
    '빨간불이 났다'는 신호 자체를 못 믿게 된다 — 그게 이 테스트가 막는 것이다.

    운영에도 같은 일이 있다. 같은 초에 두 편을 올리면 목록이 요청마다 뒤집힐 수 있고,
    목록은 limit/offset 페이지네이션이라 그 경계에서 **같은 글이 두 페이지에 나오거나
    한 글이 건너뛰어진다.**
    """
    user = make_user(role="writer")
    headers = auth_headers(user)
    ids = []
    for i in range(6):
        r = client.post(
            "/api/posts", headers=headers, json={"title": f"T{i}", "content": "C", "series": "연재"}
        )
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])

    # 전제 확인: 정말로 created_at이 같은가. 같지 않으면 이 테스트는 아무것도 안 잠근다.
    stamps = {client.get(f"/api/posts/{i}").json()["created_at"] for i in ids}
    assert len(stamps) == 1, f"created_at이 갈렸다({len(stamps)}종) — 이 테스트의 전제가 깨졌다"

    # ① 목록: 여러 번 불러도 같은 순서여야 한다
    def page(offset):
        r = client.get(f"/api/posts?limit=3&offset={offset}")
        assert r.status_code == 200, r.text
        return [p["id"] for p in r.json()["items"]]

    assert page(0) == page(0)
    # ② 페이지가 겹치거나 빠지지 않는다 — 동점 처리가 없으면 여기서 깨진다
    first, second = page(0), page(3)
    assert not set(first) & set(second), "같은 글이 두 페이지에 나온다"
    assert set(first) | set(second) >= set(ids), "건너뛴 글이 있다"

    # ③ 연재: 순서가 고정이고, 사람이 기대하는 대로 먼저 만든 글이 앞
    nav = client.get(f"/api/posts/{ids[0]}/series").json()
    assert [it["id"] for it in nav["items"]] == ids
    assert nav["index"] == 1


# ── 공백만 든 검색어 (09-04 검사 BE-5) ───────────────────────────────────────
#
# `q` 의 min_length=2 는 **strip 전** 길이를 세는데 필터는 `q.strip()` 을 썼다.
# 그래서 두 칸짜리 `?q=%20%20` 이 검증을 통과하고 패턴이 `%%` 가 되어 title·content
# ILIKE 가 전 행에 걸렸다 — `_like_escape` 주석이 막겠다고 적어둔 '와일드카드만 보내
# 인덱스를 못 타는 무거운 스캔'이 공백으로 그대로 재현된 것이다. 결과는 전체 목록이라
# 화면상 아무 이상이 없어서 더 조용했다(무인증 60/분).


def test_공백만_든_검색어는_검색으로_치지_않는다(client, make_user, auth_headers):
    h = auth_headers(make_user(role="writer"))
    _create_post(client, h, title="AWS 비용", content="본문")
    _create_post(client, h, title="다른 글", content="본문")

    plain = client.get("/api/posts").json()
    spaces = client.get("/api/posts?q=%20%20")
    assert spaces.status_code == 200
    # 필터가 아예 안 걸린 것과 같아야 한다(= 전체 목록). '%%' 로 도는 것과 결과는 같지만
    # 여기서 잠그는 건 결과가 아니라 **그 요청이 검색으로 취급되지 않는다**는 것이다.
    assert spaces.json()["total"] == plain["total"] == 2


def test_앞뒤_공백은_털고_검색한다(client, make_user, auth_headers):
    h = auth_headers(make_user(role="writer"))
    _create_post(client, h, title="AWS 비용", content="본문")
    _create_post(client, h, title="다른 글", content="본문")

    r = client.get("/api/posts?q=%20AWS%20")
    assert r.status_code == 200
    assert r.json()["total"] == 1

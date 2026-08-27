"""목록·상세 응답이 글쓴이와 연재를 싣는지, 그리고 연재로 거를 수 있는지.

**왜 이 파일이 생겼나 (2026-08-27)** — `PostSummary`가 담는 글쓴이 정보가 `owner_id`
숫자뿐이라, 다중 글쓴이 플랫폼인데 목록도 상세도 누가 쓴 글인지 표시할 수 없었다.
그래서 `/@handle` 화면·필터·스킨이 전부 만들어져 있는데도 앱 안에서 거기로 가는 링크가
자기 자신 주소 둘뿐이었다. 연재도 같은 모양이었다 — 컬럼·인덱스·이전/다음 편 API가
다 있는데 **그 연재의 글 하나를 이미 우연히 연 사람에게만** 보였다.

여기서 잠그는 것은 두 가지다: 값이 실제로 실리는가, 그리고 **차단된 사람의 handle이
안 나가는가.** 후자가 회귀하면 화면이 빈 페이지로 가는 링크를 그린다.
"""


def _create_post(client, headers, *, title="T", content="C", series=None, visibility="public"):
    r = client.post(
        "/api/posts",
        json={
            "title": title,
            "content": content,
            "series": series,
            "visibility": visibility,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _set_handle(client, headers, handle):
    r = client.patch("/api/auth/me/handle", json={"handle": handle}, headers=headers)
    assert r.status_code == 200, r.text


def test_list_carries_author_name_and_handle(client, make_user, auth_headers):
    w = make_user(role="writer", display_name="유노")
    h = auth_headers(w)
    _set_handle(client, h, "yuno")
    _create_post(client, h)

    item = client.get("/api/posts").json()["items"][0]
    assert item["author_name"] == "유노"
    assert item["author_handle"] == "yuno"


def test_detail_carries_author(client, make_user, auth_headers):
    w = make_user(role="writer", display_name="유노")
    h = auth_headers(w)
    _set_handle(client, h, "yuno")
    post = _create_post(client, h)

    body = client.get(f"/api/posts/{post['id']}").json()
    assert body["author_name"] == "유노"
    assert body["author_handle"] == "yuno"


def test_banned_author_handle_is_withheld(client, make_user, auth_headers, db):
    """차단된 사람의 handle은 목록에 안 실린다.

    `/api/posts?author=`는 PUBLIC_BLOG_ROLES 조건을 걸어 차단된 사람의 목록을 비운다
    (2026-08-19 보안검사: "회수가 절반만 듣는다"). 그런데 목록이 handle을 그대로
    실어 보내면 화면은 **빈 페이지로 가는 링크**를 그린다. 이름은 남긴다 — 누가
    썼는지는 회수 대상이 아니고 댓글·구독 목록에도 이미 나온다.
    """
    w = make_user(role="writer", display_name="유노")
    h = auth_headers(w)
    _set_handle(client, h, "yuno")
    _create_post(client, h)

    w.role = "banned"
    db.commit()

    item = client.get("/api/posts").json()["items"][0]
    assert item["author_name"] == "유노"
    assert item["author_handle"] is None


def test_anonymous_post_has_no_author(client, make_user, auth_headers):
    """handle을 안 정한 사람의 글은 이름만 나가고 링크는 안 생긴다."""
    w = make_user(role="writer", display_name=None)
    _create_post(client, auth_headers(w))
    item = client.get("/api/posts").json()["items"][0]
    assert item["author_name"] is None
    assert item["author_handle"] is None


def test_list_carries_series(client, make_user, auth_headers):
    w = make_user(role="writer")
    _create_post(client, auth_headers(w), series="블로그 만들기")
    item = client.get("/api/posts").json()["items"][0]
    assert item["series"] == "블로그 만들기"


def test_series_filter_is_exact_not_prefix(client, make_user, auth_headers):
    """부분 일치면 안 된다.

    '블로그 만들기'로 걸렀는데 '블로그 만들기 2'가 같이 오면, 연재 뱃지를 누른 사람이
    다른 연재의 글을 보게 된다.
    """
    h = auth_headers(make_user(role="writer"))
    _create_post(client, h, title="A", series="블로그 만들기")
    _create_post(client, h, title="B", series="블로그 만들기 2")

    items = client.get("/api/posts", params={"series": "블로그 만들기"}).json()["items"]
    assert [i["title"] for i in items] == ["A"]


def test_series_filter_unknown_gives_empty_list_not_404(client, make_user, auth_headers):
    """없는 연재는 404가 아니라 빈 목록이다(author 필터와 같은 규칙)."""
    _create_post(client, auth_headers(make_user(role="writer")), series="있는연재")
    r = client.get("/api/posts", params={"series": "없는연재"})
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_series_filter_rejects_nul(client, make_user, auth_headers):
    """NUL 가드에 series가 들어가 있는가.

    이 함수의 주석이 "손으로 적는 목록이라 파라미터가 늘 때마다 샌다"를 이미 두 번
    적어뒀고(q↔tag, 그다음 author), 실제로 세 번 났다. 네 번째를 여기서 잠근다.
    psycopg2는 NUL을 만나면 DB에 닿기도 전에 던지고, 핸들러가 없으면 무인증 500이다.
    """
    r = client.get("/api/posts", params={"series": "a\x00b"})
    assert r.status_code == 422


def test_meta_aggregates_series(client, make_user, auth_headers):
    h = auth_headers(make_user(role="writer"))
    _create_post(client, h, title="A", series="연재갑")
    _create_post(client, h, title="B", series="연재갑")
    _create_post(client, h, title="C", series="연재을")
    _create_post(client, h, title="D")  # 연재 없음 — 집계에 안 들어간다

    series = client.get("/api/posts/meta").json()["series"]
    counts = {s["tag"]: s["count"] for s in series}
    assert counts == {"연재갑": 2, "연재을": 1}


def test_meta_series_respects_visibility(client, make_user, auth_headers):
    """비공개 글이 연재 집계에 새면 안 된다.

    집계는 무인증으로도 불린다. 여기서 새면 '있는 줄도 몰랐던 연재'의 존재와 편수가
    드러난다 — 목록 필터에는 공개범위 조건이 걸려 있는데 집계만 빠지는 모양이다.
    """
    h = auth_headers(make_user(role="writer"))
    _create_post(client, h, title="P", series="비밀연재", visibility="private")
    series = client.get("/api/posts/meta").json()["series"]
    assert [s for s in series if s["tag"] == "비밀연재"] == []

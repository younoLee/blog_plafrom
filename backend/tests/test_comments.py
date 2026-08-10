"""댓글: 작성·목록. 로그인 시 작성자명은 이메일 로컬파트로 고정, 익명은 자유 입력."""


def _public_post(client, headers):
    r = client.post(
        "/api/posts",
        headers=headers,
        json={"title": "T", "content": "C", "visibility": "public"},
    )
    assert r.status_code == 201
    return r.json()["id"]


def test_anonymous_comment_uses_given_author(client, make_user, auth_headers):
    writer = make_user(role="writer")
    pid = _public_post(client, auth_headers(writer))

    r = client.post(
        f"/api/posts/{pid}/comments",
        json={"author": "익명이", "content": "좋은 글이네요"},
    )
    assert r.status_code == 201
    assert r.json()["author"] == "익명이"
    assert r.json()["is_member"] is False

    lst = client.get(f"/api/posts/{pid}/comments")
    assert lst.status_code == 200
    assert len(lst.json()) == 1


def test_logged_in_comment_author_from_display_name(client, make_user, auth_headers):
    """로그인 사용자의 작성자명은 서버가 display_name으로 덮어쓴다.

    **이메일에서 유도하지 않는다.** 2026-08-10 보안검사 전까지는 email.split("@")[0]이었고,
    그 값이 공개 글의 댓글 목록으로 영구히 나갔다(admin은 단 하나이고 발신 도메인이
    공개 제공자라 로컬파트만 알면 주소가 완성된다).
    """
    writer = make_user(role="writer", email="reader@test.com", display_name="읽는이")
    pid = _public_post(client, auth_headers(writer))

    r = client.post(
        f"/api/posts/{pid}/comments",
        headers=auth_headers(writer),
        # author를 보내도 로그인 사용자는 서버 값으로 덮어씀
        json={"author": "무시됨", "content": "내 댓글"},
    )
    assert r.status_code == 201
    assert r.json()["author"] == "읽는이"
    assert "reader" not in r.json()["author"]  # 이메일 로컬파트가 새지 않는다
    assert r.json()["is_member"] is True


def test_logged_in_comment_without_display_name_falls_back(client, make_user, auth_headers):
    """display_name이 없으면 '회원'으로 뭉갠다 — **이메일로 되돌아가지 않는다.**"""
    writer = make_user(role="writer", email="nodisplay@test.com")
    pid = _public_post(client, auth_headers(writer))
    r = client.post(
        f"/api/posts/{pid}/comments",
        headers=auth_headers(writer),
        json={"author": "무시됨", "content": "x"},
    )
    assert r.status_code == 201
    assert r.json()["author"] == "회원"
    assert "nodisplay" not in r.json()["author"]


def test_anonymous_cannot_impersonate_member(client, make_user, auth_headers):
    """익명이 회원과 **똑같은 이름**을 써도 회원으로 표시되지 않는다.

    author 문자열을 일부러 일치시킨다 — 이 테스트가 지키는 건 '이름이 다르다'가 아니라
    '이름이 같아도 구분된다'이기 때문이다. 2026-08-10에 무인증으로 관리자 사칭 댓글을
    실제로 달아 재현했고(201, 목록에서 구분 불가), 그때 응답에는 가를 필드가 없었다.

    이름을 막는 쪽으로 고치지 않은 이유도 여기 적어둔다: 동형문자·제로폭 공백으로
    우회되고, 무엇보다 "그 이름은 계정이다"를 400으로 알려주면 무인증 계정 열거
    오라클이 된다 — 그래서 이름은 그대로 두고 사실(user_id)을 따로 기록한다.
    """
    member = make_user(role="writer", display_name="주인장")
    pid = _public_post(client, auth_headers(member))

    r = client.post(
        f"/api/posts/{pid}/comments",
        json={"author": "주인장", "content": "사칭 시도"},  # 로그인 없이 같은 이름
    )
    assert r.status_code == 201
    assert r.json()["author"] == "주인장"      # 이름은 막지 않는다(의도)
    assert r.json()["is_member"] is False      # 그러나 회원은 아니다


def test_blog_owner_does_not_leak_email(client, make_user):
    """무인증 /api/blog-owner가 이메일 로컬파트를 주지 않는다.

    2026-08-10 보안검사: 예전엔 admin의 email.split("@")[0]을 그대로 반환했다.
    display_name이 없으면 None이고, 프론트가 폴백 문자열을 쓴다.
    """
    admin = make_user(role="admin", email="secretlocal@test.com")
    r = client.get("/api/blog-owner")
    assert r.status_code == 200
    assert r.json()["id"] == admin.id
    assert r.json()["name"] is None
    assert "secretlocal" not in str(r.json())


def test_comment_on_private_post_hidden(client, make_user, auth_headers):
    owner = make_user(role="writer")
    r = client.post(
        "/api/posts",
        headers=auth_headers(owner),
        json={"title": "T", "content": "C", "visibility": "private"},
    )
    pid = r.json()["id"]
    # 볼 수 없는 글의 댓글 목록도 404 (글 존재 자체를 숨김)
    assert client.get(f"/api/posts/{pid}/comments").status_code == 404

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

    lst = client.get(f"/api/posts/{pid}/comments")
    assert lst.status_code == 200
    assert len(lst.json()) == 1


def test_logged_in_comment_author_from_email(client, make_user, auth_headers):
    writer = make_user(role="writer", email="reader@test.com")
    pid = _public_post(client, auth_headers(writer))

    r = client.post(
        f"/api/posts/{pid}/comments",
        headers=auth_headers(writer),
        # author를 보내도 로그인 사용자는 이메일 로컬파트로 덮어씀
        json={"author": "무시됨", "content": "내 댓글"},
    )
    assert r.status_code == 201
    assert r.json()["author"] == "reader"


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

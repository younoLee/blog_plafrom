"""계정마다 자기 블로그(`/@handle`) — 주소·글 목록·스킨이 사람별로 갈리는지 잠근다.

2026-08-18에 생겼다. 그전까지 이 사이트는 블로그가 하나(`/blog`)였고 스킨도 주인 것
하나만 나갔다. 이 파일이 지키는 것은 **갈림**이다:

  · 핸들은 중복될 수 없고 대소문자로 우회할 수 없다
  · 목록을 `author=`로 거르면 그 사람 글만 나온다
  · 스킨은 저장한 사람의 것이 그 사람 주소에서 나온다 (남의 블로그에 안 샌다)

마지막 항목이 이 변경의 진짜 위험이다. 전에는 PUT이 **주인 행**에 썼는데, 그대로 두고
권한만 넓혔으면 글쓴이가 저장한 CSS가 주인 블로그에 나갔을 것이다.
"""

import pytest


def test_핸들을_정하면_응답에_담긴다(client, make_user, auth_headers):
    u = make_user(role="writer")
    r = client.patch("/api/auth/me/handle", json={"handle": "yuno"}, headers=auth_headers(u))
    assert r.status_code == 200
    assert r.json()["handle"] == "yuno"


def test_대문자로_넣어도_소문자로_저장된다(client, make_user, auth_headers):
    u = make_user(role="writer")
    r = client.patch("/api/auth/me/handle", json={"handle": "YuNo"}, headers=auth_headers(u))
    assert r.json()["handle"] == "yuno"


def test_빈_값이면_주소를_없앤다(client, make_user, auth_headers):
    u = make_user(role="writer")
    h = auth_headers(u)
    client.patch("/api/auth/me/handle", json={"handle": "yuno"}, headers=h)
    r = client.patch("/api/auth/me/handle", json={"handle": "  "}, headers=h)
    assert r.status_code == 200
    assert r.json()["handle"] is None
    # 주소를 없앴으면 그 블로그는 더 이상 없다
    assert client.get("/api/authors/yuno").status_code == 404


@pytest.mark.parametrize(
    "bad",
    [
        "a",  # 너무 짧다
        "유노",  # 한글 — 주소에서 인코딩 문제를 만든다
        "yu no",  # 공백
        "-yuno",  # 하이픈으로 시작
        "yuno-",  # 하이픈으로 끝
        "yu.no",  # 점
        "blog",  # 예약어 — 나중에 진짜 /blog 경로를 못 만든다
        "settings",  # 예약어
    ],
)
def test_주소로_못_쓰는_값은_거부된다(client, make_user, auth_headers, bad):
    u = make_user(role="writer")
    r = client.patch("/api/auth/me/handle", json={"handle": bad}, headers=auth_headers(u))
    assert r.status_code == 422, f"{bad!r} 가 통과했다"


def test_중복은_409다(client, make_user, auth_headers):
    a, b = make_user(role="writer"), make_user(role="writer")
    assert client.patch("/api/auth/me/handle", json={"handle": "yuno"}, headers=auth_headers(a)).status_code == 200
    r = client.patch("/api/auth/me/handle", json={"handle": "yuno"}, headers=auth_headers(b))
    assert r.status_code == 409


def test_대소문자만_다른_중복도_막힌다(client, make_user, auth_headers):
    # lower(handle) 유니크 인덱스가 없으면 여기가 통과하고, 그 순간부터
    # /@Yuno 와 /@yuno 중 어느 쪽이 열리는지가 행 순서에 달린다.
    a, b = make_user(role="writer"), make_user(role="writer")
    client.patch("/api/auth/me/handle", json={"handle": "yuno"}, headers=auth_headers(a))
    r = client.patch("/api/auth/me/handle", json={"handle": "YUNO"}, headers=auth_headers(b))
    assert r.status_code in (409, 422)


def test_없는_핸들은_404_있으면_공개정보만(client, make_user, auth_headers):
    assert client.get("/api/authors/nobody").status_code == 404
    u = make_user(role="writer", display_name="유노")
    client.patch("/api/auth/me/handle", json={"handle": "yuno"}, headers=auth_headers(u))
    body = client.get("/api/authors/yuno").json()
    assert body == {"handle": "yuno", "name": "유노", "posts": 0}
    # 이메일은 어떤 경우에도 안 나간다
    assert u.email not in str(body)


def test_표시명이_없으면_핸들을_이름으로_쓴다(client, make_user, auth_headers):
    # 이메일로 되돌아가는 폴백이 없어야 한다(2026-08-10에 끊은 경로다).
    u = make_user(role="writer", display_name=None)
    client.patch("/api/auth/me/handle", json={"handle": "yuno"}, headers=auth_headers(u))
    body = client.get("/api/authors/yuno").json()
    assert body["name"] == "yuno"
    assert "@" not in body["name"]


def test_목록을_글쓴이로_거른다(client, make_user, auth_headers):
    a, b = make_user(role="writer"), make_user(role="writer")
    client.patch("/api/auth/me/handle", json={"handle": "aaa"}, headers=auth_headers(a))
    client.patch("/api/auth/me/handle", json={"handle": "bbb"}, headers=auth_headers(b))
    client.post("/api/posts", json={"title": "A의 글", "content": "본문"}, headers=auth_headers(a))
    client.post("/api/posts", json={"title": "B의 글", "content": "본문"}, headers=auth_headers(b))

    def titles(q: str) -> list[str]:
        return [p["title"] for p in client.get(q).json()["items"]]

    assert titles("/api/posts?author=aaa") == ["A의 글"]
    assert titles("/api/posts?author=AAA") == ["A의 글"]  # 대소문자 무시
    assert set(titles("/api/posts")) == {"A의 글", "B의 글"}  # 전체 모아보기
    # 없는 사람은 빈 목록이다(404가 아니다 — 목록은 '없음'을 표현할 수 있다)
    assert client.get("/api/posts?author=nobody").json()["items"] == []


def test_스킨은_저장한_사람_주소에서_나온다(client, make_user, auth_headers):
    """이 변경의 진짜 위험. 전에는 PUT이 주인 행에 썼다."""
    admin = make_user(role="admin")
    writer = make_user(role="writer")
    client.patch("/api/auth/me/handle", json={"handle": "writer1"}, headers=auth_headers(writer))

    client.put("/api/skin", json={"custom_css": ":root{--color-accent:red}"}, headers=auth_headers(admin))
    client.put("/api/skin", json={"custom_css": ":root{--color-accent:blue}"}, headers=auth_headers(writer))

    # 사이트 스킨(핸들 없음) = 주인 것. 글쓴이가 저장한 값이 여기 새면 안 된다.
    assert "red" in client.get("/api/skin").json()["css"]
    assert "blue" not in client.get("/api/skin").json()["css"]
    # 그 사람 주소 = 그 사람 것
    assert "blue" in client.get("/api/skin?handle=writer1").json()["css"]


def test_글쓴이도_스킨을_저장할_수_있다(client, make_user, auth_headers):
    # 08-18 오전엔 admin만 가능했다. 계정별 블로그가 생기면서 넓혔다.
    w = make_user(role="writer")
    r = client.put("/api/skin", json={"custom_css": "body{}"}, headers=auth_headers(w))
    assert r.status_code == 200


def test_승인_대기중인_사람은_못_바꾼다(client, make_user, auth_headers):
    p = make_user(role="pending")
    r = client.put("/api/skin", json={"custom_css": "body{}"}, headers=auth_headers(p))
    assert r.status_code == 403


def test_없는_핸들의_스킨은_빈_값이다(client, make_user):
    # 404가 아니다 — 스킨은 장식이라 화면이 이것 때문에 실패 경로를 타면 손해가 더 크다.
    make_user(role="admin")
    assert client.get("/api/skin?handle=nobody").json() == {"css": ""}

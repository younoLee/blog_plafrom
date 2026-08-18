"""블로그 스킨(users.custom_css) — 공개 조회와 주인만의 저장.

이 파일이 지키려는 것은 두 가지다.
  1. 스킨은 **무인증으로 읽힌다**. 방문자가 못 받으면 화면이 기본색으로 그려진다.
  2. 스킨은 **아무나 못 쓴다**. 방문자 브라우저에서 실행될 스타일이기 때문이다.
그 사이에 CSS를 벗어나는 문자열(`</style`·`@import` 등)을 입구에서 막는 검사가 있다.
"""

import pytest


def test_스킨이_없으면_빈_문자열이지_에러가_아니다(client, make_user):
    make_user(role="admin")
    r = client.get("/api/skin")
    assert r.status_code == 200
    # 스킨과 '내 문장'이 한 응답에 함께 온다(routers/skin.py 상단 주석 참고).
    # 여기서 css만 본다 — 문장 쪽은 test_slots.py가 잠근다.
    assert r.json()["css"] == ""


def test_주인이_없어도_200이다(client):
    # admin 계정이 아직 없는 새 설치. 화면이 뜨는 게 더 중요하다.
    r = client.get("/api/skin")
    assert r.status_code == 200
    assert r.json()["css"] == ""


def test_주인이_저장하면_무인증으로_읽힌다(client, make_user, auth_headers):
    admin = make_user(role="admin")
    css = ":root { --color-accent: #20c997 }"
    r = client.put("/api/skin", json={"custom_css": css}, headers=auth_headers(admin))
    assert r.status_code == 200

    # 로그인하지 않은 방문자가 그대로 받는다
    assert client.get("/api/skin").json()["css"] == css


def test_빈_값이면_기본_스킨으로_되돌아간다(client, make_user, auth_headers):
    admin = make_user(role="admin")
    h = auth_headers(admin)
    client.put("/api/skin", json={"custom_css": ":root{--color-accent:red}"}, headers=h)

    r = client.put("/api/skin", json={"custom_css": "   "}, headers=h)
    assert r.status_code == 200
    assert r.json()["css"] == ""
    assert client.get("/api/skin").json()["css"] == ""


def test_글쓴이가_저장해도_사이트_스킨은_안_바뀐다(client, make_user, auth_headers):
    """2026-08-18 오후에 규칙이 바뀐 자리다.

    그전엔 글쓴이가 아예 못 바꿨다(403). 계정별 블로그(`/@handle`)가 생기면서
    자기 것은 바꿀 수 있게 넓혔는데, **그때 저장 대상도 '주인 행'에서 '자기 행'으로**
    같이 바꿔야 했다. 하나만 바꿨으면 글쓴이가 저장한 CSS가 사이트 스킨이 됐을 것이다.
    그래서 여기서 잠근다: 글쓴이가 저장해도 핸들 없는 조회(= 사이트 스킨)는 안 변한다.
    """
    make_user(role="admin")
    writer = make_user(role="writer")
    r = client.put(
        "/api/skin", json={"custom_css": "body{display:none}"}, headers=auth_headers(writer)
    )
    assert r.status_code == 200  # 자기 것은 바꿀 수 있다
    assert client.get("/api/skin").json()["css"] == ""  # 사이트 스킨은 그대로


def test_로그인하지_않으면_못_바꾼다(client, make_user):
    make_user(role="admin")
    r = client.put("/api/skin", json={"custom_css": "body{display:none}"})
    assert r.status_code == 401


@pytest.mark.parametrize(
    "css",
    [
        "</style><script>alert(1)</script>",  # 태그를 닫고 밖으로 나가는 시도
        "</STYLE>",  # 대문자 변형
        "@import url('https://cdn.jsdelivr.net/x.css')",  # 남의 스타일시트를 끌어옴
        "body { background: url(javascript:alert(1)) }",
        "width: expression(alert(1))",  # 옛 IE에서 스크립트가 되던 형태
    ],
)
def test_CSS를_벗어나는_문자열은_거부된다(client, make_user, auth_headers, css):
    admin = make_user(role="admin")
    r = client.put("/api/skin", json={"custom_css": css}, headers=auth_headers(admin))
    assert r.status_code == 422
    # 거부만으로는 부족하다 — 저장이 안 됐는지까지 본다
    assert client.get("/api/skin").json()["css"] == ""


def test_50KB를_넘으면_거부된다(client, make_user, auth_headers):
    admin = make_user(role="admin")
    r = client.put(
        "/api/skin", json={"custom_css": "a" * 50_001}, headers=auth_headers(admin)
    )
    assert r.status_code == 422


def test_평범한_스킨은_통과한다(client, make_user, auth_headers):
    # 위 금지 목록이 정상 CSS를 잡아먹지 않는지 본다. @media·의사요소·주석·url()이
    # 다 살아 있어야 스킨으로 쓸모가 있다.
    admin = make_user(role="admin")
    css = """
    /* velog풍 */
    :root { --color-accent: #20c997; --radius-card: .5rem; --radius-btn: .25rem }
    .dark { --color-accent: #38d9a9 }
    @media (max-width: 640px) { :root { --radius-card: 0 } }
    article::after { content: "읽기"; background: url(/uploads/x.png) }
    """
    r = client.put("/api/skin", json={"custom_css": css}, headers=auth_headers(admin))
    assert r.status_code == 200
    assert "velog" in client.get("/api/skin").json()["css"]

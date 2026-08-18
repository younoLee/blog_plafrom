"""'내 문장'(HTML 슬롯) — 살균기와 API.

이 파일이 지키는 것은 하나다: **사용자가 넣은 HTML이 방문자 브라우저에서 스크립트가
되지 않는다.** 스킨 CSS(test_skin.py)와 나란히 있지만 위험의 크기가 다르다 — CSS는
`<`를 통째로 막아 끝났고, 여기는 `<`가 목적이라 허용 목록으로 다시 쓴다.

공격 사례를 골라 넣은 기준: **막는 목록 방식이었다면 통과했을 것들**이다.
`<script>`만 지우는 코드는 `<img onerror>`를 놓치고, `on*`까지 지우는 코드는
`<a href="javascript:">`를 놓치고, 그것까지 막는 코드는 `jav&#9;ascript:`를 놓친다.
셋 다 실제로 쓰이는 우회다.
"""

import pytest

from app.core.html_slots import SLOT_MAX, sanitize_html, sanitize_slots

# ─────────────────────────────────────────────────────────── 살균기(단위)


@pytest.mark.parametrize(
    "payload",
    [
        "<script>alert(1)</script>",
        "<SCRIPT>alert(1)</SCRIPT>",
        # 안쪽 태그를 지우면 바깥이 완성되는 형태. 문자열 치환 방식이 여기서 샌다.
        "<scr<script>ipt>alert(1)</script>",
        '<img src=x onerror="alert(1)">',
        '<img src=x ONERROR=alert(1)>',
        '<svg onload=alert(1)></svg>',
        '<body onload=alert(1)>',
        '<a href="javascript:alert(1)">클릭</a>',
        '<a href="JaVaScRiPt:alert(1)">클릭</a>',
        # 엔티티로 숨긴 스킴. 브라우저는 탭을 무시하고 실행한다.
        '<a href="jav&#9;ascript:alert(1)">클릭</a>',
        '<a href="&#106;avascript:alert(1)">클릭</a>',
        '<iframe src="https://evil.example"></iframe>',
        '<object data="evil.swf"></object>',
        '<embed src="evil.swf">',
        '<form action="https://evil.example"><input name="pw"></form>',
        '<input onfocus=alert(1) autofocus>',
        # data: URL 안의 SVG는 그 자체가 스크립트를 품는다.
        '<img src="data:image/svg+xml,<svg onload=alert(1)>">',
        '<style>body{display:none}</style>',
        '<link rel="stylesheet" href="https://evil.example/x.css">',
        '<meta http-equiv="refresh" content="0;url=https://evil.example">',
        '<base href="https://evil.example/">',
    ],
)
def test_실행되는_것은_남지_않는다(payload: str):
    out = sanitize_html(payload)
    low = out.lower()
    assert "<script" not in low
    assert "javascript:" not in low.replace("&#", "")
    assert "onerror" not in low and "onload" not in low and "onfocus" not in low
    assert "<iframe" not in low and "<object" not in low and "<embed" not in low
    assert "<style" not in low and "<link" not in low and "<meta" not in low
    assert "<form" not in low and "<input" not in low and "<base" not in low


def test_script_안의_글자도_사라진다():
    """태그만 지우면 `alert(1)`이 본문 글자로 남는다 — 그건 씻은 게 아니다."""
    assert sanitize_html("<script>alert(1)</script>안녕") == "안녕"


def test_평범한_문장은_그대로_남는다():
    src = '<p>안녕 <strong>반가워</strong></p><ul><li>하나</li></ul>'
    assert sanitize_html(src) == src


def test_링크는_남고_rel이_붙는다():
    out = sanitize_html('<a href="https://example.com" target="_blank">예시</a>')
    assert 'href="https://example.com"' in out
    assert 'target="_blank"' in out
    # 새 창 링크에 opener를 남기면 그쪽이 이 창을 조종할 수 있다(tabnabbing).
    assert "noopener" in out


def test_상대_주소와_앵커는_통과한다():
    assert '/uploads/a.png' in sanitize_html('<img src="/uploads/a.png" alt="사진">')
    assert '#tail' in sanitize_html('<a href="#tail">아래로</a>')
    assert 'mailto:' in sanitize_html('<a href="mailto:me@example.com">메일</a>')


def test_출처를_숨긴_절대주소는_막는다():
    """`//evil` 은 상대 경로처럼 보이지만 남의 출처로 나간다."""
    assert "evil" not in sanitize_html('<a href="//evil.example/x">클릭</a>')


def test_이미지는_남고_lazy와_alt가_보강된다():
    out = sanitize_html('<img src="/uploads/a.png">')
    assert 'src="/uploads/a.png"' in out
    assert 'loading="lazy"' in out
    # alt가 없으면 화면낭독기가 파일 이름을 읽는다 → 장식으로 선언한다
    assert 'alt=""' in out


def test_주소_없는_이미지와_링크는_통째로_사라진다():
    assert sanitize_html('<img alt="없음">') == ""
    assert sanitize_html("<a>목적지 없음</a>") == "목적지 없음"


def test_class는_남고_style과_id는_사라진다():
    """`class`만 남기는 게 스킨(CSS)과 문장을 잇는 유일한 끈이다."""
    out = sanitize_html('<p class="인사" style="color:red" id="main">안녕</p>')
    assert 'class="인사"' in out
    assert "style" not in out
    # id가 남으면 페이지의 진짜 #main(본문 바로가기 대상)과 충돌한다
    assert "id=" not in out


def test_모르는_태그는_껍데기만_버리고_글자는_남긴다():
    """사람이 쓴 문장이 낯선 태그에 싸였다고 사라지면, 왜 없어졌는지 알 길이 없다."""
    assert sanitize_html("<marquee>지나가는 글씨</marquee>") == "지나가는 글씨"
    assert sanitize_html("<font color=red>빨강</font>") == "빨강"


def test_안_닫힌_태그는_닫아서_내보낸다():
    """짝이 안 맞으면 사용자 문장 하나가 그 아래 화면 전체를 삼킨다."""
    assert sanitize_html("<p>열고 안 닫음") == "<p>열고 안 닫음</p>"
    assert sanitize_html("<div><p>어긋남</div>") == "<div><p>어긋남</p></div>"


def test_글자는_이스케이프된다():
    assert sanitize_html("a < b & c") == "a &lt; b &amp; c"


def test_주석은_사라진다():
    """옛 IE의 조건부 주석은 주석 안에서 실행됐다."""
    assert sanitize_html("<!--[if IE]><script>x</script><![endif]-->") == ""


def test_알맹이_없는_태그는_빈_것으로_본다():
    """`<p></p>`가 저장돼 있으면 '문장이 있다'로 세어져 빈 칸이 자리만 차지한다."""
    assert sanitize_html("<p></p>") == ""
    assert sanitize_html("   ") == ""
    # 글자가 없어도 이미지는 알맹이다
    assert sanitize_html('<p><img src="/a.png" alt=""></p>') != ""


def test_세_칸_모양은_항상_같다():
    out = sanitize_slots({"intro": "<p>hi</p>", "없는키": "x"})
    assert set(out) == {"intro", "aside", "footer"}
    assert out["aside"] == "" and out["footer"] == ""
    assert sanitize_slots(None) == {"intro": "", "aside": "", "footer": ""}


# ─────────────────────────────────────────────────────────────── API


def test_기본은_빈_세_칸이다(client, make_user):
    make_user(role="admin")
    r = client.get("/api/skin")
    assert r.status_code == 200
    assert r.json()["slots"] == {"intro": "", "aside": "", "footer": ""}


def test_주인이_없어도_세_칸_모양은_온다(client):
    # 새 설치라 admin이 아직 없다. 화면이 뜨는 게 더 중요하다.
    assert client.get("/api/skin").json()["slots"] == {"intro": "", "aside": "", "footer": ""}


def test_저장하면_공개_조회에_나온다(client, make_user, auth_headers):
    admin = make_user(role="admin")
    r = client.put(
        "/api/skin/slots",
        json={"intro": "<p>안녕</p>", "aside": "", "footer": "<p>끝</p>"},
        headers=auth_headers(admin),
    )
    assert r.status_code == 200
    assert r.json()["slots"]["intro"] == "<p>안녕</p>"

    # 무인증 방문자도 같은 값을 받는다 — 이게 화면에 그려지는 경로다
    public = client.get("/api/skin").json()
    assert public["slots"]["intro"] == "<p>안녕</p>"
    assert public["slots"]["footer"] == "<p>끝</p>"


def test_위험한_것은_거절이_아니라_씻어서_돌려준다(client, make_user, auth_headers):
    """422로 막지 않는 이유는 schemas/user.py의 SlotsUpdate 주석에 있다.

    돌려주는 값이 씻은 결과라는 게 핵심이다 — 편집기가 이걸로 입력칸을 다시 채워서
    무엇이 사라졌는지 사람에게 보여준다.
    """
    admin = make_user(role="admin")
    r = client.put(
        "/api/skin/slots",
        json={"intro": "<p>안녕</p><script>alert(1)</script><img src=x onerror=alert(1)>"},
        headers=auth_headers(admin),
    )
    assert r.status_code == 200
    got = r.json()["slots"]["intro"]
    assert "<p>안녕</p>" in got
    assert "script" not in got.lower() and "onerror" not in got.lower()

    # **DB에 씻긴 값이 들어갔는지**가 진짜 관심사다. 응답만 씻고 저장은 원문이면,
    # 읽는 쪽을 하나라도 빠뜨리는 순간 그게 그대로 나간다.
    public = client.get("/api/skin").json()["slots"]["intro"]
    assert "script" not in public.lower() and "onerror" not in public.lower()


def test_전부_비우면_되돌아간다(client, make_user, auth_headers):
    admin = make_user(role="admin")
    h = auth_headers(admin)
    client.put("/api/skin/slots", json={"intro": "<p>있음</p>"}, headers=h)
    r = client.put("/api/skin/slots", json={"intro": "", "aside": "", "footer": ""}, headers=h)
    assert r.json()["slots"] == {"intro": "", "aside": "", "footer": ""}
    assert client.get("/api/skin").json()["slots"]["intro"] == ""


def test_로그인_안_하면_못_바꾼다(client, make_user):
    make_user(role="admin")
    r = client.put("/api/skin/slots", json={"intro": "<p>x</p>"})
    assert r.status_code in (401, 403)


def test_승인_대기중인_사람은_못_바꾼다(client, make_user, auth_headers):
    pending = make_user(role="pending")
    r = client.put("/api/skin/slots", json={"intro": "<p>x</p>"}, headers=auth_headers(pending))
    assert r.status_code == 403


def test_너무_길면_거절한다(client, make_user, auth_headers):
    admin = make_user(role="admin")
    r = client.put(
        "/api/skin/slots",
        json={"intro": "가" * (SLOT_MAX + 1)},
        headers=auth_headers(admin),
    )
    assert r.status_code == 422


def test_문장은_저장한_사람_주소에서_나온다(client, make_user, auth_headers):
    """스킨과 같은 규칙이다 — 저장한 사람과 그 값이 보이는 곳이 일치해야 한다.

    이걸 어기면 글쓴이가 쓴 소개가 **남의 블로그**에 나온다.
    """
    admin = make_user(role="admin")
    writer = make_user(role="writer")
    client.put("/api/skin/slots", json={"intro": "<p>주인</p>"}, headers=auth_headers(admin))
    client.patch(
        "/api/auth/me/handle", json={"handle": "writerb"}, headers=auth_headers(writer)
    )
    client.put("/api/skin/slots", json={"intro": "<p>글쓴이</p>"}, headers=auth_headers(writer))

    assert client.get("/api/skin").json()["slots"]["intro"] == "<p>주인</p>"
    assert client.get("/api/skin?handle=writerb").json()["slots"]["intro"] == "<p>글쓴이</p>"


def test_스킨과_문장은_서로를_지우지_않는다(client, make_user, auth_headers):
    """한 응답에 같이 실려 오지만 저장 경로는 둘이다. 한쪽 저장이 다른 쪽을 날리면
    사람은 방금 쓴 CSS가 왜 사라졌는지 모른다."""
    admin = make_user(role="admin")
    h = auth_headers(admin)
    client.put("/api/skin/slots", json={"intro": "<p>문장</p>"}, headers=h)
    client.put("/api/skin", json={"custom_css": ":root{--color-accent:#000}"}, headers=h)

    got = client.get("/api/skin").json()
    assert got["slots"]["intro"] == "<p>문장</p>"
    assert "--color-accent" in got["css"]

    client.put("/api/skin/slots", json={"intro": "<p>바꿈</p>"}, headers=h)
    assert "--color-accent" in client.get("/api/skin").json()["css"]


def test_DB가_깨져_있어도_조회는_안_죽는다(client, make_user, db):
    """손으로 고쳤거나 옛 형식이 남아 있을 수 있다. 장식 하나 때문에 방문자
    **전원의 첫 화면**이 500이 되면 안 된다."""
    admin = make_user(role="admin")
    admin.custom_html = "이건 JSON이 아니다{{{"
    db.commit()
    r = client.get("/api/skin")
    assert r.status_code == 200
    assert r.json()["slots"] == {"intro": "", "aside": "", "footer": ""}

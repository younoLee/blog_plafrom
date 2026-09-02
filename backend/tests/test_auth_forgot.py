"""`/api/auth/forgot-password` — 링크를 **발급하는 쪽**을 잠근다.

왜 새 파일인가 (2026-09-02): 이 라우트에 테스트가 0개였다. test_auth_security.py는
재설정 토큰을 `create_email_token(...)`으로 **직접 만들어** `/reset-password`만 부른다.
그래서 소비 쪽(1회용·purpose 대조)은 잠겨 있었지만 발급 쪽은 아무도 안 봤다 —
누가 받는가, 무엇을 응답하는가, 토큰에 무엇을 싣는가가 전부 무방비였다.

여기서 잠그는 세 가지:
  (a) 계정 존재 여부가 응답으로 새지 않는가 (있음/없음/차단이 구분 불가한가)
  (b) 차단된 계정이 발송 대상에서 빠지는가
  (c) 발급된 토큰이 `token_version`에 묶여 세션 무효화와 함께 죽는가

**메일은 conftest의 autouse `no_smtp`가 막는다.** 이 저장소는 `send_reset_email`
같은 함수 이름을 갈아끼우지 않고 `smtplib.SMTP`를 통째로 가짜로 바꾼다 — 메시지
조립·헤더 정리·HTML 본문 같은 코드 경로를 그대로 지나가게 두려는 것이다(그 이유는
conftest 주석에 적혀 있다). 그래서 이 파일도 같은 방식으로 `sent_mail` 픽스처를 쓰고,
**링크의 토큰을 메일 본문에서 꺼내 쓴다.** 토큰을 테스트가 만들면 발급 로직을 또
안 보게 되므로, 그건 이 파일이 존재하는 이유를 스스로 지우는 셈이다.

**레이트리밋(5/hour)이 테스트끼리를 굶기지 않는 이유**: conftest가 import 시점에
`limiter.enabled = False`로 리미터를 통째로 끈다. slowapi는 IP를 키로 쓰는데
TestClient는 모든 요청이 같은 주소("testclient")라, 끄지 않으면 이 파일의 6번째
forgot 호출부터 429가 나고 **실행 순서에 따라 다른 테스트가 깨진다.** 리밋이 켜진
채로 확인하고 싶은 게 있으면 그 테스트 안에서만 켜고 끝나면 되돌릴 것 —
전역으로 켜두면 굶는 쪽이 이 파일 밖의 테스트가 된다.
"""
import re

FORGOT = "/api/auth/forgot-password"


def _reset_token(msg) -> str:
    """가로챈 메일 본문에서 재설정 토큰을 꺼낸다(라우터가 실제로 발급한 값)."""
    body = msg.get_body(preferencelist=("plain",))
    assert body is not None, "평문 본문이 없다"
    m = re.search(r"/reset\?token=([\w.\-]+)", body.get_content())
    assert m, "메일에 재설정 링크가 없다"
    return m.group(1)


def _recipients(sent_mail) -> list[str]:
    return [msg["To"] for msg in sent_mail]


# ── (a) 응답은 계정 존재 여부를 말하지 않는다 ────────────────────────────────
def test_있음_없음_차단이_전부_같은_응답이다(client, make_user):
    """세 경우의 상태코드와 본문이 **바이트 단위로 같아야** 한다.

    하나라도 갈리면 이 라우트가 이메일 열거 오라클이 된다 — 가입(register)이 항상
    202를 주느라 들인 공이 여기서 그대로 새는 것이라, 응답을 맞추는 게 이 엔드포인트의
    핵심 계약이다. 아래 (b)의 '실제 발송 대상'이 셋 중 하나뿐인데도 그렇다.
    """
    live = make_user(role="writer")
    banned = make_user(role="banned")

    rs = [
        client.post(FORGOT, json={"email": live.email}),
        client.post(FORGOT, json={"email": "nobody-here@test.com"}),
        client.post(FORGOT, json={"email": banned.email}),
    ]

    assert {r.status_code for r in rs} == {202}, [r.status_code for r in rs]
    assert len({r.text for r in rs}) == 1, [r.text for r in rs]


# ── (b) 실제로 메일을 받는 건 누구인가 ───────────────────────────────────────
def test_메일은_존재하고_차단되지_않은_계정에만_간다(client, make_user, sent_mail):
    """응답이 같다는 것과 '아무에게나 보낸다'는 것은 다르다. 발송 대상은 실제로 좁다.

    없는 주소로도 보내면 SES 하드바운스가 쌓여 발신 평판이 깎이고(가입이 초대제로
    닫힌 지금 남은 유일한 발송 경로다), 차단된 계정에 보내면 로그인도 못 하는 사람에게
    '계정이 살아 있다'는 신호를 주는 셈이다.
    """
    live = make_user(role="writer")
    banned = make_user(role="banned")

    client.post(FORGOT, json={"email": live.email})
    client.post(FORGOT, json={"email": "nobody-here@test.com"})
    client.post(FORGOT, json={"email": banned.email})

    assert _recipients(sent_mail) == [live.email]


def test_미인증_계정도_받는다(client, make_user, sent_mail):
    """가입만 하고 인증을 못 끝낸 사람도 비밀번호를 되찾을 수 있어야 한다.
    (차단은 제외 조건이지만 미인증은 아니다 — 라우터가 role만 본다)"""
    user = make_user(role="pending", verified=False)
    client.post(FORGOT, json={"email": user.email})
    assert _recipients(sent_mail) == [user.email]


def test_대소문자를_섞어_쳐도_같은_계정으로_간다(client, make_user, sent_mail):
    """조회가 대소문자를 무시한다(`_find_user_by_email`). 안 그러면 초대로 소문자
    저장된 사람이 평소 쓰던 대로 치고 202를 받는데 **메일은 안 오는** 잠금이 된다."""
    user = make_user(role="writer", email="case-forgot@test.com")

    r = client.post(FORGOT, json={"email": "Case-Forgot@TEST.com"})

    assert r.status_code == 202
    assert _recipients(sent_mail) == [user.email]


# ── (c) 발급된 토큰이 token_version에 묶여 있는가 ────────────────────────────
def test_발급된_토큰은_한_번만_쓰인다(client, make_user, sent_mail):
    """메일로 나간 그 토큰으로 재설정이 되고, **같은 토큰의 재사용은 400**이다.

    1회용을 만드는 것은 발급 시점에 실은 `ver`(그때의 token_version)이다. 재설정이
    token_version을 올리므로 두 번째 호출은 ver 불일치로 걸린다. 발급 쪽이 ver을
    안 실으면(기본값 0) 이 성질이 조용히 사라지는데, 토큰을 테스트가 직접 만들면
    그 사고를 못 본다 — 그래서 여기서는 **메일에서 꺼낸 토큰**만 쓴다.
    """
    user = make_user(role="writer", password="oldpassword1")
    assert client.post(FORGOT, json={"email": user.email}).status_code == 202
    token = _reset_token(sent_mail[-1])

    first = client.post(
        "/api/auth/reset-password",
        json={"token": token, "new_password": "newpassword1"},
    )
    assert first.status_code == 200, first.text

    second = client.post(
        "/api/auth/reset-password",
        json={"token": token, "new_password": "another12345"},
    )
    assert second.status_code == 400

    # 새 비번으로는 들어가진다 (첫 번째 재설정이 진짜로 먹혔다는 확인)
    assert client.post(
        "/api/auth/login", json={"email": user.email, "password": "newpassword1"}
    ).status_code == 200


def test_로그아웃하면_대기중인_재설정_링크도_같이_죽는다(
    client, make_user, auth_headers, sent_mail
):
    """세션 무효화(`token_version` +1)와 재설정 링크가 **한 레버로 묶여 있는가.**

    기기를 잃어버렸을 때 사람이 하는 일은 로그아웃(전 기기 무효화)인데, 그때 메일함에
    남아 있던 재설정 링크가 계속 살아 있으면 회수가 절반만 되는 것이다. 발급 시점의
    ver이 토큰에 실려 있어야 이게 성립한다.
    """
    user = make_user(role="writer")
    assert client.post(FORGOT, json={"email": user.email}).status_code == 202
    token = _reset_token(sent_mail[-1])

    assert client.post(
        "/api/auth/logout", headers=auth_headers(user)
    ).status_code == 204

    r = client.post(
        "/api/auth/reset-password",
        json={"token": token, "new_password": "newpassword1"},
    )
    assert r.status_code == 400, r.text

"""인증 라우터: 가입/로그인/내정보. 실제 흐름의 성공·실패 경로를 건다."""


def test_register_returns_202(client):
    r = client.post(
        "/api/auth/register",
        json={"email": "new@test.com", "password": "password123"},
    )
    # 이메일 enumeration 방지로 항상 202(메일로만 안내) — 응답에 토큰 없음
    assert r.status_code == 202


def test_register_rejects_short_password(client):
    r = client.post(
        "/api/auth/register", json={"email": "x@test.com", "password": "short"}
    )
    assert r.status_code == 422  # min_length=8


def test_login_wrong_password_401(client, make_user):
    make_user(email="a@test.com", password="password123")
    r = client.post(
        "/api/auth/login", json={"email": "a@test.com", "password": "WRONG-pw-9"}
    )
    assert r.status_code == 401


def test_login_unverified_email_403(client, make_user):
    make_user(email="unv@test.com", password="password123", verified=False)
    r = client.post(
        "/api/auth/login", json={"email": "unv@test.com", "password": "password123"}
    )
    assert r.status_code == 403  # 이메일 인증 필요


def test_login_success_returns_token(client, make_user):
    make_user(email="ok@test.com", password="password123", verified=True)
    r = client.post(
        "/api/auth/login", json={"email": "ok@test.com", "password": "password123"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"


def test_banned_login_403(client, make_user):
    make_user(email="banned@test.com", password="password123", role="banned")
    r = client.post(
        "/api/auth/login",
        json={"email": "banned@test.com", "password": "password123"},
    )
    assert r.status_code == 403


def test_me_requires_auth(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_with_token(client, make_user, auth_headers):
    u = make_user(email="me@test.com")
    r = client.get("/api/auth/me", headers=auth_headers(u))
    assert r.status_code == 200
    assert r.json()["email"] == "me@test.com"


# ── 로그아웃 (2026-08-14) ──────────────────────────────────────────────────────
# 잠그는 불변식은 "204가 온다"가 아니라 **그 토큰이 정말 죽었는가**다.
# 상태코드만 보면 엔드포인트가 아무것도 안 해도 통과한다.


def test_logout_requires_auth(client):
    assert client.post("/api/auth/logout").status_code == 401


def test_logout_invalidates_the_token_that_called_it(client, make_user, auth_headers):
    u = make_user(email="lo@test.com")
    h = auth_headers(u)
    assert client.get("/api/auth/me", headers=h).status_code == 200
    assert client.post("/api/auth/logout", headers=h).status_code == 204
    # 같은 토큰으로 다시 → 401. token_version이 올라가 서명은 맞지만 버전이 안 맞는다.
    assert client.get("/api/auth/me", headers=h).status_code == 401


def test_logout_invalidates_other_devices_too(client, make_user, auth_headers):
    """계정 단위 무효화 — 이게 이 기능의 목적이다(기기 분실).

    기기 단위였다면 아래 phone 토큰은 살아 있어야 한다. 살아 있으면 안 된다.
    """
    u = make_user(email="two@test.com")
    laptop = auth_headers(u)
    phone = auth_headers(u)  # 같은 계정의 다른 기기(같은 token_version으로 따로 발급)
    assert client.post("/api/auth/logout", headers=laptop).status_code == 204
    assert client.get("/api/auth/me", headers=phone).status_code == 401


def test_logout_then_login_again_works(client, make_user):
    """로그아웃이 계정을 잠그면 안 된다 — 새 로그인은 새 버전으로 발급된다."""
    make_user(email="back@test.com", password="password123", verified=True)
    tok = client.post(
        "/api/auth/login", json={"email": "back@test.com", "password": "password123"}
    ).json()["access_token"]
    assert (
        client.post(
            "/api/auth/logout", headers={"Authorization": f"Bearer {tok}"}
        ).status_code
        == 204
    )
    r = client.post(
        "/api/auth/login", json={"email": "back@test.com", "password": "password123"}
    )
    assert r.status_code == 200
    new = r.json()["access_token"]
    assert new != tok
    assert (
        client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {new}"}
        ).status_code
        == 200
    )


# ── 비밀번호 바이트 길이 경계 (bcrypt 5.0 회귀 방지, 2026-07-22) ────────────────
# bcrypt는 72'바이트'까지만 받고 5.0부터 초과분을 ValueError로 거부한다(4.x는 조용히
# 잘랐다). 스키마의 PW_MAX=72는 '글자 수'라 이걸 못 막는다 — 한글은 글자당 3바이트라
# 24글자만 넘어도 걸린다. deps bump 때 실제로 500이 났던 자리라 경계값을 고정해둔다.
# 기존 테스트가 전부 짧은 ASCII만 써서 못 잡았다.
LONG_KR = "가" * 30  # 30글자 = 90바이트


def test_register_accepts_password_over_72_bytes(client):
    """한글 긴 비밀번호로 가입이 500 나지 않는다."""
    r = client.post(
        "/api/auth/register", json={"email": "kr@test.com", "password": LONG_KR}
    )
    assert r.status_code == 202


def test_login_with_password_over_72_bytes(client, make_user):
    """72바이트를 넘겨도 로그인이 되고, 틀린 비번은 500이 아니라 401이다."""
    make_user(email="krlogin@test.com", password=LONG_KR, verified=True)

    r = client.post(
        "/api/auth/login", json={"email": "krlogin@test.com", "password": LONG_KR}
    )
    assert r.status_code == 200

    r = client.post(
        "/api/auth/login", json={"email": "krlogin@test.com", "password": "나" * 30}
    )
    assert r.status_code == 401


# ── 표시명 (2026-08-14) ────────────────────────────────────────────────────────
# 왜 이게 생겼나: 구독 화면이 "회원 · 회원 · 회원"으로 보인다는 신고. 원인은
# display_name이 전부 NULL인 것이고, 진짜 원인은 **그걸 정할 방법이 제품에 없었다**는
# 것이다. 유일한 경로(create_user.py --display-name)는 같은 실행에서 비밀번호를 덮어썼다.
# 그래서 이 테스트가 잠그는 핵심은 "이름이 바뀐다"가 아니라 **"비밀번호가 안 바뀐다"**이다.


def test_update_display_name_requires_auth(client):
    r = client.patch("/api/auth/me", json={"display_name": "누구"})
    assert r.status_code == 401


def test_update_display_name(client, make_user, auth_headers):
    u = make_user(email="dn@test.com")
    r = client.patch("/api/auth/me", json={"display_name": "유노"}, headers=auth_headers(u))
    assert r.status_code == 200
    assert r.json()["display_name"] == "유노"
    # 다시 읽어도 같은 값 (응답만 그럴듯한 게 아니라 실제로 저장됐는가)
    assert client.get("/api/auth/me", headers=auth_headers(u)).json()["display_name"] == "유노"


def test_update_display_name_does_not_touch_password(client, make_user, auth_headers):
    """이름을 바꿔도 로그인은 그대로여야 한다 — 이 기능이 존재하는 이유 그 자체."""
    make_user(email="keep@test.com", password="password123", verified=True)
    tok = client.post(
        "/api/auth/login", json={"email": "keep@test.com", "password": "password123"}
    ).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.patch("/api/auth/me", json={"display_name": "이름"}, headers=h).status_code == 200
    # 같은 비밀번호로 다시 로그인된다
    assert (
        client.post(
            "/api/auth/login", json={"email": "keep@test.com", "password": "password123"}
        ).status_code
        == 200
    )


def test_blank_display_name_clears_it(client, make_user, auth_headers):
    """지우는 방법이 없으면 한 번 정한 사람이 갇힌다."""
    u = make_user(email="clear@test.com", display_name="예전이름")
    r = client.patch("/api/auth/me", json={"display_name": "   "}, headers=auth_headers(u))
    assert r.status_code == 200
    assert r.json()["display_name"] is None


def test_display_name_too_long_is_422(client, make_user, auth_headers):
    """DB 컬럼이 50자다 — 스키마가 안 막으면 422가 아니라 DB에서 터진다."""
    u = make_user(email="long@test.com")
    r = client.patch("/api/auth/me", json={"display_name": "가" * 51}, headers=auth_headers(u))
    assert r.status_code == 422


def test_display_name_fallback_distinguishes_users(client, make_user, auth_headers):
    """이름을 안 정한 계정끼리도 구분돼야 한다 — 전부 "회원"이면 화면이 못 쓰게 된다."""
    author = make_user(email="a-nodn@test.com")
    me = make_user(email="b-nodn@test.com")
    client.post("/api/subscriptions", json={"author_id": author.id}, headers=auth_headers(me))
    rows = client.get("/api/subscriptions/detail", headers=auth_headers(me)).json()
    assert rows[0]["name"] == f"회원 #{author.id}"


# ── 이메일 인증 토큰은 본문으로 받는다 (09-04 검사 SEC-07) ───────────────────
#
# `token: str` 은 FastAPI 에서 쿼리 파라미터다. uvicorn 액세스 로그는 요청 라인을
# 통째로 찍으므로 그대로 두면 **원문 토큰이 컨테이너 로그에 평문으로 쌓인다** —
# 이 저장소는 같은 이유로 초대 토큰(08-27)과 기기 endpoint(09-02)를 이미 본문으로
# 옮겼고, reset-password 는 처음부터 본문이다. verify 만 남아 있었다.


def test_인증_토큰은_본문으로_받는다(client, make_user, db):
    from app.core.security import create_email_token

    u = make_user(role="pending", verified=False)
    token = create_email_token(u.id, purpose="verify", ver=u.token_version)

    r = client.post("/api/auth/verify", json={"token": token})
    assert r.status_code == 200
    assert r.json()["email_verified"] is True


def test_쿼리스트링으로_주면_안_받는다(client, make_user):
    """구경로가 남아 있으면 로그에 토큰이 계속 쌓인다 — 422 로 끊긴다."""
    from app.core.security import create_email_token

    u = make_user(role="pending", verified=False)
    token = create_email_token(u.id, purpose="verify", ver=u.token_version)
    assert client.post(f"/api/auth/verify?token={token}").status_code == 422


def test_위조된_토큰은_400(client):
    assert client.post("/api/auth/verify", json={"token": "not-a-token"}).status_code == 400


# ── 내 계정을 내가 지운다 · 내 것을 내려받는다 (09-04 검사 GAP-6) ────────────
#
# 그전까지 계정을 지울 수 있는 사람은 관리자뿐이었다. 나가고 싶은 사람은 서버가 켜진
# 날 관리자에게 부탁해야 했고 그 요청을 받을 창구도 없었다. 내보내기를 함께 두는 이유는
# 가져갈 방법 없는 삭제가 '전부 잃거나 전부 남기거나'만 남기기 때문이다.


def test_내_글과_댓글을_내려받는다(client, make_user, auth_headers):
    me = make_user(role="writer", display_name="나")
    other = make_user(role="writer")
    h = auth_headers(me)
    post = client.post("/api/posts", headers=h, json={"title": "내 글", "content": "본문"}).json()
    others_post = client.post(
        "/api/posts", headers=auth_headers(other), json={"title": "남의 글", "content": "C"}
    ).json()
    client.post(
        f"/api/posts/{others_post['id']}/comments", json={"author": "x", "content": "내 댓글"}, headers=h
    )

    body = client.get("/api/auth/me/export", headers=h).json()
    assert body["account"]["display_name"] == "나"
    assert [p["title"] for p in body["posts"]] == ["내 글"]
    assert [c["content"] for c in body["comments"]] == ["내 댓글"]
    assert body["posts"][0]["id"] == post["id"]


def test_익명_댓글은_내보내기에_없다(client, make_user, auth_headers):
    """user_id 가 없는 게 익명의 정의다 — 넣으려면 IP 로 짐작해야 하고, 그건 남의 댓글을
    내 것으로 내보낼 수 있다는 뜻이다."""
    me = make_user(role="writer")
    post = client.post(
        "/api/posts", headers=auth_headers(me), json={"title": "T", "content": "C"}
    ).json()
    client.post(f"/api/posts/{post['id']}/comments", json={"author": "손님", "content": "익명"})

    assert client.get("/api/auth/me/export", headers=auth_headers(me)).json()["comments"] == []


def test_내보내기는_로그인해야_한다(client):
    assert client.get("/api/auth/me/export").status_code == 401


def test_비밀번호가_맞아야_계정이_지워진다(client, make_user, auth_headers):
    me = make_user(role="writer", password="password123")
    h = auth_headers(me)
    assert client.post("/api/auth/me/delete", json={"password": "틀린비번"}, headers=h).status_code == 401
    assert client.get("/api/auth/me", headers=h).status_code == 200  # 아직 살아 있다


def test_계정을_지우면_글도_지워지고_댓글은_익명으로_남는다(client, make_user, auth_headers, db):
    """정리 범위는 관리자 삭제와 같다. 남의 글에 남긴 대화까지 지우는 것은
    '내 것을 지운다'의 범위를 넘는다(comments.user_id 가 SET NULL 인 이유)."""
    me = make_user(role="writer", password="password123")
    other = make_user(role="writer")
    h = auth_headers(me)
    my_post = client.post("/api/posts", headers=h, json={"title": "내 글", "content": "C"}).json()
    others_post = client.post(
        "/api/posts", headers=auth_headers(other), json={"title": "남의 글", "content": "C"}
    ).json()
    client.post(
        f"/api/posts/{others_post['id']}/comments", json={"author": "x", "content": "남긴 말"}, headers=h
    )

    assert client.post("/api/auth/me/delete", json={"password": "password123"}, headers=h).status_code == 204

    assert client.get(f"/api/posts/{my_post['id']}").status_code == 404
    assert client.get("/api/auth/me", headers=h).status_code == 401
    left = client.get(f"/api/posts/{others_post['id']}/comments").json()
    assert [c["content"] for c in left] == ["남긴 말"]
    assert left[0]["is_member"] is False  # 익명으로 남는다


def test_관리자는_스스로_못_지운다(client, make_user, auth_headers):
    """그 계정이 사라지면 아무도 관리 화면에 못 들어가고, 새로 만들 경로는 서버에
    직접 붙는 것뿐이다."""
    admin = make_user(role="admin", password="password123")
    r = client.post(
        "/api/auth/me/delete", json={"password": "password123"}, headers=auth_headers(admin)
    )
    assert r.status_code == 400

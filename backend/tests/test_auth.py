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

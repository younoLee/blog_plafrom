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

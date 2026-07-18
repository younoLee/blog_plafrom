"""인증의 보안 속성 — 이메일인증/비번재설정 흐름 + 토큰 무효화·혼용 차단.
로그인 성공만이 아니라 '세션이 제대로 끊기는가'를 건다."""
from app.core.security import create_email_token


# ── 이메일 인증 ──────────────────────────────────────────────────────────────
def test_verify_email_flow(client, make_user):
    user = make_user(role="pending", verified=False)
    token = create_email_token(user.id, purpose="verify")
    r = client.post(f"/api/auth/verify?token={token}")
    assert r.status_code == 200
    assert r.json()["email_verified"] is True


def test_verify_invalid_token_400(client):
    assert client.post("/api/auth/verify?token=garbage.token.x").status_code == 400


# ── 비번 재설정: 성공 + 기존 세션 무효화 ──────────────────────────────────────
def test_reset_password_changes_pw_and_revokes_old_tokens(
    client, make_user, auth_headers
):
    user = make_user(role="writer", password="oldpassword1")
    old_headers = auth_headers(user)  # 재설정 전 토큰(token_version=0)
    token = create_email_token(user.id, purpose="reset", ver=user.token_version)

    r = client.post(
        "/api/auth/reset-password",
        json={"token": token, "new_password": "newpassword1"},
    )
    assert r.status_code == 200

    # 비번 바뀌면 기존 액세스 토큰 즉시 무효 (token_version++)
    assert client.get("/api/auth/me", headers=old_headers).status_code == 401
    # 새 비번으로는 로그인됨
    lr = client.post(
        "/api/auth/login", json={"email": user.email, "password": "newpassword1"}
    )
    assert lr.status_code == 200


def test_reset_token_is_single_use(client, make_user):
    user = make_user(role="writer")
    token = create_email_token(user.id, purpose="reset", ver=user.token_version)
    first = client.post(
        "/api/auth/reset-password", json={"token": token, "new_password": "newpassword1"}
    )
    assert first.status_code == 200
    # 같은 토큰 재사용 → ver 불일치로 거부(1회용)
    second = client.post(
        "/api/auth/reset-password", json={"token": token, "new_password": "another1234"}
    )
    assert second.status_code == 400


# ── 토큰 혼용 차단 ───────────────────────────────────────────────────────────
def test_email_token_cannot_be_used_as_bearer(client, make_user):
    user = make_user(role="writer")
    email_token = create_email_token(user.id, purpose="verify")
    # purpose가 박힌 이메일 토큰은 로그인 토큰으로 못 씀(토큰 혼동 방지)
    r = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {email_token}"}
    )
    assert r.status_code == 401


def test_verify_purpose_token_rejected_on_reset(client, make_user):
    user = make_user(role="writer")
    verify_token = create_email_token(user.id, purpose="verify", ver=user.token_version)
    # verify 목적 토큰을 reset 엔드포인트에 쓰면 purpose 불일치 → 거부
    r = client.post(
        "/api/auth/reset-password",
        json={"token": verify_token, "new_password": "newpassword1"},
    )
    assert r.status_code == 400

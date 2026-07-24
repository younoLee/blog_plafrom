"""인증의 보안 속성 — 이메일인증/비번재설정 흐름 + 토큰 무효화·혼용 차단.
로그인 성공만이 아니라 '세션이 제대로 끊기는가'를 건다."""
from app.core.config import settings
from app.core.security import create_email_token


# ── 초대제 게이트 ────────────────────────────────────────────────────────────
def test_register_closed_when_signup_disabled(client, monkeypatch):
    """allow_signup=False(운영 기본)면 register가 403으로 닫힌다. 프론트 폼 제거만으론
    라우트가 살아 아무 주소로 인증메일을 보낼 수 있었다(SES 하드바운스) — 백엔드에서 막는다.
    (conftest의 autouse open_signup이 기본을 열어두므로 여기서 되돌려 검증)"""
    monkeypatch.setattr(settings, "allow_signup", False)
    r = client.post(
        "/api/auth/register",
        json={"email": "closed@test.com", "password": "password123"},
    )
    assert r.status_code == 403


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


# ── 미인증 계정 선점(account pre-hijacking) ──────────────────────────────────
def test_reregister_unverified_replaces_password(client, db):
    """미인증 계정에 같은 이메일로 다시 가입하면 **비밀번호가 갱신돼야** 한다.

    안 그러면 계정 선점이 된다: 공격자가 피해자 이메일로 먼저 가입해 두면(미인증),
    피해자가 같은 주소로 가입할 때 인증 메일만 피해자에게 가고 저장된 해시는
    공격자 것으로 남는다. 피해자가 링크를 누르는 순간 '검증된' 계정이 되는데
    로그인은 공격자만 할 수 있다. (2026-07-22 보안검사에서 발견)
    """
    from app.models.user import User

    victim_email = "prehijack-target@test.com"
    attacker_pw, victim_pw = "attacker-password-1", "victim-password-2"

    # 1) 공격자가 피해자 이메일로 선점 가입 (미인증 상태로 생성됨)
    assert client.post(
        "/api/auth/register", json={"email": victim_email, "password": attacker_pw}
    ).status_code == 202

    # 2) 진짜 피해자가 같은 이메일로 가입 → 이 분기가 해시를 덮어써야 한다
    assert client.post(
        "/api/auth/register", json={"email": victim_email, "password": victim_pw}
    ).status_code == 202

    # 3) 피해자가 메일 링크로 인증을 마친다
    uid = db.query(User).filter(User.email == victim_email).one().id
    assert client.post(
        f"/api/auth/verify?token={create_email_token(uid, purpose='verify')}"
    ).status_code == 200

    # 4) 공격자 비밀번호로는 못 들어가고, 피해자 비밀번호로는 들어가야 한다
    assert client.post(
        "/api/auth/login", json={"email": victim_email, "password": attacker_pw}
    ).status_code == 401
    assert client.post(
        "/api/auth/login", json={"email": victim_email, "password": victim_pw}
    ).status_code == 200

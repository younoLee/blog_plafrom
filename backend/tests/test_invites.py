"""초대제 가입: 발급 → 확인 → 1회용 소각.

이 기능의 핵심은 '가입이 된다'가 아니라 **한 번만 된다**와 **실패를 구분해
알려주지 않는다**이다. 그래서 성공 경로보다 재사용·만료·위조 쪽에 테스트가 많다.
"""
import threading
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text

from app.core.config import settings
from app.core.security import hash_invite_token
from app.main import app
from app.models.invite import Invite
from app.models.user import User


def _invite(client, headers, email="invited@test.com", **kw):
    """관리자로 초대를 발급하고 (응답 JSON, 원문 토큰)을 돌려준다."""
    r = client.post("/api/admin/invites", json={"email": email, **kw}, headers=headers)
    assert r.status_code == 201, r.text
    body = r.json()
    return body, body["url"].split("token=")[1]


# ── 발급 ────────────────────────────────────────────────────────────────────


def test_admin_creates_invite_with_url(client, make_user, auth_headers):
    admin = make_user(role="admin")
    body, token = _invite(client, auth_headers(admin))
    assert body["email"] == "invited@test.com"
    assert body["role"] == "pending"
    assert body["used_at"] is None
    assert "/register?token=" in body["url"]
    assert len(token) > 30  # 손으로 칠 수 있는 짧은 코드가 아니어야 한다


def test_invite_token_is_stored_hashed_only(client, make_user, auth_headers, db):
    """DB에는 원문이 없다 — 유출돼도 그것만으로는 가입할 수 없어야 한다."""
    admin = make_user(role="admin")
    _, token = _invite(client, auth_headers(admin))
    invite = db.scalar(select(Invite).where(Invite.email == "invited@test.com"))
    assert invite.token_hash != token
    assert invite.token_hash == hash_invite_token(token)


def test_non_admin_cannot_create_invite(client, make_user, auth_headers):
    writer = make_user(role="writer")
    r = client.post(
        "/api/admin/invites",
        json={"email": "x@test.com"},
        headers=auth_headers(writer),
    )
    assert r.status_code == 403


def test_invite_cannot_grant_admin(client, make_user, auth_headers):
    """초대 링크 하나가 관리자 계정이 되면 링크 유출이 곧 사이트 탈취다."""
    admin = make_user(role="admin")
    r = client.post(
        "/api/admin/invites",
        json={"email": "x@test.com", "role": "admin"},
        headers=auth_headers(admin),
    )
    assert r.status_code == 422  # 스키마의 Literal에서 막힌다


def test_unverified_recipient_is_flagged_but_not_blocked(
    client, make_user, auth_headers, monkeypatch
):
    """미검증 주소는 **알려주되 막지 않는다.**

    초대제는 가입에 메일을 안 쓰므로 미검증 주소로도 초대가 정상 동작한다.
    막아버리면 SES 등록을 강제하게 되는데, 그건 이 기능이 벗어나려던 바로 그
    사슬이다(샌드박스). 대신 나중에 비번 재설정이 안 닿는다는 걸 화면이 말해준다."""
    from app.routers import admin as admin_router

    monkeypatch.setattr(
        admin_router, "recipient_status", lambda _e: {"sandbox": True, "verified": False}
    )
    admin = make_user(role="admin")
    body, _ = _invite(client, auth_headers(admin))
    assert body["recipient_verified"] is False  # 발급은 됐다


def test_unknown_ses_status_is_not_a_warning(
    client, make_user, auth_headers, monkeypatch
):
    """'확인 못 함'과 '문제 있음'을 섞으면 안 된다.

    권한이 없거나 자격증명이 없으면 None이 와야 하고, 화면은 그때 아무 말도 안 한다.
    모름을 경고로 바꾸면 늑대 소년이 되어 진짜 경고까지 무시하게 된다."""
    from app.routers import admin as admin_router

    monkeypatch.setattr(
        admin_router, "recipient_status", lambda _e: {"sandbox": None, "verified": None}
    )
    admin = make_user(role="admin")
    body, _ = _invite(client, auth_headers(admin))
    assert body["recipient_verified"] is None


def test_ses_failure_does_not_break_issuing(client, make_user, auth_headers, monkeypatch):
    """SES 조회가 터져도 초대 발급은 끝까지 가야 한다.

    초대 행은 SES를 보기 **전에 이미 커밋**되고 원문 토큰은 그 응답에만 실린다.
    여기서 500이 나가면 초대는 DB에 남는데 링크는 영영 사라져서, 취소하고 다시
    발급하는 수밖에 없다 — 부가 정보가 본 기능을 망치는 전형적인 모양이다."""
    from app.routers import admin as admin_router

    def boom(_email):
        raise RuntimeError("AWS 폭발")

    # 라우터가 import 시점에 바인딩한 이름을 갈아끼워야 실제 호출부가 바뀐다
    monkeypatch.setattr(admin_router, "recipient_status", boom)
    admin = make_user(role="admin")
    r = client.post(
        "/api/admin/invites",
        json={"email": "boom@test.com"},
        headers=auth_headers(admin),
    )
    assert r.status_code == 201
    assert r.json()["url"]  # 링크가 살아서 나왔다
    assert r.json()["recipient_verified"] is None  # 모름으로 떨어졌을 뿐


def test_invite_for_existing_account_rejected(client, make_user, auth_headers):
    admin = make_user(role="admin")
    make_user(role="writer", email="already@test.com")
    r = client.post(
        "/api/admin/invites",
        json={"email": "already@test.com"},
        headers=auth_headers(admin),
    )
    assert r.status_code == 400


def test_invite_for_existing_account_is_case_insensitive(
    client, make_user, auth_headers
):
    """이 앱은 이메일을 정규화하지 않는데 초대만 lower()로 저장한다. 그래서 단순
    동등 비교를 쓰면 대소문자만 다른 중복 계정이 생긴다 — 소각 단계의 unique 제약도
    대소문자를 구분하므로 이 검사가 유일한 방어다."""
    admin = make_user(role="admin")
    make_user(role="writer", email="Mixed@test.com")
    r = client.post(
        "/api/admin/invites",
        json={"email": "mixed@test.com"},
        headers=auth_headers(admin),
    )
    assert r.status_code == 400


def test_second_live_invite_for_same_email_conflicts(client, make_user, auth_headers):
    """유효 링크가 여러 개 떠다니면 '취소했다'가 거짓이 된다."""
    admin = make_user(role="admin")
    _invite(client, auth_headers(admin))
    r = client.post(
        "/api/admin/invites",
        json={"email": "invited@test.com"},
        headers=auth_headers(admin),
    )
    assert r.status_code == 409


def test_expires_days_controls_expiry(client, make_user, auth_headers):
    """만료 '계산'을 건다. 아래 만료 테스트들은 DB에 직접 과거 시각을 써넣으므로
    비교만 검증하고, expires_days가 실제로 쓰이는지는 안 본다 —
    `timedelta(days=7)` 하드코딩이나 days→hours 오타를 그것들은 못 잡는다."""
    admin = make_user(role="admin")
    body, _ = _invite(client, auth_headers(admin), expires_days=1)
    left = datetime.fromisoformat(body["expires_at"]) - datetime.now(UTC)
    assert timedelta(hours=23) < left < timedelta(hours=25)


@pytest.mark.parametrize("days", [0, -1, 31])
def test_expires_days_bounds(client, make_user, auth_headers, days):
    """0·음수는 태어나자마자 죽은 링크, 큰 값은 영원히 사는 링크가 된다."""
    admin = make_user(role="admin")
    r = client.post(
        "/api/admin/invites",
        json={"email": "x@test.com", "expires_days": days},
        headers=auth_headers(admin),
    )
    assert r.status_code == 422


def test_invite_email_is_stored_lowercased(client, make_user, auth_headers):
    """소문자 저장은 중복·중복초대 검사가 성립하는 근거다. 위 검사들은 이미
    소문자인 주소를 보내므로 lower()가 사라져도 초록이다 — 여기서 직접 건다."""
    admin = make_user(role="admin")
    body, token = _invite(client, auth_headers(admin), email="Mixed@Test.com")
    assert body["email"] == "mixed@test.com"
    assert client.post("/api/auth/invite", json={"token": token}).json()["email"] == (
        "mixed@test.com"
    )


def test_expired_invite_can_be_reissued(client, make_user, auth_headers, db):
    """만료된 초대가 409를 계속 물면 그 주소엔 영영 다시 초대할 수 없게 된다."""
    admin = make_user(role="admin")
    _invite(client, auth_headers(admin))
    invite = db.scalar(select(Invite).where(Invite.email == "invited@test.com"))
    invite.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    r = client.post(
        "/api/admin/invites",
        json={"email": "invited@test.com"},
        headers=auth_headers(admin),
    )
    assert r.status_code == 201


# ── 확인(미리보기) ───────────────────────────────────────────────────────────


def test_preview_returns_bound_email(client, make_user, auth_headers):
    admin = make_user(role="admin")
    _, token = _invite(client, auth_headers(admin))
    r = client.post("/api/auth/invite", json={"token": token})
    assert r.status_code == 200
    assert r.json() == {"email": "invited@test.com", "role": "pending"}


def test_preview_needs_no_login(client, make_user, auth_headers):
    """초대받은 사람은 아직 계정이 없다 — 인증을 요구하면 쓸 수가 없다."""
    admin = make_user(role="admin")
    _, token = _invite(client, auth_headers(admin))
    assert client.post("/api/auth/invite", json={"token": token}).status_code == 200


def test_bogus_and_expired_tokens_are_indistinguishable(
    client, make_user, auth_headers, db
):
    """만료·위조를 구분해 알려주면 그 자체가 오라클이 된다."""
    admin = make_user(role="admin")
    _, token = _invite(client, auth_headers(admin))
    invite = db.scalar(select(Invite).where(Invite.email == "invited@test.com"))
    invite.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()

    expired = client.post("/api/auth/invite", json={"token": token})
    bogus = client.post("/api/auth/invite", json={"token": "definitely-not-a-real-token"})
    assert expired.status_code == bogus.status_code == 404
    assert expired.json()["detail"] == bogus.json()["detail"]


def test_preview_rejects_used_invite(client, make_user, auth_headers):
    """이게 없으면 소각된 링크가 계속 상대의 주소와 살아 있는 폼을 보여준다.
    (프론트가 미리보기 성공 여부로 폼을 띄울지 정한다.)"""
    admin = make_user(role="admin")
    _, token = _invite(client, auth_headers(admin))
    client.post(
        "/api/auth/register/invite",
        json={"token": token, "password": "password123"},
    )
    used = client.post("/api/auth/invite", json={"token": token})
    bogus = client.post("/api/auth/invite", json={"token": "nope-not-real"})
    assert used.status_code == 404
    assert used.json()["detail"] == bogus.json()["detail"]


def test_preview_reports_the_invited_role(client, make_user, auth_headers):
    """화면이 '가입 후 글쓰기 되나'를 이 값으로 안내한다."""
    admin = make_user(role="admin")
    _, token = _invite(client, auth_headers(admin), role="writer")
    assert client.post("/api/auth/invite", json={"token": token}).json()["role"] == (
        "writer"
    )


# ── 토큰이 '자기' 초대를 고르는가 ────────────────────────────────────────────
#
# 아래 둘이 없으면 토큰 조회 자체가 전혀 검증되지 않는다. 다른 테스트는 초대를
# 하나만 만들기 때문에 "토큰이 맞는 행을 골랐다"와 "행이 하나뿐이라 그거였다"가
# 구별되지 않는다 — 소각 UPDATE에서 token_hash 조건을 통째로 지워도 전부 초록이다.
# 그 상태의 프로덕션은 **아무 문자열이나 보내면 남의 초대가 소각된다.**


def test_token_selects_its_own_invite(client, make_user, auth_headers):
    admin = make_user(role="admin")
    h = auth_headers(admin)
    _, token_a = _invite(client, h, email="alice@test.com")
    _, token_b = _invite(client, h, email="bob@test.com")

    assert client.post("/api/auth/invite", json={"token": token_b}).json()["email"] == (
        "bob@test.com"
    )
    r = client.post(
        "/api/auth/register/invite",
        json={"token": token_b, "password": "password123"},
    )
    assert r.status_code == 201
    # b를 썼다고 a가 타면 안 된다
    assert client.post("/api/auth/invite", json={"token": token_a}).json()["email"] == (
        "alice@test.com"
    )


def test_bogus_token_cannot_burn_a_live_invite(client, make_user, auth_headers, db):
    """살아 있는 초대가 있는 상태에서 엉터리 토큰을 던진다. 소각 조건에서
    token_hash가 빠지면 여기서 남의 초대가 타면서 계정이 생긴다."""
    admin = make_user(role="admin")
    _invite(client, auth_headers(admin), email="victim@test.com")

    r = client.post(
        "/api/auth/register/invite",
        json={"token": "definitely-not-a-real-token", "password": "password123"},
    )
    assert r.status_code == 400
    invite = db.scalar(select(Invite).where(Invite.email == "victim@test.com"))
    assert invite.used_at is None  # 남의 초대가 타지 않았다
    assert db.scalar(select(User).where(User.email == "victim@test.com")) is None


# ── 소각(가입) ───────────────────────────────────────────────────────────────


def test_redeem_creates_verified_account(client, make_user, auth_headers, db):
    admin = make_user(role="admin")
    _, token = _invite(client, auth_headers(admin))

    r = client.post(
        "/api/auth/register/invite",
        json={"token": token, "password": "password123"},
    )
    assert r.status_code == 201
    assert r.json()["access_token"]  # 바로 로그인된 상태로 돌려준다

    user = db.scalar(select(User).where(User.email == "invited@test.com"))
    # 메일을 한 통도 안 보내고 인증이 끝나 있어야 한다 — SES 샌드박스에서
    # 가입이 성립하는 이유가 바로 이것이다.
    assert user.email_verified is True
    assert user.role == "pending"


def test_redeem_sends_no_mail(client, make_user, auth_headers, sent_mail):
    admin = make_user(role="admin")
    _, token = _invite(client, auth_headers(admin))
    before = len(sent_mail)
    client.post(
        "/api/auth/register/invite",
        json={"token": token, "password": "password123"},
    )
    assert len(sent_mail) == before


def test_redeemed_account_can_log_in(client, make_user, auth_headers):
    admin = make_user(role="admin")
    _, token = _invite(client, auth_headers(admin))
    client.post(
        "/api/auth/register/invite",
        json={"token": token, "password": "password123"},
    )
    r = client.post(
        "/api/auth/login",
        json={"email": "invited@test.com", "password": "password123"},
    )
    assert r.status_code == 200  # 이메일 미인증 403에 걸리지 않는다


def test_invited_user_can_log_in_with_any_capitalization(
    client, make_user, auth_headers
):
    """초대는 주소를 소문자로 저장한다. 그런데 로그인이 원문 그대로 비교하던 시절엔
    'Bob@Test.com'으로 초대받은 사람이 평소 쓰는 대로 치면 맞는 비번인데도 401이었고,
    비번 재설정은 202를 주며 메일을 안 보냈다 — 단서가 하나도 없는 잠금이다."""
    admin = make_user(role="admin")
    _, token = _invite(client, auth_headers(admin), email="Bob@Test.com")
    client.post(
        "/api/auth/register/invite",
        json={"token": token, "password": "password123"},
    )
    r = client.post(
        "/api/auth/login",
        json={"email": "Bob@Test.com", "password": "password123"},
    )
    assert r.status_code == 200


def test_invite_role_writer_skips_approval(client, make_user, auth_headers, db):
    admin = make_user(role="admin")
    _, token = _invite(client, auth_headers(admin), role="writer")
    client.post(
        "/api/auth/register/invite",
        json={"token": token, "password": "password123"},
    )
    user = db.scalar(select(User).where(User.email == "invited@test.com"))
    assert user.role == "writer"


def test_token_is_single_use(client, make_user, auth_headers):
    """같은 링크로 두 번은 못 들어온다."""
    admin = make_user(role="admin")
    _, token = _invite(client, auth_headers(admin))
    first = client.post(
        "/api/auth/register/invite",
        json={"token": token, "password": "password123"},
    )
    second = client.post(
        "/api/auth/register/invite",
        json={"token": token, "password": "another-pw-9"},
    )
    assert first.status_code == 201
    assert second.status_code == 400


def test_expired_token_cannot_redeem(client, make_user, auth_headers, db):
    admin = make_user(role="admin")
    _, token = _invite(client, auth_headers(admin))
    invite = db.scalar(select(Invite).where(Invite.email == "invited@test.com"))
    invite.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    r = client.post(
        "/api/auth/register/invite",
        json={"token": token, "password": "password123"},
    )
    assert r.status_code == 400


def test_redeem_records_who_was_let_in(client, make_user, auth_headers, db):
    admin = make_user(role="admin")
    _, token = _invite(client, auth_headers(admin))
    client.post(
        "/api/auth/register/invite",
        json={"token": token, "password": "password123"},
    )
    invite = db.scalar(select(Invite).where(Invite.email == "invited@test.com"))
    user = db.scalar(select(User).where(User.email == "invited@test.com"))
    assert invite.used_at is not None
    assert invite.used_by_id == user.id
    assert invite.created_by_id == admin.id


def test_redeem_is_blocked_if_the_address_got_taken_meanwhile(
    client, make_user, auth_headers, db
):
    """발급과 소각 사이에 그 주소로 계정이 생긴 경우(IntegrityError 분기).

    핵심은 400이 아니라 **초대가 타지 않는 것**이다. 롤백이 소각까지 되돌리지
    않으면 링크만 잃고 계정은 못 만드는 상태가 된다."""
    admin = make_user(role="admin")
    _, token = _invite(client, auth_headers(admin))
    make_user(role="writer", email="invited@test.com")  # 그 사이 생긴 계정

    r = client.post(
        "/api/auth/register/invite",
        json={"token": token, "password": "password123"},
    )
    assert r.status_code == 400
    invite = db.scalar(select(Invite).where(Invite.email == "invited@test.com"))
    assert invite.used_at is None  # 초대는 살아 있어야 한다


def test_burn_is_atomic_under_concurrency():
    """링크를 동시에 여러 번 열어도 계정은 하나만 생긴다.

    다른 테스트는 전부 순차다(앞 요청이 커밋을 끝낸 뒤 다음이 시작). 여기서만
    **실제 엔드포인트를 여러 스레드로 동시에 때린다.** 롤백되는 트랜잭션 세션을
    쓰지 않는 이유는 각 요청이 자기 커넥션을 가져야 행 잠금이 실제로 걸려서다.
    대신 뒷정리를 직접 한다.

    솔직한 한계 하나 — 이 테스트는 소각을 '읽고 확인한 뒤 표시하는' 방식으로
    바꿔도 통과한다(2026-08-07 변조 테스트로 확인). users.email의 유니크 제약이
    두 번째 INSERT를 막아 결과가 같아지기 때문이다. 즉 여기서 지키는 건
    '계정 하나'라는 **결과**고, 그 결과는 두 겹이 함께 만든다.
    """
    engine = create_engine(settings.database_url)
    token = "atomicity-drill-token-do-not-reuse"
    email = "atomic-drill@test.com"
    attempts = 8

    with engine.begin() as setup:
        setup.execute(
            text(
                "INSERT INTO invites (email, token_hash, role, expires_at) "
                "VALUES (:e, :h, 'pending', now() + interval '1 day')"
            ),
            {"e": email, "h": hash_invite_token(token)},
        )

    codes: list[int] = []
    lock = threading.Lock()
    try:
        # get_db 오버라이드 없는 클라이언트 = 요청마다 진짜 세션(SessionLocal)
        with TestClient(app) as c:

            def attempt():
                r = c.post(
                    "/api/auth/register/invite",
                    json={"token": token, "password": "password123"},
                )
                with lock:
                    codes.append(r.status_code)

            threads = [threading.Thread(target=attempt) for _ in range(attempts)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=20)

        assert len(codes) == attempts, "일부 요청이 끝나지 않았다"
        assert codes.count(201) == 1, f"동시 소각이 {codes.count(201)}건 성공했다"
        with engine.begin() as check:
            made = check.execute(
                text("SELECT count(*) FROM users WHERE email = :e"), {"e": email}
            ).scalar()
        assert made == 1, f"계정이 {made}개 생겼다"
    finally:
        with engine.begin() as cleanup:
            cleanup.execute(text("DELETE FROM users WHERE email = :e"), {"e": email})
            cleanup.execute(text("DELETE FROM invites WHERE email = :e"), {"e": email})
        engine.dispose()


def test_redeem_rejects_short_password(client, make_user, auth_headers):
    admin = make_user(role="admin")
    _, token = _invite(client, auth_headers(admin))
    r = client.post(
        "/api/auth/register/invite", json={"token": token, "password": "short"}
    )
    assert r.status_code == 422


def test_invite_works_while_open_signup_stays_closed(
    client, make_user, auth_headers, monkeypatch
):
    """이 테스트가 이 기능의 존재 이유다.

    초대 가입이 열려도 **열린 가입은 여전히 닫혀 있어야** 한다. 두 문이 같이
    열리면 2026-07-28에 닫은 것이 조용히 되돌아간 것이고, 그건 SES 하드바운스
    누적으로 이어진다.
    (conftest의 autouse open_signup이 기본을 열어두므로 여기서 운영값으로 되돌린다.)"""
    monkeypatch.setattr(settings, "allow_signup", False)
    admin = make_user(role="admin")
    _, token = _invite(client, auth_headers(admin))

    invited = client.post(
        "/api/auth/register/invite",
        json={"token": token, "password": "password123"},
    )
    walk_in = client.post(
        "/api/auth/register",
        json={"email": "stranger@test.com", "password": "password123"},
    )
    assert invited.status_code == 201
    assert walk_in.status_code == 403


# ── 취소 ────────────────────────────────────────────────────────────────────


def test_revoke_unused_invite(client, make_user, auth_headers):
    admin = make_user(role="admin")
    body, token = _invite(client, auth_headers(admin))
    r = client.delete(f"/api/admin/invites/{body['id']}", headers=auth_headers(admin))
    assert r.status_code == 204
    # 취소된 링크는 더 이상 통하지 않는다
    assert client.post("/api/auth/invite", json={"token": token}).status_code == 404


def test_used_invite_cannot_be_deleted(client, make_user, auth_headers):
    """소각 기록을 지우면 '누가 이 계정을 들였나'의 답이 사라진다."""
    admin = make_user(role="admin")
    body, token = _invite(client, auth_headers(admin))
    client.post(
        "/api/auth/register/invite",
        json={"token": token, "password": "password123"},
    )
    r = client.delete(f"/api/admin/invites/{body['id']}", headers=auth_headers(admin))
    assert r.status_code == 400


def test_revoke_missing_invite_404(client, make_user, auth_headers):
    admin = make_user(role="admin")
    assert client.delete(
        "/api/admin/invites/999999", headers=auth_headers(admin)
    ).status_code == 404


def test_list_invites_hides_token(client, make_user, auth_headers):
    admin = make_user(role="admin")
    _invite(client, auth_headers(admin))
    r = client.get("/api/admin/invites", headers=auth_headers(admin))
    assert r.status_code == 200
    row = r.json()[0]
    assert "token" not in row and "token_hash" not in row and "url" not in row


def test_list_shows_who_issued_and_who_joined(client, make_user, auth_headers):
    """감사 기록을 화면에서 실제로 답할 수 있어야 한다. 컬럼에만 쓰고 안 보여주면
    관리자가 그 답을 얻으려고 결국 psql을 열어야 한다."""
    admin = make_user(role="admin", email="boss@test.com")
    h = auth_headers(admin)
    body, token = _invite(client, h)
    assert body["created_by_email"] == "boss@test.com"  # 발급 응답에도 바로 들어간다
    assert body["used_by_email"] is None

    client.post(
        "/api/auth/register/invite",
        json={"token": token, "password": "password123"},
    )
    row = client.get("/api/admin/invites", headers=h).json()[0]
    assert row["created_by_email"] == "boss@test.com"
    assert row["used_by_email"] == "invited@test.com"


def test_list_survives_a_deleted_issuer(client, make_user, auth_headers, db):
    """발급자 계정이 지워지면 FK가 SET NULL이다. inner join이면 그 줄이 목록에서
    통째로 사라져 — 감사 기록을 남긴다면서 정작 못 보게 된다."""
    boss = make_user(role="admin", email="boss@test.com")
    other = make_user(role="admin", email="other@test.com")
    _invite(client, auth_headers(boss))
    db.delete(boss)
    db.commit()

    rows = client.get("/api/admin/invites", headers=auth_headers(other)).json()
    assert len(rows) == 1  # 줄이 사라지지 않는다
    assert rows[0]["created_by_email"] is None


def test_list_shows_used_invites_newest_first(client, make_user, auth_headers):
    """사용된 것도 남긴다 — '누구를 언제 들였나'가 초대제의 감사 기록이라서다.
    한 건만 두고 [0]을 보면 순서도 '사용된 것 포함'도 검증되지 않는다."""
    admin = make_user(role="admin")
    h = auth_headers(admin)
    _, first = _invite(client, h, email="first@test.com")
    _invite(client, h, email="second@test.com")
    client.post(
        "/api/auth/register/invite",
        json={"token": first, "password": "password123"},
    )

    rows = client.get("/api/admin/invites", headers=h).json()
    assert [r["email"] for r in rows] == ["second@test.com", "first@test.com"]
    assert rows[1]["used_at"] is not None  # 소각된 것이 목록에서 사라지지 않는다


def test_list_survives_a_malformed_issuer_email(client, make_user, auth_headers, db):
    """발급자 이메일 형식이 어긋나도 **초대 목록 전체가 죽지 않는다** (09-04 검사 SEC-03).

    `UserRead.email` 은 08-11에 EmailStr → str 로 내렸는데(그 이유가 '한 행이 목록
    전체를 500 으로 만든다'였다), 08-07에 생긴 `InviteOut` 은 users.email 을 실어오는
    두 필드에 EmailStr 을 그대로 썼다. 그래서 같은 레거시 행 하나로 이 화면만 터진다 —
    `/admin/users` 는 멀쩡한데 `/admin/invites` 만 500 이 되는, 두 화면이 갈리는 모양이다.
    하필 이 화면이 '누구를 언제 들였나'의 유일한 답이다.
    """
    from app.models.user import User

    viewer = make_user(role="admin")
    # 앱 경로로는 못 만드는 값을 DB에 직접 심는다(과거 데이터·psql 경로)
    issuer = User(
        email="legacy@test.local",  # 예약 TLD — EmailStr 이 거부한다
        hashed_password="x",
        role="admin",
        email_verified=True,
    )
    db.add(issuer)
    db.commit()
    db.refresh(issuer)
    _invite(client, auth_headers(issuer))

    r = client.get("/api/admin/invites", headers=auth_headers(viewer))
    assert r.status_code == 200, r.text
    assert r.json()[0]["created_by_email"] == "legacy@test.local"

"""관리자 사용자 관리 — 최고권한 작업이라 인가·자기잠금방지·세션무효화에 집중."""


def test_admin_routes_require_admin(client, make_user, auth_headers):
    writer = make_user(role="writer")
    # 라우터 전체가 require_admin → 일반 writer 403, 비인증 401
    assert client.get("/api/admin/users", headers=auth_headers(writer)).status_code == 403
    assert client.get("/api/admin/users").status_code == 401


def test_list_users_excludes_unverified(client, make_user, auth_headers):
    admin = make_user(role="admin")
    make_user(role="writer", verified=True)
    make_user(role="pending", verified=False)  # 미인증 → 목록 제외
    r = client.get("/api/admin/users", headers=auth_headers(admin))
    assert r.status_code == 200
    assert all(u["email_verified"] for u in r.json())  # 미인증 하나도 없음


def test_approve_pending_to_writer(client, make_user, auth_headers):
    admin = make_user(role="admin")
    pending = make_user(role="pending")
    r = client.post(f"/api/admin/users/{pending.id}/approve", headers=auth_headers(admin))
    assert r.status_code == 200
    assert r.json()["role"] == "writer"


def test_revoke_writer_to_pending(client, make_user, auth_headers):
    admin = make_user(role="admin")
    writer = make_user(role="writer")
    r = client.post(f"/api/admin/users/{writer.id}/revoke", headers=auth_headers(admin))
    assert r.status_code == 200
    assert r.json()["role"] == "pending"


def test_cannot_modify_or_delete_admin_account(client, make_user, auth_headers):
    admin = make_user(role="admin")
    target_admin = make_user(role="admin")
    for action in ("approve", "revoke", "ban"):
        r = client.post(
            f"/api/admin/users/{target_admin.id}/{action}", headers=auth_headers(admin)
        )
        assert r.status_code == 400, action
    d = client.delete(f"/api/admin/users/{target_admin.id}", headers=auth_headers(admin))
    assert d.status_code == 400


def test_ban_revokes_existing_token(client, make_user, auth_headers):
    admin = make_user(role="admin")
    victim = make_user(role="writer")
    victim_headers = auth_headers(victim)  # 밴 이전 발급 토큰(token_version=0)

    # 밴 전엔 통함
    assert client.get("/api/auth/me", headers=victim_headers).status_code == 200

    r = client.post(f"/api/admin/users/{victim.id}/ban", headers=auth_headers(admin))
    assert r.status_code == 200
    assert r.json()["role"] == "banned"

    # 밴 즉시 기존 토큰 무효 (token_version++로 세션 강제 종료)
    assert client.get("/api/auth/me", headers=victim_headers).status_code == 401


def test_unban_non_banned_400(client, make_user, auth_headers):
    admin = make_user(role="admin")
    writer = make_user(role="writer")
    r = client.post(f"/api/admin/users/{writer.id}/unban", headers=auth_headers(admin))
    assert r.status_code == 400


def test_unban_banned_to_pending(client, make_user, auth_headers):
    admin = make_user(role="admin")
    banned = make_user(role="banned")
    r = client.post(f"/api/admin/users/{banned.id}/unban", headers=auth_headers(admin))
    assert r.status_code == 200
    assert r.json()["role"] == "pending"  # 재승인 필요 상태로


def test_toggle_pro(client, make_user, auth_headers):
    admin = make_user(role="admin")
    u = make_user(role="writer", is_pro=False)
    on = client.post(f"/api/admin/users/{u.id}/toggle-pro", headers=auth_headers(admin))
    assert on.json()["is_pro"] is True
    off = client.post(f"/api/admin/users/{u.id}/toggle-pro", headers=auth_headers(admin))
    assert off.json()["is_pro"] is False


def test_toggle_pro_clears_stale_expiry(client, make_user, auth_headers, db):
    """관리자가 켠 Pro가 다음 요청에 조용히 꺼지던 버그를 잠근다.

    admin.py가 `if user.is_pro: user.pro_until = None`을 하는 이유가 그 사고인데,
    위 test_toggle_pro는 is_pro=False로 시작해 pro_until이 처음부터 NULL이라
    **그 두 줄을 지워도 통과했다**(2026-08-11 공백검사). 과거 결제의 만료가 남은
    상태에서 켜야 실제 경로를 탄다 — 안 그러면 deps.py의 _expire_pro_if_due가
    다음 요청에서 즉시 되돌린다.
    """
    from datetime import UTC, datetime, timedelta

    from app.models.user import User

    admin = make_user(role="admin")
    u = make_user(role="writer", is_pro=False)
    # 과거 결제가 남긴 만료: 이미 지난 시각
    db.query(User).filter(User.id == u.id).update(
        {"pro_until": datetime.now(UTC) - timedelta(days=1)}
    )
    db.commit()

    r = client.post(f"/api/admin/users/{u.id}/toggle-pro", headers=auth_headers(admin))
    assert r.json()["is_pro"] is True
    assert db.get(User, u.id).pro_until is None, "낡은 pro_until이 안 지워졌다"

    # 다음 요청에서도 살아 있어야 한다(여기가 조용히 꺼지던 자리)
    still = client.get("/api/auth/me", headers=auth_headers(u))
    assert still.json()["is_pro"] is True, "관리자가 켠 Pro가 다음 요청에 꺼졌다"


def test_delete_user_removes_their_posts(client, make_user, auth_headers):
    admin = make_user(role="admin")
    u = make_user(role="writer")
    client.post("/api/posts", headers=auth_headers(u), json={"title": "T", "content": "C"})

    r = client.delete(f"/api/admin/users/{u.id}", headers=auth_headers(admin))
    assert r.status_code == 204
    # 삭제 후 그 유저는 사라짐(다시 조작 시 404)
    assert (
        client.post(f"/api/admin/users/{u.id}/approve", headers=auth_headers(admin)).status_code
        == 404
    )


def test_action_on_unknown_user_404(client, make_user, auth_headers):
    admin = make_user(role="admin")
    assert (
        client.post("/api/admin/users/999999/approve", headers=auth_headers(admin)).status_code
        == 404
    )


def test_admin_list_survives_a_malformed_email_row(client, make_user, auth_headers, db):
    """DB에 형식이 어긋난 이메일이 있어도 **목록 전체가 죽지 않는다.**

    `UserRead.email`이 EmailStr이던 시절엔 그런 행 하나로 `GET /admin/users`가
    응답 검증에서 터져 500이 났다. 그리고 그 계정을 지울 유일한 화면이 바로 그
    목록이라 **복구 경로가 psql뿐**이었다 — 2026-08-11 동적 분석에서 실제로 재현했다
    (500 → psql 삭제 → 200). 형식 강제는 입구(create_user.py·UserCreate)의 일이고,
    출구에서 다시 검증해봐야 지키는 건 없이 '한 행이 전체를 죽이는' 실패만 만든다.
    """
    from app.models.user import User

    admin = make_user(role="admin")
    # 앱 경로로는 못 만드는 값을 DB에 직접 심는다(과거 데이터·psql·마이그레이션 경로)
    db.add(
        User(
            email="broken@test.local",  # 예약 TLD — EmailStr이 거부한다
            hashed_password="x",
            role="pending",
            email_verified=True,
        )
    )
    db.commit()

    r = client.get("/api/admin/users", headers=auth_headers(admin))
    assert r.status_code == 200, r.text
    emails = [u["email"] for u in r.json()]
    assert "broken@test.local" in emails, "지울 수 있으려면 목록에 보여야 한다"

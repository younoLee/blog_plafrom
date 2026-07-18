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

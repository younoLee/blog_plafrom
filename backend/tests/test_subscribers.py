"""이메일 뉴스레터 구독 폐지(2026-07-31) 이후 남은 계약.

폐지 사유는 `app/routers/subscribers.py`에. 요지는 셋이다 —
확인해도 후속 메일이 없는 막다른 길이었고, SES 샌드박스에서 조용히 사라졌고,
그러면서 방문자에겐 "확인 메일을 보냈어"라고 답하고 있었다.

여기서 못박는 건 둘이다:
  ① 임의의 주소로 메일을 쏘던 경로가 **정말로 없어졌는가** (SES 판단의 근거가 이것이다)
  ② 관리자가 폐지 전에 쌓인 주소(개인정보)를 여전히 조회·삭제할 수 있는가
"""
from sqlalchemy import select

from app.models.subscriber import Subscriber

# 폐지된 공개 경로들. 살아 있으면 임의 주소로 메일이 나갈 수 있다.
RETIRED = [
    ("post", "/api/subscribers", {"json": {"email": "x@test.com"}}),
    ("post", "/api/subscribers/confirm?token=whatever", {}),
    ("post", "/api/subscribers/unsubscribe", {"json": {"email": "x@test.com"}}),
    ("get", "/api/subscribers/me", {}),
    ("post", "/api/subscribers/me", {}),
    ("delete", "/api/subscribers/me", {}),
]


def test_retired_routes_never_succeed(client):
    """폐지된 경로는 어느 것도 성공해서는 안 된다.

    '404여야 한다'가 아니라 '성공하면 안 된다'로 적는 이유: 남겨둔 관리자 경로
    `DELETE /subscribers/{id}`가 `/me`와 모양이 같아서, `DELETE /subscribers/me`는
    404가 아니라 인증 검사에 먼저 걸려 401이 된다(관리자 토큰을 줘도 'me'가 int가
    아니라 422다). 상태코드를 못박으면 그 우연한 값을 계약으로 만들어버린다.
    중요한 건 **옛 동작(204로 내 구독 해제)이 사라졌다**는 것이다.
    """
    for method, path, kwargs in RETIRED:
        r = getattr(client, method)(path, **kwargs)
        assert not (200 <= r.status_code < 300), f"{method.upper()} {path} → {r.status_code}"


def test_public_subscribe_endpoint_is_gone(client):
    """`POST /api/subscribers`는 특히 확실히 없어야 한다.

    이 앱에서 **검증 안 된 임의 주소로 메일이 나가던 유일한 경로**였다.
    'SES 프로덕션 액세스가 필요 없다'는 판단이 이게 없다는 사실 위에 서 있으므로,
    되살아나면 그 판단도 같이 무너진다.
    """
    r = client.post("/api/subscribers", json={"email": "stranger@test.com"})
    assert r.status_code in (404, 405)


def test_subscribe_confirm_email_sender_is_gone():
    """확인 메일 발송 함수 자체가 없어야 한다. 남아 있으면 누가 다시 부른다."""
    from app.services import email

    assert not hasattr(email, "send_subscribe_confirm_email")


# ── 관리자만 PII 목록 (폐지 후에도 남는 정리 수단) ──────────────────────────
def test_list_subscribers_admin_only(client, make_user, auth_headers, db):
    db.add(Subscriber(email="a@test.com", confirmed=True))
    db.commit()
    writer = make_user(role="writer")
    admin = make_user(role="admin")

    assert client.get("/api/subscribers", headers=auth_headers(writer)).status_code == 403
    assert client.get("/api/subscribers").status_code == 401
    ok = client.get("/api/subscribers", headers=auth_headers(admin))
    assert ok.status_code == 200
    assert any(s["email"] == "a@test.com" for s in ok.json())


def test_admin_can_delete_leftover_subscriber(client, make_user, auth_headers, db):
    """폐지 전에 쌓인 주소를 지울 수 있어야 한다 — 개인정보라 조회만 되면 곤란하다."""
    sub = Subscriber(email="leftover@test.com", confirmed=True)
    db.add(sub)
    db.commit()
    db.refresh(sub)
    admin = make_user(role="admin")

    assert client.delete(f"/api/subscribers/{sub.id}", headers=auth_headers(admin)).status_code == 204
    assert db.scalar(select(Subscriber).where(Subscriber.id == sub.id)) is None


def test_remove_subscriber_unknown_404(client, make_user, auth_headers):
    admin = make_user(role="admin")
    assert client.delete("/api/subscribers/999999", headers=auth_headers(admin)).status_code == 404

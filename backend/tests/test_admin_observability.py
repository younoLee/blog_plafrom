"""관리자 화면이 '로그에만 있던 것'을 보게 됐는가 (2026-08-27 신설).

두 자리가 같은 모양이었다. 서버는 정확히 알고 있는데 **그 사실이 화면에 한 줄도
없어서**, 확인하려면 대부분 꺼져 있는 EC2 를 켜고 SSH 로 들어가 로그나 psql 을
봐야 했다.

  · AI 가드 위반과 그로 인한 자동 제한 — 테이블은 진작 있었고 429 로 막고도 있었다
  · 알림 발송 결과 — tried/ok 를 08-27 에 정확히 갈랐는데 로그로만 나갔다

가드 쪽은 특히 사용자에게도 뭉뚱그려 안내된다(몇 번 걸렸고 몇 번 남았는지 알려주면
공격자에겐 계기판이 된다). **관리자조차 못 보면 아무도 못 본다.**
"""

from datetime import UTC, datetime

from app.models.ai_usage import AiGuardViolation


def _hour():
    return datetime.now(UTC).replace(minute=0, second=0, microsecond=0)


def test_ai_guard_requires_admin(client, make_user, auth_headers):
    writer = make_user(role="writer")
    assert client.get("/api/admin/ai-guard").status_code == 401
    assert client.get("/api/admin/ai-guard", headers=auth_headers(writer)).status_code == 403


def test_ai_guard_empty_is_a_valid_answer(client, make_user, auth_headers):
    """비어 있음 자체가 정보다 — 정상 사용자는 평생 0이다."""
    admin = make_user(role="admin")
    body = client.get("/api/admin/ai-guard", headers=auth_headers(admin)).json()
    assert body["items"] == []
    assert body["cap"] >= 1


def test_ai_guard_lists_violations_and_blocked_flag(client, make_user, auth_headers, db):
    """`blocked` 판정은 **서버가 한다.**

    화면이 count 와 cap 을 받아 스스로 비교하면, 백엔드가 임계를 바꿔도 화면은 옛
    기준으로 그린다. 이 저장소는 같은 날 디스크 임계에서 그 모양을 고쳤다.
    """
    admin = make_user(role="admin")
    bad = make_user(role="writer", display_name="두드리는사람")
    cap = client.get("/api/admin/ai-guard", headers=auth_headers(admin)).json()["cap"]

    db.add(AiGuardViolation(user_id=bad.id, hour=_hour(), count=cap))
    db.commit()

    body = client.get("/api/admin/ai-guard", headers=auth_headers(admin)).json()
    row = next(i for i in body["items"] if i["user_id"] == bad.id)
    assert row["count"] == cap
    assert row["blocked"] is True
    assert row["name"] == "두드리는사람"


def test_ai_guard_below_cap_is_not_blocked(client, make_user, auth_headers, db):
    admin = make_user(role="admin")
    u = make_user(role="writer")
    db.add(AiGuardViolation(user_id=u.id, hour=_hour(), count=1))
    db.commit()

    body = client.get("/api/admin/ai-guard", headers=auth_headers(admin)).json()
    row = next(i for i in body["items"] if i["user_id"] == u.id)
    assert row["blocked"] is False


def test_ai_guard_does_not_leak_email(client, make_user, auth_headers, db):
    """이메일은 안 내보낸다 — 관리자 화면의 다른 목록과 같은 규칙이다."""
    admin = make_user(role="admin")
    u = make_user(role="writer", email="secret@test.com")
    db.add(AiGuardViolation(user_id=u.id, hour=_hour(), count=1))
    db.commit()

    raw = client.get("/api/admin/ai-guard", headers=auth_headers(admin)).text
    assert "secret@test.com" not in raw


def test_infra_carries_last_push_key(client, make_user, auth_headers):
    """아직 발송이 없으면 None 이지만 **키는 있어야 한다.**

    키가 사라지면 프론트가 그 카드를 조용히 안 그린다(선택값으로 다룬다).
    '알림이 안 나갔다'와 '화면이 안 그린다'가 구분되지 않는 상태가 된다.
    """
    admin = make_user(role="admin")
    body = client.get("/api/admin/infra", headers=auth_headers(admin)).json()
    assert "last_push" in body


def test_last_delivery_records_tried_and_ok(monkeypatch):
    """발송 결과가 실제로 기록되는가.

    tried 와 ok 를 가른 것이 08-27 훈련의 소득이었다(예전엔 sent 하나였고 예외를 삼킨
    뒤에도 증가해서 "5/20대에서 중단"이 '5대는 받았다'로 읽혔다). 그 구분이 화면까지
    이어지는지 본다.
    """
    from app.services import push

    sent: list[str] = []

    def fake_send(endpoint, p256dh, auth, data):
        sent.append(endpoint)
        if len(sent) == 2:
            raise RuntimeError("벤더가 아프다")

    monkeypatch.setattr(push, "send_push", fake_send)
    subs = [(i, f"https://fcm.googleapis.com/x{i}", "p", "a") for i in range(3)]
    push._deliver(subs, {"title": "t", "body": "본문", "tag": "new-post"})

    last = push.last_delivery()
    assert last is not None
    assert last["targets"] == 3
    assert last["tried"] == 3
    assert last["ok"] == 2  # 하나는 실패 — tried 와 다르다
    assert last["budget_hit"] is False
    assert last["title"] == "본문"


# ── AI 사용량 (09-04 검사 BQ-7) ──────────────────────────────────────────────
#
# `GET /api/admin/ai-usage` 는 라우트 전체가 시험 0건이었다. 이 화면이 하는 일은
# Anthropic 청구를 보는 **유일한 창**이다 — 그 청구는 AWS 밖이라 watch.sh 가 보는
# AWS Budgets 가 원리적으로 못 본다. 여기가 조용히 틀리면 다음 명세서까지 아무도 모른다.


def _seed_usage(db, user_id: int, *, days_ago: int = 0, calls: int = 1, tin: int = 0, tout: int = 0):
    from datetime import timedelta

    from app.models.ai_usage import AiUsage
    from app.services.ai_usage import today

    db.add(
        AiUsage(
            user_id=user_id,
            day=today() - timedelta(days=days_ago),
            count=calls,
            input_tokens=tin,
            output_tokens=tout,
        )
    )
    db.commit()


def test_ai_usage_requires_admin(client, make_user, auth_headers):
    writer = make_user(role="writer")
    assert client.get("/api/admin/ai-usage").status_code == 401
    assert client.get("/api/admin/ai-usage", headers=auth_headers(writer)).status_code == 403


def test_오늘_숫자는_시드_합과_같다(client, make_user, auth_headers, db):
    admin = make_user(role="admin")
    a = make_user(role="writer")
    b = make_user(role="writer")
    _seed_usage(db, a.id, calls=3, tin=100, tout=50)
    _seed_usage(db, b.id, calls=2, tin=10, tout=5)

    today_block = client.get("/api/admin/ai-usage", headers=auth_headers(admin)).json()["today"]
    assert today_block["calls"] == 5
    assert today_block["tokens"] == 165
    assert today_block["calls_cap"] >= 1  # 상한 없이 숫자만 보면 많은지 적은지 모른다


def test_추이는_14일_창_밖을_뺀다(client, make_user, auth_headers, db):
    """창이 없으면 이 표는 계정이 살아 있는 내내 길어진다. 경계(13일 전은 포함,
    14일 전은 제외)를 못박아 둔다 — '평소 대비 튀었는가'가 이 표의 용도다."""
    admin = make_user(role="admin")
    u = make_user(role="writer")
    _seed_usage(db, u.id, days_ago=13, calls=7)
    _seed_usage(db, u.id, days_ago=14, calls=99)

    daily = client.get("/api/admin/ai-usage", headers=auth_headers(admin)).json()["daily"]
    assert sum(d["calls"] for d in daily) == 7


def test_상위_사용자는_이메일을_안_흘린다(client, make_user, auth_headers, db):
    """가드 목록과 같은 규칙이다 — 표시명 폴백(`회원 #id`)을 쓰고 이메일은 안 내보낸다.
    관리자 화면이라도 이메일을 실어 보내면 그게 다시 다른 응답으로 새는 경로가 된다."""
    admin = make_user(role="admin")
    u = make_user(role="writer", email="secret@test.com")
    _seed_usage(db, u.id, calls=1, tin=1, tout=1)

    body = client.get("/api/admin/ai-usage", headers=auth_headers(admin)).text
    assert "secret@test.com" not in body
    top = client.get("/api/admin/ai-usage", headers=auth_headers(admin)).json()["top_users_month"]
    assert top[0]["user_id"] == u.id
    assert top[0]["name"] == f"회원 #{u.id}"


def test_이번_달_1일_경계를_지킨다(client, make_user, auth_headers, db):
    """지난달 사용량이 이번 달 표에 섞이면 '이번 달 얼마 썼나'가 뜻을 잃는다."""
    from datetime import timedelta

    from app.services.ai_usage import today

    admin = make_user(role="admin")
    u = make_user(role="writer")
    day = today()
    last_month = day.replace(day=1) - timedelta(days=1)
    _seed_usage(db, u.id, days_ago=(day - last_month).days, calls=50, tin=1000, tout=1000)
    _seed_usage(db, u.id, calls=1, tin=1, tout=1)

    top = client.get("/api/admin/ai-usage", headers=auth_headers(admin)).json()["top_users_month"]
    assert top[0]["tokens"] == 2  # 지난달 2000 토큰이 안 섞인다

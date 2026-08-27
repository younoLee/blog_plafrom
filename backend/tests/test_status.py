"""상태점검·업타임 집계 서비스. 백그라운드 레코더 스레드에 의존하지 않고
순수 함수(run_checks / get_latest 캐시 / get_history 집계)를 직접 건다."""
from app.services import status


def test_run_checks_shape():
    c = status.run_checks()
    assert c["backend_ok"] is True  # 이 코드가 도는 것 = 백엔드 정상
    assert c["database_ok"] is True  # 테스트 DB 연결됨
    assert isinstance(c["posts"], int)
    assert isinstance(c["subscribers"], int)
    assert "mail_ok" in c  # 값은 환경(메일서버 유무)따라 달라 존재만 확인


def test_get_latest_returns_cache(monkeypatch):
    sentinel = {
        "backend_ok": True, "database_ok": True, "mail_ok": False,
        "posts": 1, "subscribers": 2,
    }
    monkeypatch.setattr(status, "_latest", sentinel)
    # 캐시가 있으면 라이브 점검 없이 그대로 반환
    assert status.get_latest() is sentinel


def test_get_latest_cold_start_runs_live(monkeypatch):
    monkeypatch.setattr(status, "_latest", None)
    c = status.get_latest()  # 캐시 없으면 그 자리에서 한 번 점검
    assert c["backend_ok"] is True
    assert "database_ok" in c


def test_get_history_structure():
    days = 7
    h = status.get_history(days=days)
    # 서비스 4개(backend/database/mail/disk) 각각 일별 집계.
    # disk는 2026-08-10 추가 — /api/status에 실으면서 기록·집계까지 같이 붙였다.
    assert {s["name"] for s in h["services"]} == {"backend", "database", "mail", "disk"}
    for s in h["services"]:
        assert len(s["days"]) == days  # 요청한 일수만큼 날짜 채움(빈 날은 None)
        for d in s["days"]:
            assert set(d.keys()) == {"date", "uptime", "checks"}
        # overall은 None(데이터 없음) 또는 0~1 비율
        assert s["overall_uptime"] is None or 0.0 <= s["overall_uptime"] <= 1.0
    assert isinstance(h["total_checks"], int)


def test_get_history_clamped_days():
    # 하루짜리도 구조가 성립(경계)
    h = status.get_history(days=1)
    assert all(len(s["days"]) == 1 for s in h["services"])


def test_run_checks_includes_disk():
    """run_checks는 항상 disk_ok를 낸다.

    main.py의 /api/status가 `c["disk_ok"]`를 폴백 없이 읽으므로 이게 계약이다.
    처음엔 `.get("disk_ok", True)`로 뒀는데, 그 폴백은 도달 불가능한 죽은 코드였고
    기본값 True가 '못 쟀으면 초록으로 넘기지 않는다'는 방침과 정반대였다(2026-08-10).
    """
    c = status.run_checks()
    assert "disk_ok" in c
    assert isinstance(c["disk_ok"], bool)


def test_disk_history_does_not_count_unmeasured_days_as_up():
    """disk_ok가 NULL인 행을 '정상'으로 세지 않는다.

    이 컬럼은 2026-08-10에 nullable로 추가됐고 그 전 행이 수만 개다. 분모를 전체 점검
    수로 잡으면 **안 쟀던 날이 '디스크 0% 정상'으로** 칠해진다 — 이 저장소가 반복해서
    경계하는 '초록으로 썩는 검사'의 정확한 모양이라 회귀 테스트로 못박는다.

    절대값이 아니라 **증분**을 본다. 같은 세션의 다른 테스트가 status_checks에 행을
    남길 수 있어서 빈 테이블을 가정하면 안 된다(처음에 그렇게 썼다가 깨졌다).
    db 픽스처(롤백 트랜잭션)도 못 쓴다 — get_history가 engine.connect()로 별도
    커넥션을 열어 픽스처 안의 미커밋 행을 못 본다. 그래서 실제로 커밋하고 finally에서
    넣은 id만 정확히 지운다.
    """
    from datetime import UTC, datetime

    from sqlalchemy import delete

    from app.core.database import SessionLocal
    from app.models.status_check import StatusCheck

    def today_checks(name: str) -> int:
        h = status.get_history(days=1)
        return next(s for s in h["services"] if s["name"] == name)["days"][0]["checks"]

    base_disk = today_checks("disk")
    base_backend = today_checks("backend")

    now = datetime.now(UTC)
    rows = [
        StatusCheck(checked_at=now, backend_ok=True, database_ok=True, mail_ok=True, disk_ok=None),
        StatusCheck(checked_at=now, backend_ok=True, database_ok=True, mail_ok=True, disk_ok=None),
        StatusCheck(checked_at=now, backend_ok=True, database_ok=True, mail_ok=True, disk_ok=True),
    ]
    session = SessionLocal()
    ids = []
    try:
        session.add_all(rows)
        session.commit()
        ids = [r.id for r in rows]

        # 세 행을 넣었는데 disk 분모는 **1만** 늘어야 한다(NULL 2개는 '안 쟀다').
        assert today_checks("disk") - base_disk == 1
        # 대조군: backend는 세 행 전부 값이 있으므로 분모가 3 늘어난다.
        assert today_checks("backend") - base_backend == 3
    finally:
        if ids:
            session.execute(delete(StatusCheck).where(StatusCheck.id.in_(ids)))
            session.commit()
        session.close()


# ── 낡은 응답을 낡았다고 말하는가 (2026-08-27) ──────────────────────────────
#
# 08-27 카오스 훈련이 잡은 것: DB를 얼렸는데 /api/status가 884초 동안 database=ok를
# 내보냈다. 캐시가 낡은 게 아니라 값이 나이를 안 먹었다 — 레코더 스레드가 같이 얼어서
# 얼기 직전 값이 그대로 남았다. 그 경로는 점검 전용 엔진에 상한을 줘서 닫혔지만,
# 레코더가 다른 이유로 멈추면 같은 모양이 된다.
#
# 그래서 **낡았다는 사실 자체를 응답이 말하게** 했다. 판정을 화면이 아니라 서버가
# 하는 이유는, 화면마다 임계를 정하면 상태 페이지와 watch.sh가 같은 순간에 다른
# 답을 내기 때문이다(이 저장소는 디스크 임계에서 이미 그 모양을 겪었다).
from datetime import UTC, datetime, timedelta  # noqa: E402

from app.services import status as status_svc  # noqa: E402


def _freeze_latest(monkeypatch, age_seconds: float):
    at = (datetime.now(UTC) - timedelta(seconds=age_seconds)).isoformat()
    monkeypatch.setattr(
        status_svc,
        "get_latest",
        lambda: {
            "at": at,
            "backend_ok": True,
            "database_ok": True,
            "mail_ok": True,
            "disk_ok": True,
            "posts": 1,
            "subscribers": 0,
        },
    )
    # main.py는 import 시점에 이름을 가져가므로 그쪽도 바꿔야 한다.
    from app import main as main_mod

    monkeypatch.setattr(main_mod, "get_latest", status_svc.get_latest)


def test_fresh_status_is_not_stale(client, monkeypatch):
    _freeze_latest(monkeypatch, 5)
    body = client.get("/api/status").json()
    assert body["stale"] is False
    assert body["checked_age_seconds"] < 30


def test_old_status_is_marked_stale(client, monkeypatch):
    """884초짜리 거짓말이 이제는 stale=true 를 달고 나간다."""
    _freeze_latest(monkeypatch, 884)
    body = client.get("/api/status").json()
    assert body["stale"] is True
    assert body["checked_age_seconds"] >= 880
    # **값 자체는 그대로 내보낸다.** 낡았다고 지어내지 않는다 — 마지막으로 잰 것이
    # 무엇이었는지도 사고 중에는 정보다. 화면이 '믿지 말라'를 같이 그린다.
    assert body["database"] == "ok"


def test_stale_boundary_is_three_intervals(client, monkeypatch):
    """임계가 조용히 바뀌면 여기서 걸린다.

    1주기는 갱신 직전에 늘 참이라 상시 경고가 되고, 2주기는 한 번 걸러도 바로 걸린다.
    셋이면 '한 번 놓친 것'과 '멈춘 것'이 갈린다.
    """
    assert status_svc.STALE_AFTER == status_svc.RECORD_INTERVAL * 3
    _freeze_latest(monkeypatch, status_svc.STALE_AFTER - 5)
    assert client.get("/api/status").json()["stale"] is False

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
    # 서비스 3개(backend/database/mail) 각각 일별 집계
    assert {s["name"] for s in h["services"]} == {"backend", "database", "mail"}
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

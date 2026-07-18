"""서비스 상태 점검 + 기록(업타임) 로직.

- run_checks(): 지금 이 순간 상태를 점검해서 반환 (실시간 /status 가 사용)
- record_check(): 점검 결과를 status_checks 테이블에 1줄 저장
- start_recorder(): 1분마다 record_check() 도는 백그라운드 스레드 시작 (앱 기동 시)
- get_history(days): 일별 업타임 집계 (업타임 페이지가 사용)
"""

import socket
import threading
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.models.status_check import StatusCheck

# 자가 점검 기록 간격(초)
RECORD_INTERVAL = 60

# 마지막 점검 결과 캐시 — /status가 매 호출마다 라이브 점검(특히 SMTP 2초)하지 않도록.
# 백그라운드 레코더가 RECORD_INTERVAL마다 갱신한다.
_latest: dict | None = None


def run_checks() -> dict:
    """백엔드/DB/메일 점검 + 통계(글·구독자 수)를 한 번에."""
    # DB 점검 + 통계를 한 연결에서
    db_ok = True
    post_count = None
    subscriber_count = None
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
            post_count = conn.execute(text("select count(*) from posts")).scalar()
            subscriber_count = conn.execute(
                text("select count(*) from subscribers")
            ).scalar()
    except Exception:
        db_ok = False

    # 메일 점검: Mailpit SMTP 포트에 소켓이 연결되는지만 확인
    mail_ok = True
    try:
        with socket.create_connection(
            (settings.smtp_host, settings.smtp_port), timeout=2
        ):
            pass
    except Exception:
        mail_ok = False

    return {
        "backend_ok": True,  # 이 코드가 도는 것 자체가 백엔드 동작
        "database_ok": db_ok,
        "mail_ok": mail_ok,
        "posts": post_count,
        "subscribers": subscriber_count,
    }


def record_check() -> None:
    """점검 결과 한 줄을 status_checks 에 저장 + 최신값 캐시 (백그라운드용 자체 세션)."""
    global _latest
    c = run_checks()
    _latest = c  # /status가 이 캐시를 읽음 (매 호출 SMTP 연결 제거)
    db = SessionLocal()
    try:
        db.add(
            StatusCheck(
                backend_ok=c["backend_ok"],
                database_ok=c["database_ok"],
                mail_ok=c["mail_ok"],
            )
        )
        db.commit()
    finally:
        db.close()


def get_latest() -> dict:
    """/status용: 백그라운드가 1분마다 갱신한 캐시를 반환.
    아직 캐시가 없으면(콜드스타트) 그때만 한 번 라이브 점검."""
    return _latest if _latest is not None else run_checks()


def _recorder_loop() -> None:
    while True:
        try:
            record_check()
        except Exception:
            # 기록 실패해도 루프는 계속 (다음 주기에 재시도)
            pass
        time.sleep(RECORD_INTERVAL)


def start_recorder() -> None:
    """앱 기동 시 호출. 데몬 스레드라 서버 꺼지면 같이 종료됨."""
    threading.Thread(target=_recorder_loop, daemon=True).start()


# 업타임을 따로 집계할 서비스들: (집계 키, 화면 라벨, status_checks 컬럼)
_SERVICES = [
    ("backend", "백엔드", "backend_ok"),
    ("database", "데이터베이스", "database_ok"),
    ("mail", "메일", "mail_ok"),
]


def get_history(days: int = 30) -> dict:
    """최근 N일 일별 업타임을 서비스별로 집계.

    각 서비스 uptime = 그 서비스가 정상이던 점검 / 전체 점검.
    점검이 없는 날(서버가 꺼져 있던 날)은 uptime=None → 프론트에서 회색 처리.
    """
    sql = text(
        """
        select date_trunc('day', checked_at) as day,
               count(*) as total,
               sum(case when backend_ok then 1 else 0 end) as backend_up,
               sum(case when database_ok then 1 else 0 end) as database_up,
               sum(case when mail_ok then 1 else 0 end) as mail_up
        from status_checks
        where checked_at >= :since
        group by day
        """
    )
    since = datetime.now(UTC) - timedelta(days=days)

    # 날짜 -> {total, backend, database, mail}
    by_date: dict[str, dict] = {}
    with engine.connect() as conn:
        for r in conn.execute(sql, {"since": since}):
            d = r.day.date().isoformat()
            by_date[d] = {
                "total": r.total,
                "backend": r.backend_up,
                "database": r.database_up,
                "mail": r.mail_up,
            }

    # 최근 N일 날짜 목록 (오래된 → 오늘 순)
    today = datetime.now(UTC).date()
    date_list = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]

    services = []
    for key, label, _col in _SERVICES:
        day_rows = []
        up_all = 0
        total_all = 0
        for d in date_list:
            rec = by_date.get(d)
            if rec and rec["total"] > 0:
                day_rows.append(
                    {
                        "date": d,
                        "uptime": round(rec[key] / rec["total"], 4),
                        "checks": rec["total"],
                    }
                )
                up_all += rec[key]
                total_all += rec["total"]
            else:
                day_rows.append({"date": d, "uptime": None, "checks": 0})
        overall = round(up_all / total_all, 4) if total_all else None
        services.append(
            {"name": key, "label": label, "overall_uptime": overall, "days": day_rows}
        )

    total_checks = sum(rec["total"] for rec in by_date.values())
    return {"services": services, "total_checks": total_checks}

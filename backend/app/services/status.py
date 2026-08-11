"""서비스 상태 점검 + 기록(업타임) 로직.

- run_checks(): 지금 이 순간 상태를 점검해서 반환 (실시간 /status 가 사용)
- record_check(): 점검 결과를 status_checks 테이블에 1줄 저장
- start_recorder(): 1분마다 record_check() 도는 백그라운드 스레드 시작 (앱 기동 시)
- get_history(days): 일별 업타임 집계 (업타임 페이지가 사용)
"""

import smtplib
import threading
import time
from datetime import UTC, datetime, timedelta

import psutil
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
    """백엔드/DB/메일 점검 + 통계(글·구독자 수)를 한 번에.

    결과에 `at`(이 점검이 **실제로 돈** 시각)을 같이 담는다. /api/status는 이 값을
    그대로 내보낸다 — 예전엔 응답의 checked_at을 '호출 시각'으로 새로 찍어서,
    최대 60초 낡은 캐시가 방금 잰 것처럼 보였다(2026-07-28 카오스 훈련에서 확인).
    사고 중에 "방금 확인했는데 ok라는데?"로 사람을 헷갈리게 하는 종류의 거짓이다.
    """
    # DB 점검 + 통계를 한 연결에서
    db_ok = True
    post_count = None
    subscriber_count = None
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
            # **공개 글만 센다.** /api/status는 무인증이고 이 값은 상태 페이지의 카드로
            # 나간다. 전체를 세면 `GET /api/posts`의 total(비로그인=public만,
            # routers/posts.py의 visible_condition)과 어긋나고 **그 차이가 곧 숨긴 글의
            # 개수**다. 2026-08-10 무인증으로 재현했다:
            #   공개 17 / 비공개 1 / 구독자전용 1 일 때
            #   GET /api/posts?limit=1 → total 17,  GET /api/status → stats.posts 19
            # 내용은 안 새지만 "숨긴 글이 2편 있고 방금 하나 늘었다"가 나간다.
            # 새 원칙이 아니라 **바로 아래 disk_ok가 이미 쓴 기준**이다("무인증 공개라
            # 잔량 수치는 공격 진척 계기판이 된다 → 1비트만"). 그 기준이 이 줄에만
            # 적용되지 않고 있었다. 덤으로 UI 거짓말도 닫힌다 — 상태 페이지가 19라고
            # 하는데 목록은 17개만 보여주던 상태였다.
            #
            # 아래 subscribers는 같은 문제가 아니라 그대로 둔다. 기준은 '시행 중인 통제를
            # 우회하는가'인데, author_subscriptions에는 행 단위 가시성이 없고(=비공개 구독이라는
            # 개념이 없다) approved=true가 이미 대기 신청을 뺀다. 우회할 통제가 없다.
            post_count = conn.execute(
                text("select count(*) from posts where visibility = 'public'")
            ).scalar()
            # '구독자' = 승인된 계정 구독을 가진 사람 수(중복 제거).
            # 2026-07-31 전까지는 폐지된 뉴스레터 테이블(subscribers)을 셌는데, 그 테이블은
            # 더 이상 늘지 않으므로 그대로 두면 **얼어붙은 숫자를 현재값처럼** 보여주게 된다.
            # 화면의 라벨은 그대로 '구독자'이므로, 지금 그 말이 뜻하는 것을 센다.
            subscriber_count = conn.execute(
                text(
                    "select count(distinct subscriber_id) from author_subscriptions "
                    "where approved = true"
                )
            ).scalar()
    except Exception:
        db_ok = False

    mail_ok = _check_mail()

    # 디스크는 **퍼센트를 내보내지 않는다.** /api/status는 무인증 공개라 잔량 수치는
    # '디스크를 채우는 공격'의 진척 계기판이 된다. 임계 초과 여부 1비트만 낸다.
    #
    # 왜 이게 여기 있어야 하나 — pgdata가 EC2 루트 볼륨 위에 살고, 감시(watch.sh)는
    # AWS 바깥의 GitHub Actions에서 돌아 EC2에 닿을 수단이 없다(SSH 키도 SSM 권한도 없다).
    # 이 응답이 **감시가 서버 안을 볼 수 있는 유일한 창**이다. 그런데 디스크가 차서
    # Postgres가 쓰기를 거부하면 감시는 database가 down이 되는 순간에야 아는데, 그때는
    # 이미 사이트가 죽었고 백업도 못 뜬다(2026-08-10 심층검사).
    #
    # 임계: 여유 15% 미만 **또는** 1.5GiB 미만. Postgres는 볼륨이 꽉 차기 전에 WAL·
    # 체크포인트에서 먼저 죽으므로 여유를 둔다. 루트 볼륨 크기가 terraform에 없어서
    # (ec2.tf의 root_block_device에 volume_size가 없다) 비율과 절대값을 둘 다 건다.
    try:
        du = psutil.disk_usage("/")
        disk_ok = du.free >= max(1.5 * 1024**3, du.total * 0.15)
    except Exception:
        disk_ok = False  # 못 쟀으면 초록으로 넘기지 않는다

    return {
        "at": datetime.now(UTC).isoformat(),
        "backend_ok": True,  # 이 코드가 도는 것 자체가 백엔드 동작
        "database_ok": db_ok,
        "mail_ok": mail_ok,
        "disk_ok": disk_ok,
        "posts": post_count,
        "subscribers": subscriber_count,
    }


def _check_mail() -> bool:
    """메일이 '실제로 나갈 수 있는' 상태인지 본다.

    예전엔 SMTP 포트에 TCP 소켓이 붙는지만 봤다. 그건 "포트가 열려 있다"까지만
    말해주는데, 우리가 알고 싶은 건 "send_mail이 성공하겠는가"다. 그 차이 때문에
    2026-06-25부터 4주 동안 제3자에게 메일이 한 통도 안 나가는 상태였는데도
    상태 페이지는 25,826번 "메일 정상"이라고 답했다.

    그래서 email.py의 send_message 직전까지, 즉 STARTTLS와 로그인까지 똑같이 해본다.
    이러면 자격증명 만료·비밀번호 오타·TLS 설정 오류가 잡힌다.

    ⚠️ 이걸로도 못 잡는 게 하나 있다: **SES 샌드박스**. 샌드박스에서도 로그인은
    성공하고, 검증 안 된 수신자에게 보낼 때 비로소 거부된다. 그건 계정 설정이라
    앱이 아니라 바깥에서 봐야 한다 → `scripts/watch.sh`가 ses:GetAccount로 확인한다.
    """
    # TLS를 쓰는 구성(=SES 같은 인증 SMTP)인데 사용자명이 비어 있으면 로그인을 건너뛰게
    # 되고, 그러면 "고쳤다고 생각한 가짜 정상"이 다른 입구로 돌아온다. 설정 오류로 본다.
    if settings.smtp_use_tls and not settings.smtp_user:
        return False
    try:
        # 로컬 Mailpit = 평문/무인증, 프로드 SES = STARTTLS + 로그인 (email.py와 같은 분기)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=3) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
        return True
    except Exception:
        return False


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
                disk_ok=c["disk_ok"],
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
    ("disk", "디스크", "disk_ok"),
]


def get_history(days: int = 30) -> dict:
    """최근 N일 일별 업타임을 서비스별로 집계.

    각 서비스 uptime = 그 서비스가 정상이던 점검 / 전체 점검.
    점검이 없는 날(서버가 꺼져 있던 날)은 uptime=None → 프론트에서 회색 처리.

    **표가 커지는 건 여기서 문제가 아니다 — 재봤다(2026-08-11).**
    "status_checks가 180일 차면 /status/history가 8배 느려진다"는 예측이 있었는데,
    로컬에 180일치(259,214행 · 29 MB)를 실제로 심고 EXPLAIN ANALYZE로 재보니 틀렸다:

      · days=30  → 21 ms  (Index Scan, 43,213행만 읽음 — 현행 실측 18~27ms와 같다)
      · days=90  → 51 ms  (라우터가 1~90으로 묶으므로 **이게 API의 최악**이다)
      · 표 전체  → 68 ms  (Seq Scan. days 상한 때문에 이 경로는 API로 도달 불가)

    이유는 단순하다: `where checked_at >= :since`가 ix_status_checks_checked_at으로
    범위 스캔이라 **읽는 양이 창(window) 크기에 묶여 있고 표 크기와 무관하다.**
    그래서 보존 정책(오래된 행 삭제)은 성능 때문에 필요한 게 아니다 — 1년이면
    약 59 MB고, 지우면 과거 업타임 기록이 사라진다. 느려진다면 그건 표가 커져서가
    아니라 days 상한이 올라갔거나 인덱스가 사라진 것이다.
    """
    sql = text(
        """
        select date_trunc('day', checked_at) as day,
               count(*) as total,
               sum(case when backend_ok then 1 else 0 end) as backend_up,
               sum(case when database_ok then 1 else 0 end) as database_up,
               sum(case when mail_ok then 1 else 0 end) as mail_up,
               -- disk_ok는 2026-08-10 이후 행에만 있다(그 전은 NULL). NULL을 '정상'으로
               -- 세면 안 쟀던 과거가 초록으로 칠해진다 → 분모도 따로 센다.
               sum(case when disk_ok then 1 else 0 end) as disk_up,
               count(disk_ok) as disk_total
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
                "disk": r.disk_up,
                "disk_total": r.disk_total,
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
            # 분모를 서비스마다 따로 잡는다. disk_ok는 2026-08-10부터 기록되므로 그 전 행은
            # NULL이고, 전체 점검 수를 분모로 쓰면 **안 쟀던 날이 '디스크 0% 정상'으로**
            # 칠해진다. 그건 이 저장소가 반복해서 경계하는 '초록으로 썩는 검사'다.
            denom = rec["disk_total"] if (rec and key == "disk") else (rec["total"] if rec else 0)
            if rec and denom > 0:
                day_rows.append(
                    {
                        "date": d,
                        "uptime": round(rec[key] / denom, 4),
                        "checks": denom,
                    }
                )
                up_all += rec[key]
                total_all += denom
            else:
                # 기록이 없는 날은 uptime=None → 프론트가 회색으로 그린다.
                # 디스크는 08-10 이전 구간이 통째로 여기 해당한다(안 잰 것이지 정상이 아니다).
                day_rows.append({"date": d, "uptime": None, "checks": 0})
        overall = round(up_all / total_all, 4) if total_all else None
        services.append(
            {"name": key, "label": label, "overall_uptime": overall, "days": day_rows}
        )

    total_checks = sum(rec["total"] for rec in by_date.values())
    return {"services": services, "total_checks": total_checks}

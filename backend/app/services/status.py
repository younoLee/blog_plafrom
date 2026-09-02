"""서비스 상태 점검 + 기록(업타임) 로직.

- run_checks(): 지금 이 순간 상태를 점검해서 반환 (실시간 /status 가 사용)
- record_check(): 점검 결과를 status_checks 테이블에 1줄 저장
- start_recorder(): 1분마다 record_check() 도는 백그라운드 스레드 시작 (앱 기동 시)
- get_history(days): 일별 업타임 집계 (업타임 페이지가 사용)
"""

import logging
import smtplib
import threading
import time
from datetime import UTC, datetime, timedelta

import psutil
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.models.status_check import StatusCheck

# main.py의 lifespan이 basicConfig로 app 로거를 INFO로 켠다 — 그전엔 핸들러가 0개라
# 이런 줄이 한 줄도 안 나갔다(같은 파일 주석 참고). exception은 WARNING 위라 그때도 나간다.
logger = logging.getLogger(__name__)

# 자가 점검 기록 간격(초)
RECORD_INTERVAL = 60

# 마지막 점검이 이보다 오래됐으면 **이 응답을 믿지 말라**는 뜻이다.
#
# **왜 필요한가 (2026-08-27)** — 08-27 카오스 훈련이 DB를 얼렸을 때 /api/status가
# 884초(14분 45초) 동안 database=ok 를 내보냈다. 캐시가 낡은 게 아니라 **값이 나이를
# 안 먹고 있었다** — 레코더 스레드가 run_checks()의 connect()에서 같이 얼어서 얼기
# 직전 값이 그대로 남았다. 그 뒤 점검 전용 엔진에 상한을 줘서 이 경로는 닫혔지만,
# 레코더가 다른 이유로 멈추는 경우는 여전히 같은 모양이 된다.
#
# **판정을 서버가 소유한다.** 화면이 각자 "몇 초부터 낡은 건가"를 정하면 상태 페이지와
# watch.sh 가 같은 순간에 다른 답을 낸다. 이 저장소는 디스크 임계에서 이미 그 모양을
# 겪었다. 여기서 한 번 정하고 응답에 실어 보내면 바깥에서도 같은 조건을 쓴다.
#
# 3주기인 이유: 1주기는 갱신 직전에 늘 참이라 상시 경고가 되고, 2주기는 한 번 걸러도
# 바로 걸린다. 셋이면 '한 번 놓친 것'과 '멈춘 것'이 갈린다.
STALE_AFTER = RECORD_INTERVAL * 3


# 디스크가 '괜찮은가'의 판정. **여기 한 곳에만 둔다.**
#
# 임계: 여유 15% 미만 또는 1.5GiB 미만이면 안 괜찮다. Postgres 는 볼륨이 꽉 차기 전에
# WAL·체크포인트에서 먼저 죽으므로 여유를 둔다. 루트 볼륨 크기가 terraform 에 없어서
# (ec2.tf 의 root_block_device 에 volume_size 가 없다) 비율과 절대값을 둘 다 건다.
#
# **왜 함수로 뽑았나 (2026-08-27)** — 같은 판정이 두 곳에 있었다. 여기는 여유 용량으로,
# 관리자 화면의 미터는 사용률 85% 로 판정했다. 8GiB 루트에서 1.5GiB 여유는 사용률
# 81.25% 라, 81.25~85% 구간에서 **상태 페이지는 빨간불인데 관리자 미터는 노란불**이다.
# 같은 순간에 두 화면이 다른 답을 낸다.
#
# 둘 다 안전한 방향으로 틀려서(상태 쪽이 더 엄격) 사고는 안 나지만, 판정이 두 곳에
# 살면 한쪽만 고쳐지는 것이 이 저장소가 반복해서 겪은 일이다. 같은 날 /api/status 의
# stale 판정을 서버가 소유하게 만든 것과 같은 이유로 여기서 한 번 정한다.
DISK_MIN_FREE_BYTES = 1.5 * 1024**3
DISK_MIN_FREE_RATIO = 0.15


def disk_is_ok(du) -> bool:  # noqa: ANN001  (psutil의 sdiskusage — 타입 스텁이 없다)
    return bool(du.free >= max(DISK_MIN_FREE_BYTES, du.total * DISK_MIN_FREE_RATIO))

# ── 점검 전용 엔진 (2026-08-27 카오스 훈련) ──────────────────────────────────────
# **왜 앱 엔진을 안 쓰나.** 08-27 훈련에서 `db hang`(연결은 받고 무응답)을 걸었더니
# `/api/status`가 **884초 동안** `"database":"ok"`라고 답했다. 원인은 캐시가 아니라
# 레코더 스레드다 — `run_checks()`가 공용 엔진의 `engine.connect()`에서 같이 얼어붙어
# `_latest`가 영원히 안 늙는다. 얼기 직전 값이 ok였으니 ok를 계속 내보낸다.
#
# 07-28 훈련이 이 파일에서 고친 것이 "응답의 checked_at을 호출 시각으로 새로 찍어
# 낡은 캐시가 방금 잰 것처럼 보인다"였다. 그때 거짓의 절반(시각)을 닫았는데
# **나머지 절반(값 자체가 안 늙는다)이 남아 있었다.** 사고 중에 사람을 헷갈리게
# 하는 종류는 같다.
#
# 대조군이 같은 파일 안에 있었다 — `_check_mail`은 `timeout=3`이 있어서 같은 상황에서
# 한 주기 만에 정상적으로 빨간불이 켜졌다. DB 점검에만 상한이 없었다.
#
# **NullPool이 핵심이다.** 점검할 때마다 **새 커넥션**을 뚫으므로 `connect_timeout`이
# 실제로 걸린다. 풀에 이미 열려 있던 커넥션을 재사용하면 읽기에 상한이 없어서
# (libpq에 읽기 타임아웃이 없다 — core/database.py의 긴 주석 참고) 이 수정이 무의미해진다.
# 점검은 RECORD_INTERVAL(60초)에 한 번이라 매번 새로 뚫어도 싸다.
#
# 3초인 이유: 같은 파일 `_check_mail`의 timeout=3과 맞춘다. 이 DB는 같은 호스트에
# 얹혀 있어 정상이면 밀리초다. 3초가 걸리면 그건 이미 사고다.
_probe_engine = create_engine(
    settings.database_url,
    poolclass=NullPool,
    connect_args={"connect_timeout": 3},
)

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
        # 공용 엔진이 아니라 점검 전용 엔진(위 주석) — 상한이 실제로 걸리는 쪽이다.
        with _probe_engine.connect() as conn:
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
        disk_ok = disk_is_ok(psutil.disk_usage("/"))
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
    # **DB가 죽었으면 기록은 건너뛴다.** 죽은 DB에 한 줄 쓰겠다고 여기서 다시 얼면
    # 위에서 점검에 상한을 준 의미가 없다 — 캐시는 down으로 갱신됐는데 스레드가
    # 커밋에 붙들려 다음 주기가 영영 안 온다. 업타임 표에 그 분이 비는 것은
    # 맞는 기록이다(그 시각에 DB가 없었다는 뜻이고, 화면도 그렇게 읽는다).
    if not c["database_ok"]:
        return
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
            # 기록 실패해도 루프는 계속 돈다(다음 주기에 재시도). **삼키지는 않는다** —
            # 이 스레드는 호출자가 없어서 여기서 조용히 넘기면 실패가 어디에도 안 남고,
            # 결과는 상태 페이지의 일별 집계에 구멍으로만 나타난다. 그 구멍은 '그 시각에
            # 서버가 꺼져 있었다'와 화면상 구분이 안 되므로 **아무도 모른다**.
            # services/cleanup.py가 같은 자리(백그라운드 + 호출자 없음)에서 이미
            # logger.exception을 쓴다 — 배운 자리 옆이 안 쓸려 있었다(2026-09-02).
            logger.exception("상태 점검 기록 실패 — 이번 주기는 업타임에 한 줄도 안 남는다")
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
    # 업타임 페이지는 사용자 경로다 — 공용 풀을 쓴다. 점검 전용 엔진은 NullPool 이라
    # 매 호출 새 커넥션을 뚫는데, 60초에 한 번인 레코더에는 싸도 사용자 요청마다는 비싸다.
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

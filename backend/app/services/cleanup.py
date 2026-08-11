"""미인증 계정 자동 정리.

가입했지만 일정 시간(기본 24h) 안에 이메일 인증을 안 한 계정을 주기적으로 삭제한다.
미인증 계정은 로그인 자체가 안 되므로 글·댓글 등 딸린 데이터가 없어 안전하게 지울 수 있다.
(author_subscriptions는 users FK ondelete CASCADE라 혹시 있어도 자동 정리됨)
"""

import logging
import threading
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from app.core.database import SessionLocal
from app.models.ai_usage import AiHourlyUsage
from app.models.status_check import StatusCheck
from app.models.user import User

CLEANUP_INTERVAL = 3600  # 1시간마다
UNVERIFIED_TTL_HOURS = 24  # 가입 후 24시간 지나도 미인증이면 삭제
# append-only 테이블 보관 한도(무한 증가 방지). 조회 범위 밖만 지운다.
AI_HOURLY_TTL_HOURS = 48  # count_hour는 '현재 시간' 창만 본다 → 이틀이면 넉넉
STATUS_CHECK_TTL_DAYS = 180  # 업타임 페이지가 보는 범위 밖은 정리(1행/분이라 작지만 무한↑)

# 이 모듈은 백그라운드 스레드에서 돌아 **호출자가 없다** — 예외를 삼키면 그대로 사라진다.
# 예전엔 `except Exception: return 0`이 전부라 잘못 지워도 조용하고 안 지워져도 조용했다.
# email.py:31-56이 "조용한 실패를 읽을 수 있는 실패로 바꾼다"고 해놓은 것과 정면으로
# 어긋나던 자리다(2026-08-11 공백검사). 성공도 남긴다 — 대량 DELETE는 '몇 건 지웠나'가
# 사후에 유일한 단서다(계정 생성 경로가 초대뿐이라 복구가 관리자 수작업이다).
logger = logging.getLogger(__name__)


def cleanup_unverified(ttl_hours: int = UNVERIFIED_TTL_HOURS) -> int:
    """미인증 + 가입 후 ttl_hours 경과한 계정 삭제. 삭제 건수 반환."""
    cutoff = datetime.now(UTC) - timedelta(hours=ttl_hours)
    db = SessionLocal()
    try:
        result = db.execute(
            delete(User).where(
                User.email_verified.is_(False), User.created_at < cutoff
            )
        )
        db.commit()
        n = result.rowcount or 0
        if n:
            logger.info("미인증 계정 %d건 삭제 (기준 %dh, cutoff=%s)", n, ttl_hours, cutoff)
        return n
    except Exception:
        db.rollback()
        logger.exception("미인증 계정 정리 실패 — 이번 주기는 아무것도 안 지웠다")
        return 0
    finally:
        db.close()


def cleanup_old_usage_rows() -> None:
    """조회 범위 밖의 오래된 append-only 행을 지운다(무한 증가 방지).
    시간당 사용량은 '현재 시간'만, 상태점검은 최근 몇 달만 조회하므로 그 밖은 안전하게 삭제."""
    now = datetime.now(UTC)
    db = SessionLocal()
    try:
        db.execute(
            delete(AiHourlyUsage).where(
                AiHourlyUsage.hour < now - timedelta(hours=AI_HOURLY_TTL_HOURS)
            )
        )
        db.execute(
            delete(StatusCheck).where(
                StatusCheck.checked_at < now - timedelta(days=STATUS_CHECK_TTL_DAYS)
            )
        )
        # ai_guard_violation은 **일부러 안 지운다.** 2026-08-10 심층검사에서 "count_hour와
        # 같은 모양(현재 창만 읽음)인데 여기만 빠졌다"고 지적됐지만, 검토 결과 빼는 게 맞다:
        #   · 이건 사용량 카운터가 아니라 **보안 이벤트 기록**이다(인젝션 시도가 남는 유일한 자리).
        #   · "앱이 현재 시간만 읽는다"는 "아무도 안 읽는다"가 아니다. 같은 날 status_checks의
        #     180일 보관을 '낭비'라고 걸었다가 철회했는데, 그 근거가 services/status.py에 적힌
        #     "4주 동안 25,826번 '메일 정상'이라고 답했다"였다 — UI가 안 보여주는 과거 행을
        #     사람이 psql로 집계해서 나온 숫자다. 이 테이블도 사고 뒤에 그렇게 읽게 된다.
        #   · 크기가 사실상 0이다. 위반이 난 user-hour당 1행이고 정상 사용자는 평생 0이다.
        # 지울 이유가 '일관성'뿐이고 남길 이유가 '조사 가능성'이면 남기는 쪽이 싸다.
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("오래된 사용량·상태점검 행 정리 실패 — 테이블이 계속 커진다")
    finally:
        db.close()


def _cleanup_loop() -> None:
    while True:
        cleanup_unverified()
        cleanup_old_usage_rows()
        time.sleep(CLEANUP_INTERVAL)


def start_cleanup() -> None:
    """앱 기동 시 호출. 데몬 스레드라 서버 꺼지면 같이 종료됨."""
    threading.Thread(target=_cleanup_loop, daemon=True).start()

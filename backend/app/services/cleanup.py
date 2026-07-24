"""미인증 계정 자동 정리.

가입했지만 일정 시간(기본 24h) 안에 이메일 인증을 안 한 계정을 주기적으로 삭제한다.
미인증 계정은 로그인 자체가 안 되므로 글·댓글 등 딸린 데이터가 없어 안전하게 지울 수 있다.
(author_subscriptions는 users FK ondelete CASCADE라 혹시 있어도 자동 정리됨)
"""

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
        return result.rowcount or 0
    except Exception:
        db.rollback()
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
        db.commit()
    except Exception:
        db.rollback()
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

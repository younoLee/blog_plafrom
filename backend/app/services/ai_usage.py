"""유저별 일일 AI 초안 사용량 — 서버키(Claude) 호출 비용 폭주 방지용 일일 캡.

레이트리밋(시간당 IP)과 별개로, 사용자 한 명이 하루에 서버키로 만들 수 있는
초안 수를 제한한다. BYOK 호출은 세지 않는다(사용자 본인 비용).
"""

from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ai_usage import AiHourlyUsage, AiUsage


def _today() -> date:
    # 서버 로컬 tz에 안 휘둘리게 UTC 기준 '오늘'
    return datetime.now(UTC).date()


def _this_hour() -> datetime:
    # 정시로 내림 (14:37 → 14:00). 고정 창이라 경계에서 최대 2배가 몰릴 수 있는데,
    # 일일 캡도 같은 성질이고 slowapi 기본 창도 고정이라 동일한 트레이드오프다.
    return datetime.now(UTC).replace(minute=0, second=0, microsecond=0)


def count_today(db: Session, user_id: int) -> int:
    row = db.scalar(
        select(AiUsage).where(AiUsage.user_id == user_id, AiUsage.day == _today())
    )
    return row.count if row else 0


def count_month(db: Session, user_id: int) -> int:
    # 이번 달(UTC) 1일부터 오늘까지 일별 count 합. 별도 테이블 없이 일일 기록을 재활용.
    first = _today().replace(day=1)
    total = db.scalar(
        select(func.coalesce(func.sum(AiUsage.count), 0)).where(
            AiUsage.user_id == user_id, AiUsage.day >= first
        )
    )
    return int(total or 0)


def increment_today(db: Session, user_id: int) -> None:
    today = _today()
    row = db.scalar(
        select(AiUsage).where(AiUsage.user_id == user_id, AiUsage.day == today)
    )
    if row is None:
        db.add(AiUsage(user_id=user_id, day=today, count=1))
    else:
        row.count += 1
    db.commit()


def count_hour(db: Session, user_id: int) -> int:
    """이번 시간(UTC 정시 창)에 이 사용자가 '시도'한 초안 수. BYOK 포함."""
    row = db.scalar(
        select(AiHourlyUsage).where(
            AiHourlyUsage.user_id == user_id, AiHourlyUsage.hour == _this_hour()
        )
    )
    return row.count if row else 0


def increment_hour(db: Session, user_id: int) -> None:
    """시도 시점에 미리 센다 — 실패해도 차감되어야 재시도 남용이 공짜가 아니게 된다."""
    hour = _this_hour()
    row = db.scalar(
        select(AiHourlyUsage).where(
            AiHourlyUsage.user_id == user_id, AiHourlyUsage.hour == hour
        )
    )
    if row is None:
        db.add(AiHourlyUsage(user_id=user_id, hour=hour, count=1))
    else:
        row.count += 1
    db.commit()

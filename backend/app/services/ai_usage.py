"""유저별 일일 AI 초안 사용량 — 서버키(Claude) 호출 비용 폭주 방지용 일일 캡.

레이트리밋(시간당 IP)과 별개로, 사용자 한 명이 하루에 서버키로 만들 수 있는
초안 수를 제한한다. BYOK 호출은 세지 않는다(사용자 본인 비용).
"""

from datetime import UTC, date, datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
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


def increment_today(db: Session, user_id: int) -> int:
    """서버키 성공 호출을 원자적으로 +1 (경쟁 안전, 새 count 반환).
    예전엔 SELECT→`+=`→commit이라 동시 호출이 서로의 증가를 덮어써(lost update) 캡을
    과소집계했다 → 캡을 넘겨도 통과. ON CONFLICT DO UPDATE 한 문장으로 DB가 직렬화한다."""
    stmt = (
        pg_insert(AiUsage)
        .values(user_id=user_id, day=_today(), count=1)
        .on_conflict_do_update(
            constraint="uq_ai_usage_user_day",
            set_={"count": AiUsage.count + 1},
        )
        .returning(AiUsage.count)
    )
    new_count = int(db.scalar(stmt))
    db.commit()
    return new_count


def decrement_today(db: Session, user_id: int) -> int:
    """예약 되돌리기 — 원자적 -1 (새 count 반환). 호출 '전에' 예약한 서버키 슬롯을
    캡 초과나 생성 실패로 취소할 때 쓴다.

    `count > 0` 조건이 필수다. 없으면 동시 취소가 겹쳐 카운트가 음수로 내려가고,
    음수는 다음 요청들에게 '캡에 여유가 있다'로 읽혀 캡 자체가 무너진다.
    행이 없거나 이미 0이면 UPDATE가 0행이라 None → 0으로 본다."""
    stmt = (
        update(AiUsage)
        .where(
            AiUsage.user_id == user_id,
            AiUsage.day == _today(),
            AiUsage.count > 0,
        )
        .values(count=AiUsage.count - 1)
        .returning(AiUsage.count)
    )
    new_count = db.scalar(stmt)
    db.commit()
    return int(new_count) if new_count is not None else 0


def count_hour(db: Session, user_id: int) -> int:
    """이번 시간(UTC 정시 창)에 이 사용자가 '시도'한 초안 수. BYOK 포함."""
    row = db.scalar(
        select(AiHourlyUsage).where(
            AiHourlyUsage.user_id == user_id, AiHourlyUsage.hour == _this_hour()
        )
    )
    return row.count if row else 0


def increment_hour(db: Session, user_id: int) -> int:
    """시도를 원자적으로 +1 (경쟁 안전, 새 count 반환). 호출 '전에' 세서 실패·재시도도
    차감된다. 반환값으로 캡을 판단(reserve-then-check)하면 동시요청이 캡을 넘겨 통과 못 한다 —
    공유 데모 계정이 여러 IP로 몰려도 계정 기준 시간당 캡이 총량을 하드 캡한다."""
    stmt = (
        pg_insert(AiHourlyUsage)
        .values(user_id=user_id, hour=_this_hour(), count=1)
        .on_conflict_do_update(
            constraint="uq_ai_hourly_usage_user_hour",
            set_={"count": AiHourlyUsage.count + 1},
        )
        .returning(AiHourlyUsage.count)
    )
    new_count = int(db.scalar(stmt))
    db.commit()
    return new_count

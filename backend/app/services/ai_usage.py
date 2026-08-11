"""유저별 일일 AI 초안 사용량 — 서버키(Claude) 호출 비용 폭주 방지용 일일 캡.

레이트리밋(시간당 IP)과 별개로, 사용자 한 명이 하루에 서버키로 만들 수 있는
초안 수를 제한한다. BYOK 호출은 세지 않는다(사용자 본인 비용).
"""

from datetime import UTC, date, datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.ai_usage import AiGuardViolation, AiHourlyUsage, AiUsage


def today() -> date:
    """예약과 기록이 **같은 날짜 버킷**을 보게 하려고 밖으로 연다(add_tokens의 day 인자)."""
    return _today()


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


def add_tokens(
    db: Session, user_id: int, input_tokens: int, output_tokens: int, day: date | None = None
) -> None:
    """성공한 서버키 호출의 실제 토큰을 그날 행에 누적한다.

    호출 **후에** 부른다 — 토큰은 벤더 응답을 봐야 알 수 있어서, 예약(increment_today)
    시점에는 존재하지 않는다. 그래서 아래 토큰 상한은 '직전까지 쓴 양'으로 판단한다:
    한 호출만큼 넘칠 수 있지만, 비용 가드레일에서 그 오차는 허용 범위다(넘겨서 통과시키는
    것과 달리 다음 호출은 확실히 막힌다).

    ⚠️ **`day`는 예약 시점의 날짜를 받아야 한다.** 여기서 `_today()`를 다시 계산하면
    UTC 자정을 넘긴 호출이 D+1 행을 찾다가 **UPDATE 0행**이 되어 토큰이 조용히 사라진다
    (예약은 D일에 했고 벤더 대기가 최대 55초다). "이론상 불가"라고 적어뒀던 그 경로가
    실제로는 하루 55초짜리 창으로 존재했다 — 2026-08-11 교차검증에서 잡혔다.
    `day`를 안 주면 옛 동작(오늘 기준)이라, 부르는 쪽이 반드시 넘긴다.

    행이 없으면 조용히 넘긴다 — 토큰 기록 실패로 초안 생성을 죽일 이유는 없다.
    """
    if input_tokens <= 0 and output_tokens <= 0:
        return
    db.execute(
        update(AiUsage)
        .where(AiUsage.user_id == user_id, AiUsage.day == (day or _today()))
        .values(
            input_tokens=AiUsage.input_tokens + input_tokens,
            output_tokens=AiUsage.output_tokens + output_tokens,
        )
    )
    db.commit()


def tokens_today_all_users(db: Session) -> int:
    """오늘 서버키 호출의 **서비스 전체** 토큰 합(입력+출력).

    횟수가 아니라 이 숫자가 실제 청구에 비례한다. `coalesce`가 중요하다 —
    행이 없으면 SUM이 NULL이고, NULL을 상한과 비교하면 조용히 통과한다(fail-open).
    """
    total = db.scalar(
        select(
            func.coalesce(func.sum(AiUsage.input_tokens + AiUsage.output_tokens), 0)
        ).where(AiUsage.day == _today())
    )
    return int(total or 0)


def count_today_all_users(db: Session) -> int:
    """오늘 서버키 호출의 **서비스 전체 합계**.

    지금까지 캡은 전부 `user_id` 단위였고 전체 합계를 세는 코드가 **한 곳도 없었다**
    (2026-08-11 공백검사). 사용자가 늘거나 한 명이 여러 계정을 갖게 되면 서비스 전체
    비용에는 상한이 없었던 셈이다. 게다가 Anthropic 청구는 AWS 밖이라
    watch.sh가 보는 AWS Budgets가 **원리적으로 못 본다** → 다음 명세서까지 최대 한 달
    아무도 모른다. 그 창을 닫는 마지막 방어선이다.

    per-user 캡과 달리 이건 '남용'이 아니라 '내가 감당할 수 있는 하루'의 상한이다.
    """
    total = db.scalar(
        select(func.coalesce(func.sum(AiUsage.count), 0)).where(AiUsage.day == _today())
    )
    return int(total or 0)


def count_guard_violations(db: Session, user_id: int) -> int:
    """이번 시간 창에 이 사용자가 가드에 걸린 횟수. 정상 사용자는 0이다."""
    row = db.scalar(
        select(AiGuardViolation).where(
            AiGuardViolation.user_id == user_id,
            AiGuardViolation.hour == _this_hour(),
        )
    )
    return row.count if row else 0


def increment_guard_violation(db: Session, user_id: int) -> int:
    """가드 위반을 원자적으로 +1 (새 count 반환).

    다른 카운터와 달리 이건 **호출 뒤에** 센다 — 위반인지는 응답을 받아봐야 알 수 있다.
    그래서 reserve-then-check가 아니라 사후 집계이고, 동시 요청이 임계를 살짝 넘겨
    통과할 수 있다. 여기선 그게 문제가 안 된다: 이 카운터는 비용이 아니라 '시행착오를
    비싸게' 만드는 장치이고, 비용 자체는 이미 시간당/일일 캡이 하드 캡한다."""
    stmt = (
        pg_insert(AiGuardViolation)
        .values(user_id=user_id, hour=_this_hour(), count=1)
        .on_conflict_do_update(
            constraint="uq_ai_guard_violation_user_hour",
            set_={"count": AiGuardViolation.count + 1},
        )
        .returning(AiGuardViolation.count)
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

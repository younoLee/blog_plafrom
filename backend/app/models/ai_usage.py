from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AiUsage(Base):
    """유저별 '일일' 서버키(Claude) AI 초안 호출 횟수.

    레이트리밋(시간당)과 별개의 '하루 총량' 캡으로 서버 비용 폭주를 막는다.
    BYOK(사용자 자기 키) 호출은 세지 않음 — 그건 사용자 본인 비용이라.
    계정 삭제 시 CASCADE로 함께 삭제."""

    __tablename__ = "ai_usage"
    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_ai_usage_user_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    day: Mapped[date] = mapped_column(Date, index=True)  # UTC 기준 날짜
    count: Mapped[int] = mapped_column(Integer, default=0)


class AiHourlyUsage(Base):
    """유저별 '시간당' AI 초안 '시도' 횟수 — 남용/DoS 방어용.

    AiUsage(일일)와 다른 점이 셋 있고, 셋 다 의도적이다:
    1. BYOK도 센다. 비용은 사용자 부담이지만 워커 스레드는 우리 자원이라,
       자기 키로 무한히 때리는 건 막아야 한다.
    2. '성공'이 아니라 '시도'를 센다. 실패를 안 세면 느리거나 죽은 엔드포인트를
       무한 재시도하는 게 공짜가 되어 방어가 무의미해진다.
    3. 메모리가 아니라 DB에 쌓는다. slowapi의 인메모리 리밋은 컨테이너가
       재시작하면 0으로 돌아가는데, 이 카운터는 재시작을 견딘다.

    계정 삭제 시 CASCADE로 함께 삭제."""

    __tablename__ = "ai_hourly_usage"
    __table_args__ = (
        UniqueConstraint("user_id", "hour", name="uq_ai_hourly_usage_user_hour"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # UTC 기준 '정시로 내림한' 시각 (예: 14:37 → 14:00). 고정 창(fixed window).
    hour: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    count: Mapped[int] = mapped_column(Integer, default=0)

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, UniqueConstraint
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
    # 실제 토큰 사용량(서버키 경로만). 2026-08-11까지 **토큰을 세는 코드가 0곳**이라
    # Haiku 20회와 Fable 20회가 캡에서 같게 취급됐다 — max_tokens가 2500 대 8000이고
    # 단가도 달라 실제 청구는 수십 배까지 벌어진다. 횟수 캡은 남용 방어로 그대로 두고,
    # 비용은 이 숫자로 본다. BigInteger인 이유: 하루 수만 토큰이 몇 년 쌓이면 int 범위가
    # 위태롭고, 나중에 '한 달 합계' 같은 걸 더할 때 오버플로가 조용히 난다.
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")


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


class AiGuardViolation(Base):
    """유저별 '시간당' AI 가드 위반 횟수 — 반복 인젝션 시도 차단용.

    시간당 시도 캡(AiHourlyUsage)이 이미 있는데 왜 또 세나: **세는 대상이 다르다.**
    시도 캡은 자원(워커 스레드)을 지키느라 성공/실패를 안 가리고 전부 센다. 이건
    '가드에 걸린 시도'만 센다 — 정상 사용자는 평생 0이고, 문구를 바꿔가며 가드를
    두드리는 쪽만 쌓인다. 그래서 정상 사용자의 한도를 안 깎으면서 훨씬 낮은 임계로
    끊을 수 있다(시도 10회 vs 위반 3회).

    한 방에 뚫리는 인젝션은 드물다. 실제 공격은 문구를 바꿔가며 반복하는 시행착오라,
    그 반복 자체를 비싸게 만드는 게 요점이다.

    계정 삭제 시 CASCADE로 함께 삭제."""

    __tablename__ = "ai_guard_violation"
    __table_args__ = (
        UniqueConstraint("user_id", "hour", name="uq_ai_guard_violation_user_hour"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    hour: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    count: Mapped[int] = mapped_column(Integer, default=0)

from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, UniqueConstraint
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

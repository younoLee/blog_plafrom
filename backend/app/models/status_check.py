from datetime import datetime

from sqlalchemy import Boolean, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class StatusCheck(Base):
    """1분마다 백그라운드가 자가 점검 결과를 한 줄씩 기록. 업타임 집계용."""

    __tablename__ = "status_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 점검 시각 (집계할 때 날짜로 묶으므로 index)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    backend_ok: Mapped[bool] = mapped_column(Boolean)
    database_ok: Mapped[bool] = mapped_column(Boolean)
    mail_ok: Mapped[bool] = mapped_column(Boolean)

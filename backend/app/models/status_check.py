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
    # 2026-08-10 추가. 같은 날 /api/status에 disk를 실었는데 **기록은 안 하고 있었다** —
    # 그래서 두 번의 감시 사이에 임계를 넘었다 돌아오면 흔적이 0이었다(보안검사 지적).
    # nullable: 이 컬럼이 생기기 전 행이 이미 수만 개라 소급 값이 없다. NULL은
    # '그때는 안 쟀다'는 뜻이고, 집계는 아래 get_history가 NULL을 정상으로 세지 않는다.
    disk_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class Subscriber(Base):
    __tablename__ = "subscribers"

    id: Mapped[int] = mapped_column(primary_key=True)
    # unique=True: 같은 이메일 중복 구독 방지 (DB 차원에서 막음)
    # index=True: 이메일로 조회가 잦으므로 인덱스
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    # 더블옵트인: 본인이 확인메일 링크를 눌러야 True → 확인된 사람에게만 알림 발송.
    # 남의 이메일 무단등록으로 알림메일이 가는 것(발신평판 악용)을 막음. 신규는 False.
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

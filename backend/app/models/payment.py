from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Payment(Base):
    """토스페이먼츠 일회성 결제 주문 기록.

    /checkout에서 pending 주문을 만들고, /confirm에서 토스 승인 성공 시 paid로 확정한다.
    order_id로 멱등성(같은 주문 두 번 승인 방지)과 금액 위변조 검증을 보장.
    계정 삭제 시 CASCADE로 함께 삭제."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # 우리가 발급하는 주문 고유 ID (토스 orderId로 사용). 유니크 = 멱등 키
    order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    amount: Mapped[int] = mapped_column(Integer)  # 원 단위
    # pending(주문생성) / confirming(승인 호출 중) / paid(승인완료) / failed(승인거절)
    #
    # confirming 은 2026-09-02에 생겼다. 그전에는 행을 잠근 채로 토스를 최대 15초
    # 기다려서, 그동안 커넥션과 잠금을 함께 쥐고 있었다. 지금은 confirming 으로 먼저
    # 커밋해 잠금을 풀고 외부 호출을 한다(routers/ai.py 가 먼저 쓰던 방식).
    # 그래서 confirming 은 '결제가 확정되지 않았다'는 뜻이지 실패가 아니다 —
    # 같은 paymentKey 로 다시 오면 재시도가 허용된다(routers/payments.py 참고).
    status: Mapped[str] = mapped_column(String(20), server_default="pending")
    order_name: Mapped[str] = mapped_column(String(100), server_default="")
    # 토스가 발급한 결제 키 (승인 후 저장, 환불 등에 사용)
    payment_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

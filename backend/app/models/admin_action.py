from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AdminAction(Base):
    """관리자가 남의 계정에 한 조치의 기록 (2026-09-05 신설).

    **왜 필요한가 (2026-09-04 검사 GAP-2)** — 차단·승인취소·계정삭제·Pro 토글은 남의
    글과 접근 권한을 되돌릴 수 없게 바꾸는데, 그 사실이 어디에도 안 남았다(admin
    라우터에 로깅 0줄). 관리자가 한 명뿐이라 '누가 했나'는 자명하지만 **'무엇을 언제
    했나'가 자명하지 않다** — 초대 목록이 '누구를 언제 들였나'의 답인 것과 짝으로,
    이 표가 '누구를 언제 내보냈나'의 답이다. 계정 삭제는 글·댓글까지 지우므로
    그 흔적이 없으면 사고 뒤에 무엇이 사라졌는지 재구성할 방법이 없다.

    **target 을 FK 로 걸지 않는다.** 계정 삭제를 기록하는 게 이 표의 주 용도인데,
    FK 를 걸면 그 행이 CASCADE 로 같이 지워지거나(기록이 사라진다) SET NULL 로
    누구였는지를 잃는다. 그래서 id 와 이메일을 **값으로 복사해** 둔다 — 지워진 뒤에도
    답할 수 있어야 기록이다. actor 는 관리자라 지워질 일이 거의 없지만 같은 이유로
    값으로 둔다.

    보존 기간은 정하지 않았다. 조치가 손에 꼽는 빈도라 커질 걱정이 없고, 커질 만큼
    쌓였다면 그때는 지우는 게 아니라 내보내야 할 자료다.
    """

    __tablename__ = "admin_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 조치한 관리자 (값으로 복사 — 위 주석 참고)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_email: Mapped[str] = mapped_column(String(255))
    # 대상 계정. **FK 를 안 건다** — 삭제를 기록하는 것이 이 표의 주 용도다.
    target_id: Mapped[int] = mapped_column(index=True)
    target_email: Mapped[str] = mapped_column(String(255))
    # approve · revoke · ban · unban · toggle_pro · release_handle · delete · change_email
    action: Mapped[str] = mapped_column(String(30), index=True)
    # 조치의 결과를 한 줄로(역할 전이, 바뀐 주소 등). 없으면 빈 문자열.
    detail: Mapped[str] = mapped_column(String(200), server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

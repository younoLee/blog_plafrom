from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Invite(Base):
    """관리자가 발급하는 1회용 가입 초대.

    왜 있나 — 가입은 `allow_signup=False`로 닫혀 있고(초대제), 지금까지 '초대'는
    관리자가 DB를 직접 만지는 것이었다. 즉 문서가 말하는 절차가 코드에 없었다.
    이 테이블이 그 절차다.

    **왜 초대 링크가 SES 샌드박스와 맞물리나** — 샌드박스는 검증된 주소로만
    발송을 허용하므로, 열린 가입의 '인증 메일'은 신규 주소에 영영 닿지 않는다.
    그런데 초대제에선 주소를 **관리자가 고르므로** 소유 증명을 메일로 다시 받을
    이유가 없다. 그래서 이 토큰을 소각하면 `email_verified=True`로 바로 만든다
    → **가입 경로에서 메일 의존이 사라진다.** 알림 수신은 그 뒤에
    `scripts/ses_verify_recipients.sh`로 그 주소만 검증하면 된다(별개 단계).

    **토큰은 해시로만 저장한다.** 원문은 발급 응답에 딱 한 번 실려 나가고 그
    뒤로는 어디에도 남지 않는다 — DB가 통째로 새도 그것만으로 가입할 수 없다.
    비밀번호를 해시로 두는 것과 같은 이유고, 대가는 '링크 재확인 불가'다
    (잃어버리면 취소하고 다시 발급한다. 초대 수가 한 자릿수라 감당된다).

    소각은 조건부 UPDATE 한 방으로 한다 — 조건이 걸린 UPDATE가 1행을 돌려줬을
    때만 진행한다(routers/auth.py의 redeem). 읽어서 확인한 뒤 표시하는 방식과
    무엇이 다른지는 **실제로 재보고 적는다**(2026-08-07, 변조 테스트):

    - 계정이 둘 생기지는 **않는다.** 그건 users.email의 유니크 제약이 막는다.
      처음엔 여기 "안 그러면 계정이 둘 생긴다"고 적었는데 거짓이었다.
    - 대신 진 쪽이 받는 답이 달라진다. 조건부 UPDATE면 "링크가 이미 쓰였어"가
      나가고, 읽고-쓰기면 유니크 충돌을 타서 **"이미 가입된 주소야"**가 나간다 —
      자기 초대를 처음 쓰는 사람에게 그건 틀린 안내다.
    - 그리고 정확성이 users 테이블의 제약에 얹히지 않는다. 이쪽 조건만으로
      단독으로 성립하는 편이 낫다(services/ai.py의 reserve-then-check와 같은 형태).

    즉 이건 '없으면 터지는 방어'가 아니라 **일차 방어**고, 유니크 제약이 그 뒤에
    한 겹 더 있다. 지우지 말되, 지운다고 계정이 복제되진 않는다는 것도 알아둘 것."""

    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 초대할 주소. 가입 시 이 값을 그대로 쓴다(요청 본문에서 이메일을 받지 않는다)
    # → 폼과 토큰이 어긋날 여지 자체가 없다.
    email: Mapped[str] = mapped_column(String(255), index=True)
    # 토큰 원문의 sha256 hex(64자). 조회는 이 값으로만 한다. unique = 충돌 방지.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # 가입 시 부여할 권한. 'pending'(기본, 관리자 승인 한 번 더) 또는 'writer'.
    # 'admin'은 절대 여기로 주지 않는다 — 초대 링크 하나가 관리자 계정이 되면
    # 링크 유출이 곧 사이트 탈취다. 라우터에서 값을 강제한다.
    role: Mapped[str] = mapped_column(String(20), server_default="pending")
    # 발급자(관리자). 계정이 지워져도 초대 기록은 남겨야 하므로 SET NULL.
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # 만료 시각. 유출된 링크가 영원히 살아 있지 않게 하는 게 목적이라 넉넉히 잡지 않는다.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # 소각 시각. NULL = 아직 안 씀. 이 컬럼이 1회용을 강제하는 조건이다.
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 이 초대로 만들어진 계정. 누가 누구를 들였는지 추적용(계정 삭제 시 SET NULL).
    used_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

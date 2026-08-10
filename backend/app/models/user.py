from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    # 대소문자만 다른 중복 계정을 **DB 차원에서** 막는다.
    #
    # 왜 필요한가 — 조회는 이미 대소문자를 무시한다(routers/auth.py의
    # `_find_user_by_email`). 하지만 아래 `unique=True`는 원문 그대로를 비교하므로
    # `Bob@x.com`과 `bob@x.com`은 **둘 다 만들어질 수 있었다.** 그러면 그 시점부터
    # 대소문자 무시 조회가 둘 중 하나를 임의로 집는다 — 로그인이 어느 계정으로
    # 붙는지가 행 순서에 달리고, 비번 재설정은 사람이 안 쓰는 쪽을 고칠 수 있다.
    # 조회를 고친 2026-08-07에 "구조적으로 막으려면 인덱스가 필요하다"고 적어뒀던 것.
    #
    # 기존 `unique=True`(원문)는 남긴다. 이 인덱스가 그것을 함의하므로 중복이지만,
    # 유니크 제약을 떼는 건 별개의 변경이고 3행짜리 테이블에서 아낄 것이 없다.
    #
    # **`text()`로 쓰는 이유**: 클래스 본문에서는 아직 `User.email`이 없어서
    # `func.lower(User.email)`을 못 쓴다. 이름으로 쓰면 create_all과 마이그레이션이
    # 같은 DDL을 낸다 — 모델과 마이그레이션이 갈라지는 게 2026-08-07 CI 빨간불의 원인이었다.
    __table_args__ = (
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    # 화면에 보일 이름. **이메일에서 유도하지 않는다.**
    # 2026-08-10 보안검사: 예전엔 이름이 필요할 때마다 email.split("@")[0]을 썼고,
    # 그 값이 무인증 경로 둘로 나갔다(GET /api/blog-owner, 공개 글의 댓글 작성자명).
    # admin이 단 하나이고 발신 도메인이 공개 제공자라, 로컬파트만 알면 주소가 완성된다.
    # NULL = '안 정했다'. 그때 화면은 폴백을 쓴다 — **이메일로 되돌아가지 않는다.**
    # 설정: scripts/create_user.py --display-name
    display_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # 평문이 아니라 bcrypt 해시를 저장
    hashed_password: Mapped[str] = mapped_column(String(255))
    # 권한: pending(가입 직후·승인 대기) / writer(승인됨·글쓰기 가능) / admin(승인권자)
    # 기존 가입자도 server_default 덕분에 마이그레이션 시 pending으로 채워짐
    role: Mapped[str] = mapped_column(String(20), server_default="pending")
    # 이메일 인증 여부. 가입 직후 False → 확인메일 링크 클릭하면 True (봇 대량가입 차단)
    # 기존 계정은 마이그레이션에서 True로 백필 (잠기지 않게)
    email_verified: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # 토큰 버전. 비번 재설정·차단 시 +1 → 그 이전에 발급된 JWT는 즉시 무효(세션 강제 종료)
    token_version: Mapped[int] = mapped_column(Integer, server_default="0")
    # 유료(pro) 여부. AI 초안에서 Opus·Fable 5 같은 고급 모델 해금.
    # 토스 결제 승인이 검증되면 True + pro_until 설정. admin은 role상 항상 전 모델 가능.
    is_pro: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # 구독 만료 시각(UTC). 결제 시 now+30일로 설정. 지나면 로그인/요청 시 자동으로 is_pro가 꺼짐.
    # None = 만료 없음(과거 수동 토글 계정 호환).
    pro_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

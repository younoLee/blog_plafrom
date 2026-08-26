from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, func, text
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
    # handle도 같은 처방을 쓴다 — 주소는 대소문자를 구분하지 않는 게 상식이라
    # `Yuno`와 `yuno`가 둘 다 만들어지면 어느 쪽이 열리는지가 행 순서에 달린다.
    # (이메일에서 이미 겪은 함정이다. 마이그레이션 c5d6e7f8a9b0 주석 참고)
    __table_args__ = (
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
        Index("uq_users_handle_lower", text("lower(handle)"), unique=True),
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
    # 이 사람의 블로그 주소. `/@handle` 로 열린다. NULL = 아직 안 정함 = 개인 블로그 없음.
    #
    # **이메일에서 유도하지 않는다.** display_name이 생긴 이유와 같고(2026-08-10 보안검사),
    # 핸들은 주소에 그대로 박히므로 노출이 더 크다. 사람이 직접 정한 값만 쓴다.
    # display_name을 안 쓰는 이유: 유니크가 아니고 한글·공백이 들어가 주소에서 인코딩
    # 문제를 만든다(한글 태그 허브가 403이던 2026-08-17의 그 문제다).
    #
    # 형식 강제(2~20자, [a-z0-9_-])는 입력 층(schemas의 HandleUpdate)이 한다.
    handle: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # 이 사람의 블로그 스킨(CSS). NULL = 기본 스킨.
    #
    # 프론트가 색·모서리를 CSS 변수로 노출하므로(index.css의 @theme), 여기 담기는 건
    # 보통 `:root { --color-accent: #20c997 }` 몇 줄이다. 그 변수 하나가 링크·버튼·
    # 태그칩·그라데이션까지 한꺼번에 따라 바뀐다.
    #
    # ⚠️ 이 값은 **무인증으로 공개된다**(GET /api/skin). 방문자 브라우저에서 실행되는
    # 스타일이므로 저장 전에 schemas의 SkinUpdate가 `</style`·`@import`·`javascript:`를
    # 거른다. 스크립트 실행 자체는 CSP(script-src 'self')가 한 겹 더 막는다.
    #
    # 지금은 주인(admin)의 값만 화면에 나간다 — 블로그 주소가 /blog 하나뿐이라
    # 여러 사람의 스킨을 동시에 적용할 자리가 없다. 컬럼을 users에 둔 건 나중에
    # 글쓴이별 주소가 생기면 그대로 쓰기 위해서다(마이그레이션 주석 참고).
    custom_css: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 이 사람의 블로그 '내 문장' — 제목 아래 머리말·사이드바 소개·푸터. NULL = 안 적음.
    #
    # JSON 문자열이다: `{"intro": "...", "aside": "...", "footer": "..."}`.
    # 세 컬럼으로 펴지 않은 이유는 마이그레이션 d6e7f8a9b0c1 주석에 있다(요약: 검색도
    # 조인도 안 하는 덩어리이고, 자리가 늘 때마다 컬럼을 늘리고 싶지 않다).
    #
    # ⚠️ custom_css와 달리 이 값은 **HTML로 파싱된다.** `<`를 막는 것으로 끝나지 않아서,
    # 저장 전에 app/core/html_slots.sanitize_slots()가 **허용 목록으로 다시 쓴다**
    # (모르는 태그·속성은 전부 사라진다). DB에 들어오는 시점에 이미 씻긴 값이다.
    custom_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# 공개 블로그(`/@handle`)를 가질 수 있는 역할.
#
# **역할을 뺏으면 블로그가 같이 내려가야 한다.** 2026-08-19 보안검사가 잡은 것:
# ban·revoke는 role과 token_version만 바꿔서 그 계정의 쓰기는 막았는데, `/@handle`이
# 읽는 세 경로(`/api/authors/{h}`·`/api/skin?handle=`·`/api/posts?author=`)가 전부
# 무인증 200으로 표시명·CSS·'내 문장'·공개 글을 계속 내보냈다. 조치가 절반만 들었다.
#
# 고치는 방법이 둘 있었다. ① ban·revoke가 handle·skin·slots를 같이 지운다
# ② 공개 읽기 경로가 역할을 본다. **②를 골랐다** — ①은 상태를 두 군데 두는 것이라
# 새 회수 경로가 생길 때마다 같이 안 고치면 또 어긋난다(그게 이번에 난 사고다).
# ②는 어느 경로로 회수해도 결과가 같고, 되돌리면(unban→approve) 블로그도 같이 돌아온다.
PUBLIC_BLOG_ROLES = ("writer", "admin")

# 차단된 계정의 역할. deps.py가 문자열로 두 번 들고 있었는데, 2026-08-26 검사에서
# 알림 발송 쪽에도 같은 판정이 필요해졌다. 철자를 흩뿌리면 한 군데를 빠뜨린다.
#
# **위 PUBLIC_BLOG_ROLES와 쓰임이 다르다.** 저건 '블로그를 가질 수 있는가'(writer·admin)이고
# 이건 '알림을 받을 수 있는가'다. 알림 수신자는 reader·pending도 정상이므로
# PUBLIC_BLOG_ROLES로 거르면 멀쩡한 독자까지 끊긴다 — 거기선 화이트리스트, 여기선 블랙리스트다.
BANNED_ROLE = "banned"

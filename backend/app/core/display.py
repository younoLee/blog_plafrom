"""화면에 보일 사용자 이름과 '이 블로그의 주인' — 한 자리에서만 정한다.

왜 공용 모듈인가 (2026-08-14): 이 폴백이 라우터 네 곳(구독·댓글·알림·구독신청)에
각자 `display_name or "회원"`으로 복사돼 있었다. 그래서 한 화면을 고치면 옆 화면이
여전히 "회원"으로 남는다 — 이 저장소가 '고친 자리 옆의 안 쓸린 입구'라고 부르는 모양이다.
라우터끼리 import 하면 순환 위험이 생기므로 core에 둔다.

**이메일에서 유도하지 않는다.** `email.split("@")[0]` 류는 2026-08-10 보안검사로 전부
걷어냈다. 유도가 한 군데라도 남으면 "이름은 이메일에서 만든다"는 관습이 살아남고,
그게 무인증 경로로 다시 새어나간 전력이 있다.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


def display_name_of(user_id: int, display_name: str | None) -> str:
    """이름을 안 정했으면 `회원 #<id>`.

    id를 붙이는 이유: 안 정한 계정이 전부 똑같이 "회원"으로 나가면 구독 화면이
    "회원 · 회원 · 회원"이 된다 — **뭘 구독했는지 알 수 없는 화면**이다(실제 신고).
    id는 같은 응답의 `id` 필드로 이미 나가므로 새로 새는 정보가 없다.

    ⚠️ **user_id를 넘겨라.** 알림 목록은 `Notification.id`와 `User.id`가 한 행에
    섞여 있어서 `r.id`를 그냥 쓰면 '회원 #<알림번호>'가 나온다(고치는 중에 실제로 밟았다).

    진짜 해법은 사람이 이름을 정하는 것이고, 그 통로는 `PATCH /api/auth/me`다.
    이 폴백은 안 정한 동안의 임시 표시다.
    """
    return display_name or f"회원 #{user_id}"


def site_owner(db: Session) -> User | None:
    """이 블로그의 주인 = role 이 admin 인 사람 중 id 가 가장 작은 사람.

    **왜 공용 함수인가 (2026-09-04 검사 BQ-11)** — 같은 쿼리가 세 곳에 손으로 복사돼
    있었다(main.py 의 /api/blog-owner · comments.py 의 `_site_owner_id` ·
    skin.py 의 `_owner`). 셋 다 주석으로 서로를 가리키며 '같은 규칙'이라고 약속했지만
    강제하는 것은 아무것도 없었다 — 규칙이 갈라지면 어떤 화면에는 주인 배지가 붙고
    어떤 화면에는 안 붙는다. 이 파일이 생긴 이유(display_name 폴백이 라우터 넷에
    복제돼 있었다)와 정확히 같은 모양이라 같은 자리에 둔다.

    id 만 필요한 호출부는 `.id` 를 읽으면 된다. 주인은 계정이 손에 꼽는 테이블에서
    한 명이라 컬럼 하나를 아끼는 이득이 없다.
    """
    return db.scalar(select(User).where(User.role == "admin").order_by(User.id))

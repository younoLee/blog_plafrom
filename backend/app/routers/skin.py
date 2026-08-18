"""블로그 스킨 — 외형을 코드 배포 없이 바꾼다.

프론트가 색·모서리를 CSS 변수로 노출하므로(frontend/src/index.css의 @theme),
여기서 내려주는 CSS는 보통 그 변수를 다시 정의하는 몇 줄이다:

    :root { --color-accent: #20c997; --radius-btn: .25rem }

그 한 줄이 링크·기본 버튼·태그칩·포커스 링·그라데이션까지 한꺼번에 바꾼다.
다크모드가 이미 같은 방식으로 동작하므로(.dark가 같은 변수를 덮어쓴다) 이건
새로 만든 장치가 아니라 **이미 돌고 있는 장치에 입구를 낸 것**이다.

누구의 스킨이 나가는가:
  · `GET /api/skin`            → **사이트 스킨** = 주인(admin)의 것. `/blog`(전체 모아보기)가 쓴다.
  · `GET /api/skin?handle=x`   → 그 사람의 것. `/@x` 화면이 쓴다.
  · `PUT /api/skin`            → **자기 행에** 쓴다.

PUT이 자기 행에 쓰는 게 2026-08-18 오후에 바뀐 부분이다. 그 전엔 누가 저장하든 주인
행에 썼는데(주소가 하나뿐이라 그게 곧 화면이었다), `/@handle`이 생기면서 그 규칙이
틀려졌다 — 글쓴이가 저장한 값이 남의 블로그에 나가게 된다. 지금은 저장한 사람과
그 값이 보이는 곳이 같다. 주인이 저장하면 그게 곧 사이트 스킨인 것도 그대로다
(사이트 스킨 = 주인 행이므로).
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_writer
from app.models.user import User
from app.schemas.user import SkinUpdate

router = APIRouter(prefix="/skin", tags=["skin"])


class SkinOut(BaseModel):
    css: str


def _owner(db: Session) -> User | None:
    # main.py의 /api/blog-owner와 같은 규칙 — role=admin 중 id가 가장 작은 사람.
    return db.scalar(select(User).where(User.role == "admin").order_by(User.id))


@router.get("", response_model=SkinOut)
def get_skin(handle: str | None = None, db: Session = Depends(get_db)):
    """지금 적용 중인 스킨. **무인증**이다 — 방문자 전원이 받아야 화면이 그려진다.

    빈 문자열은 '기본 스킨'을 뜻한다. 404를 주지 않는 이유는, 스킨이 없는 게
    정상 상태이기 때문이다. 없을 때 에러를 주면 프론트가 매 방문마다 실패를
    처리해야 하고, 그 처리를 빠뜨리면 콘솔이 빨개진다.

    레이트리밋을 걸지 않았다. 이 응답은 사용자 입력 하나를 읽어 그대로 돌려주는
    단일 행 조회이고, 모든 방문자가 첫 화면에서 반드시 한 번 부른다 — 여기에
    분당 한도를 걸면 정상 방문자가 먼저 걸린다.
    """
    if handle:
        # 없는 핸들이면 빈 스킨이다(404가 아니다). 스킨은 장식이라, 화면이 이것 하나
        # 때문에 실패 경로를 타면 손해가 더 크다 — 아래 docstring의 이유와 같다.
        target = db.scalar(
            select(User).where(func.lower(User.handle) == handle.strip().lower())
        )
    else:
        target = _owner(db)
    return SkinOut(css=(target.custom_css if target else None) or "")


@router.get("/me", response_model=SkinOut)
def get_my_skin(me: User = Depends(require_writer)):
    """**내** 스킨. 편집기가 '지금 값'을 채울 때 쓴다.

    왜 `GET /api/skin`으로 안 되나 — 그건 **사이트 스킨**(주인 것)이다. 글쓴이가 편집기를
    열면 남의 CSS가 채워지고, 그걸 저장하면 자기 스킨이 남의 것 사본이 된다.
    저장(PUT)이 자기 행에 쓰므로 읽기도 자기 행이어야 짝이 맞는다.

    주인이 부르면 결과가 `GET /api/skin`과 같다(사이트 스킨 = 주인 행). 규칙이 하나라
    두 경로가 어긋날 자리가 없다.
    """
    return SkinOut(css=me.custom_css or "")


@router.put("", response_model=SkinOut)
def put_skin(
    data: SkinUpdate,
    db: Session = Depends(get_db),
    me: User = Depends(require_writer),
):
    """스킨을 저장한다. **자기 것만** 바꾼다.

    글쓴이도 바꿀 수 있다(require_writer). 자기 블로그(`/@handle`)에 그 값이 나가므로
    저장한 사람과 보이는 곳이 일치한다. 주인이 저장하면 그게 곧 사이트 스킨이다 —
    `GET /api/skin`(핸들 없음)이 주인 행을 읽기 때문이고, 규칙이 하나라 어긋날 자리가 없다.

    ⚠️ 2026-08-18 오후에 `require_admin` → `require_writer`로 넓히면서 대상도 '주인 행'에서
    '자기 행'으로 바꿨다. 둘 중 하나만 바꾸면 글쓴이가 저장한 값이 **남의 블로그에** 나간다.

    빈 문자열(또는 공백만)은 NULL로 저장한다 = 기본 스킨으로 되돌린다.
    되돌리는 방법이 없으면 한 번 망친 사람이 화면을 못 고친다.
    """
    target = me
    css = data.custom_css.strip()
    target.custom_css = css or None
    db.commit()
    return SkinOut(css=target.custom_css or "")

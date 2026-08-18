"""블로그 스킨 — 외형을 코드 배포 없이 바꾼다.

프론트가 색·모서리를 CSS 변수로 노출하므로(frontend/src/index.css의 @theme),
여기서 내려주는 CSS는 보통 그 변수를 다시 정의하는 몇 줄이다:

    :root { --color-accent: #20c997; --radius-btn: .25rem }

그 한 줄이 링크·기본 버튼·태그칩·포커스 링·그라데이션까지 한꺼번에 바꾼다.
다크모드가 이미 같은 방식으로 동작하므로(.dark가 같은 변수를 덮어쓴다) 이건
새로 만든 장치가 아니라 **이미 돌고 있는 장치에 입구를 낸 것**이다.

누구의 스킨이 나가는가 — 지금은 주인(admin) 것 하나다. 이 사이트는 블로그 주소가
/blog 하나뿐이라 여러 사람의 스킨을 동시에 적용할 자리가 없다. 글쓴이마다 자기
주소가 생기면 그때 이 라우터가 그 사람의 행을 고르면 된다(컬럼은 이미 users에 있다).
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_admin
from app.models.user import User
from app.schemas.user import SkinUpdate

router = APIRouter(prefix="/skin", tags=["skin"])


class SkinOut(BaseModel):
    css: str


def _owner(db: Session) -> User | None:
    # main.py의 /api/blog-owner와 같은 규칙 — role=admin 중 id가 가장 작은 사람.
    return db.scalar(select(User).where(User.role == "admin").order_by(User.id))


@router.get("", response_model=SkinOut)
def get_skin(db: Session = Depends(get_db)):
    """지금 적용 중인 스킨. **무인증**이다 — 방문자 전원이 받아야 화면이 그려진다.

    빈 문자열은 '기본 스킨'을 뜻한다. 404를 주지 않는 이유는, 스킨이 없는 게
    정상 상태이기 때문이다. 없을 때 에러를 주면 프론트가 매 방문마다 실패를
    처리해야 하고, 그 처리를 빠뜨리면 콘솔이 빨개진다.

    레이트리밋을 걸지 않았다. 이 응답은 사용자 입력 하나를 읽어 그대로 돌려주는
    단일 행 조회이고, 모든 방문자가 첫 화면에서 반드시 한 번 부른다 — 여기에
    분당 한도를 걸면 정상 방문자가 먼저 걸린다.
    """
    owner = _owner(db)
    return SkinOut(css=(owner.custom_css if owner else None) or "")


@router.put("", response_model=SkinOut)
def put_skin(
    data: SkinUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """스킨을 저장한다. 주인(admin)만 바꿀 수 있다.

    ⚠️ 저장하는 사람과 적용되는 대상이 같아야 한다. `admin`이 여럿이면 두 번째
    admin이 저장한 값은 **저장은 되는데 화면엔 안 나온다**(get_skin이 id가 가장
    작은 admin을 보기 때문). 이 저장소에서 여러 번 나온 '만들어져 있는데 연결이
    없는' 모양이라, 그럴 땐 자기 행이 아니라 **주인 행에 쓴다**.
    지금 계정은 admin 하나뿐이라 두 경로가 같은 행을 가리킨다.

    빈 문자열(또는 공백만)은 NULL로 저장한다 = 기본 스킨으로 되돌린다.
    되돌리는 방법이 없으면 한 번 망친 사람이 화면을 못 고친다.
    """
    target = _owner(db) or admin
    css = data.custom_css.strip()
    target.custom_css = css or None
    db.commit()
    return SkinOut(css=target.custom_css or "")

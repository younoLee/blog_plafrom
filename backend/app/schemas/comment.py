from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import SafeModel


class CommentCreate(SafeModel):
    # author는 DB varchar(50)에 맞춤, content는 과대입력 방지. 넘으면 422
    author: str = Field(min_length=1, max_length=50)
    content: str = Field(min_length=1, max_length=2000)


class CommentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    post_id: int
    author: str
    content: str
    created_at: datetime
    # 이 댓글이 **로그인 계정**으로 작성됐는가. author로는 알 수 없다 — 익명이 회원과
    # 같은 이름을 칠 수 있다(2026-08-10 재현). 화면은 이 값이 True일 때만 회원 표시를
    # 붙여야 한다. user_id는 안 내보낸다(그건 신원이고, 화면에 필요한 건 1비트뿐이다).
    is_member: bool
    # 이 댓글을 **누가** 썼는지의 1비트 둘. 이름으로는 알 수 없다 — 표시명은 아무나
    # 같은 값을 넣을 수 있고(중복 검사가 없다), 서버가 그 이름을 그대로 고정해 박는다.
    # 2026-08-19 보안검사가 재현했다: 초대받은 계정이 `PATCH /api/auth/me`로 주인의
    # 표시명을 그대로 넣으면 댓글에서 주인과 화면상 구분이 안 됐다.
    #
    # **이름 쪽을 막지 않는 이유**는 comments.py 주석에 있다 — 동형문자로 우회되고,
    # "그 이름은 계정이다"를 알려주는 무인증 열거 오라클이 된다. 대신 서버가 **id로**
    # 판정한 사실을 하나 더 내보낸다. 이름을 아무리 베껴도 이 값은 안 붙는다.
    is_owner: bool  # 이 블로그 주인이 쓴 댓글인가
    is_author: bool  # 이 글을 쓴 사람이 쓴 댓글인가

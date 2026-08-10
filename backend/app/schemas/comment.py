from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CommentCreate(BaseModel):
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

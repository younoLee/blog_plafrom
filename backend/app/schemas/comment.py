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
    # **보는 사람이 쓴 댓글인가.** 화면이 '내 댓글 지우기·고치기'를 그릴 근거다
    # (09-04 검사 GAP-5 — 그전까지 삭제는 글쓴이·관리자만이라, 회원이 자기 실수를
    # 스스로 못 지웠다). user_id 를 내보내지 않는 규칙은 그대로 지킨다 — 이건 신원이
    # 아니라 **보는 사람 자신에 대한 1비트**이고, 익명 댓글에는 언제나 false 다.
    # 수정도 같은 비트로 그린다(내용만 바꿀 수 있고 작성자명·시각은 고정이다).
    is_mine: bool = False


# 댓글 수정 — **내용만** 바꾼다.
#
# 작성자명을 못 바꾸는 이유는 create 와 같다(사칭). 시각도 안 바꾼다 — '언제 쓴 말인가'가
# 대화의 순서를 만들기 때문이다. 수정 여부를 화면에 표시하지 않는 것은 이 저장소가
# 지금 두는 선택이고(댓글이 짧고 수가 적다), 바꾸려면 updated_at 컬럼이 먼저 필요하다.
class CommentUpdate(SafeModel):
    content: str = Field(min_length=1, max_length=2000)

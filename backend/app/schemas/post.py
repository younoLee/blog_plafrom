from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

# 공개범위는 이 두 값만 허용 (다른 값 보내면 422)
Visibility = Literal["public", "private"]

# 길이 제한: 제목은 DB varchar(200)에 맞춤, 본문은 과대입력(DoS) 방지 상한.
# 한도 넘으면 422(친절한 검증 오류)로 막힘 — 예전엔 검증이 없어 DB가 500을 냈음.
TITLE_MAX = 200
CONTENT_MAX = 50_000


# 클라이언트가 글 만들 때 보내는 데이터 (id·시각은 서버가 채움)
class PostCreate(BaseModel):
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    content: str = Field(min_length=1, max_length=CONTENT_MAX)
    visibility: Visibility = "public"


# 글 수정 시 보내는 데이터
class PostUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    content: str = Field(min_length=1, max_length=CONTENT_MAX)
    visibility: Visibility = "public"


# 서버가 클라이언트에 돌려주는 데이터 (DB의 모든 필드 포함)
class PostRead(BaseModel):
    # from_attributes=True: SQLAlchemy 객체(.속성)를 그대로 변환 가능하게
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content: str
    owner_id: int | None
    visibility: str
    created_at: datetime
    updated_at: datetime

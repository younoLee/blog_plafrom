from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict

# 공개범위는 이 두 값만 허용 (다른 값 보내면 422)
Visibility = Literal["public", "private"]


# 클라이언트가 글 만들 때 보내는 데이터 (id·시각은 서버가 채움)
class PostCreate(BaseModel):
    title: str
    content: str
    visibility: Visibility = "public"


# 글 수정 시 보내는 데이터
class PostUpdate(BaseModel):
    title: str
    content: str
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

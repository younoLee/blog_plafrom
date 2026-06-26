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

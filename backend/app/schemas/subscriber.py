from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr


# 구독 등록 시 받는 데이터 (EmailStr: 이메일 형식 자동 검증)
class SubscriberCreate(BaseModel):
    email: EmailStr


# 응답으로 돌려주는 데이터
class SubscriberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    created_at: datetime

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
    confirmed: bool  # 더블옵트인 확인 여부 (관리자 목록에서 '확인 대기' 구분용)
    created_at: datetime

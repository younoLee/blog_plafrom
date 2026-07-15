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


# 로그인 사용자 본인의 구독 상태 (구독 관리 페이지: '새 글 알림' 잠금 판단용)
class MySubscription(BaseModel):
    email: EmailStr
    subscribed: bool  # 내 계정 이메일이 '확인된' 구독 상태인지

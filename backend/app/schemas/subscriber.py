from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr

# 뉴스레터 구독은 2026-07-31에 폐지됐다(routers/subscribers.py 참고).
# 남은 건 관리자가 기존 구독자 주소를 조회·삭제하는 경로뿐이라, 응답 스키마 하나만 남긴다.
# 지운 것: SubscriberCreate(구독 신청 입력) · MySubscription(본인 구독 상태)


# 관리자 목록 응답
class SubscriberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    confirmed: bool  # 폐지 전 더블옵트인 확인 여부 (남은 데이터 구분용)
    created_at: datetime

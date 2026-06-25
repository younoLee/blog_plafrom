from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr


# 회원가입/로그인 시 받는 데이터
class UserCreate(BaseModel):
    email: EmailStr
    password: str


# 응답으로 돌려주는 사용자 정보 (비밀번호는 절대 포함 안 함)
class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    role: str  # pending / writer / admin / banned
    email_verified: bool
    created_at: datetime


# 로그인 성공 시 돌려주는 토큰
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

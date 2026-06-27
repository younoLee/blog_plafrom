from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field

# bcrypt는 72바이트 초과 비번에서 에러 → 상한 72. 가입/재설정은 최소 8자 요구.
PW_MIN = 8
PW_MAX = 72


# 로그인 시 받는 데이터 (기존 계정 호환 위해 최소길이 강제 안 함, 상한만)
class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(max_length=PW_MAX)


# 회원가입 시 받는 데이터 (새 비번이라 최소 길이 강제)
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=PW_MIN, max_length=PW_MAX)


# 응답으로 돌려주는 사용자 정보 (비밀번호는 절대 포함 안 함)
class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    role: str  # pending / writer / admin / banned
    email_verified: bool
    is_pro: bool  # 유료(고급 AI 모델 해금) 여부
    created_at: datetime


# 로그인 성공 시 돌려주는 토큰
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# 비밀번호 재설정 요청 (이메일 입력)
class ForgotPasswordRequest(BaseModel):
    email: EmailStr


# 새 비밀번호 설정 (메일 링크의 토큰 + 새 비번)
class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=PW_MIN, max_length=PW_MAX)

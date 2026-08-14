from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.base import SafeModel

# 상한 72는 '글자 수'다(Pydantic max_length). bcrypt의 72는 '바이트'라 단위가 다르다 —
# 한글은 글자당 3바이트라 이 상한을 통과한 값도 bcrypt엔 최대 216바이트로 들어간다.
# 그래서 bcrypt 안전은 여기가 아니라 core/security.py의 _bcrypt_input()이 책임진다
# (72바이트로 절삭). 두 값이 같은 72라 같은 제약처럼 보이는 게 함정이라 적어둔다.
# 가입/재설정은 최소 8자 요구.
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
    # 표시명. NULL이면 화면이 "회원 #id"로 폴백한다(이메일로 되돌아가지 않는다).
    # 2026-08-14까지 이 필드가 응답에 **아예 없어서** 설정 화면이 현재값을 못 보여줬고,
    # 그래서 바꿀 방법도 없었다 — 유일한 경로가 create_user.py였는데 그건 비번을 덮어쓴다.
    display_name: str | None = None
    # **입력은 EmailStr, 출력은 str.** 여기가 EmailStr이면 DB에 형식이 어긋난 행이
    # 하나만 있어도 `GET /admin/users`가 **응답 검증에서 터져 목록 전체가 500**이 된다.
    # 그리고 그 계정을 지울 유일한 화면이 바로 그 목록이라 복구 경로가 psql뿐이다.
    # 2026-08-11 동적 분석에서 실제로 재현했다 — `a@test.local`(예약 TLD) 한 행 때문에
    # 500이 났고, psql로 지운 뒤에야 200이 됐다.
    #
    # 출구에서 EmailStr이 지키는 건 없다. 이미 저장된 값을 다시 검증하는 것이고,
    # 형식 강제는 **입구**(UserCreate·RegisterRequest·create_user.py)의 일이다.
    # 얻는 것 없이 "한 행이 전체를 죽이는" 실패 모드만 만든다.
    email: str
    role: str  # pending / writer / admin / banned
    email_verified: bool
    is_pro: bool  # 유료(고급 AI 모델 해금) 여부
    pro_until: datetime | None = None  # 구독 만료 시각(없으면 None)
    created_at: datetime


# 로그인 성공 시 돌려주는 토큰
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# 비밀번호 재설정 요청 (이메일 입력)
class ForgotPasswordRequest(BaseModel):
    email: EmailStr


# 새 비밀번호 설정 (메일 링크의 토큰 + 새 비번)
class ResetPasswordRequest(SafeModel):
    token: str
    new_password: str = Field(min_length=PW_MIN, max_length=PW_MAX)


# 표시명 변경 — 내 것만 바꾼다.
#
# 왜 이 스키마가 생겼나 (2026-08-14): 구독 화면에서 글쓴이가 전부 "회원"으로 보여
# **누가 누군지 구분이 안 됐다.** 원인은 display_name이 전부 NULL인 것이고, 진짜
# 원인은 **그걸 정할 방법이 제품에 없었다**는 것이다. 유일한 경로가
# `create_user.py --display-name`인데 그건 같은 실행에서 비밀번호를 덮어쓴다.
#
# 최대 50자는 DB 컬럼(String(50))과 맞춘 값이다. 더 길면 422가 아니라 DB에서 터진다.
# 빈 문자열은 '안 정함'(NULL)으로 되돌리는 뜻으로 받는다 — 지우는 방법도 있어야 한다.
class DisplayNameUpdate(SafeModel):
    display_name: str = Field(max_length=50)

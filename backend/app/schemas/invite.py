from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.user import PW_MAX, PW_MIN


# 관리자가 초대를 발급할 때 보내는 것
class InviteCreate(BaseModel):
    email: EmailStr
    # Literal로 값을 스키마에서 막는다. 'admin'을 초대로 줄 수 있으면 링크 유출이
    # 곧 사이트 탈취다. 라우터가 아니라 여기서 막아야 다른 호출부가 생겨도 안전하다.
    role: Literal["pending", "writer"] = "pending"
    # 유효기간(일). 기본 7일 — 유출된 링크가 영원히 살아 있지 않게 하는 게 목적이라
    # 넉넉하게 잡지 않는다. 만료되면 다시 발급하면 그만이다.
    expires_days: int = Field(default=7, ge=1, le=30)


# 초대 목록 한 줄 (관리자 화면). 토큰은 여기 없다 — 해시만 저장하므로 복원 불가.
class InviteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    role: str
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None = None
    # '누가 들였나'. id가 아니라 이메일로 내보낸다 — 숫자만 보여주면 관리자가
    # 답을 얻으려고 결국 DB를 열어야 하고, 그러면 이 컬럼들을 남기는 이유가 없어진다.
    # 둘 다 발급자·가입계정이 지워지면 FK가 SET NULL이라 None이 될 수 있다.
    created_by_email: EmailStr | None = None
    used_by_email: EmailStr | None = None


# 발급 직후에만 돌려주는 응답. `url`이 원문 토큰이 실린 유일한 출력이고,
# 이 응답을 놓치면 다시 볼 방법이 없다(취소 후 재발급).
class InviteCreated(InviteOut):
    url: str
    # 이 주소가 SES에 검증돼 있는가 = '실재하고 그 사람이 메일함을 여는가'.
    # **None은 '모름'이다**(권한 없음·자격증명 없음·프로덕션 액세스라 무의미).
    # 화면은 False일 때만 경고하고 None이면 아무 말도 하지 않아야 한다 —
    # '확인 못 함'을 '문제 있음'으로 바꾸면 진짜 경고까지 무시하게 된다.
    recipient_verified: bool | None = None


# 토큰만 담는 요청 본문.
#
# **쿼리스트링이 아니라 본문인 이유**: 초대 토큰은 그 자체가 자격증명이다(쥐고 있으면
# 인증된 계정이 만들어진다). uvicorn의 액세스 로그는 요청 라인을 통째로 찍으므로
# `GET /api/auth/invite?token=...`으로 두면 원문 토큰이 컨테이너 로그에 평문으로 쌓인다
# — DB에 해시만 저장한 의미가 사라진다(models/invite.py 참고). 본문은 안 찍힌다.
# reset-password가 같은 이유로 이미 본문을 쓴다.
class InviteToken(BaseModel):
    token: str = Field(max_length=200)


# 초대 링크로 들어온 사람에게 보여줄 정보. 이메일을 화면에 '읽기 전용'으로
# 띄우기 위한 것 — 토큰을 이미 쥔 사람에게만 나가므로 노출이 아니다.
class InvitePreview(BaseModel):
    email: EmailStr
    role: str


# 초대 가입 요청. **이메일을 받지 않는다** — 주소는 토큰에 묶여 있고 서버가 그걸
# 쓴다. 폼에서 받으면 토큰과 어긋날 때 어떻게 할지를 또 정해야 하고, 안 정하면
# 그게 구멍이 된다. 받지 않으면 어긋날 수가 없다.
class InviteRedeem(BaseModel):
    token: str = Field(max_length=200)
    password: str = Field(min_length=PW_MIN, max_length=PW_MAX)

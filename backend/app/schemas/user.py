import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.html_slots import SLOT_MAX
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
    # 블로그 주소(`/@handle`). NULL이면 이 계정엔 개인 블로그가 없다.
    # 설정 화면이 '지금 값'을 보여주려면 응답에 있어야 한다 — display_name이 응답에
    # 없어서 바꿀 방법이 없던 2026-08-14의 일을 되풀이하지 않는다.
    handle: str | None = None
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


# 이메일 인증 토큰을 담는 요청 본문.
#
# **쿼리스트링이 아니라 본문인 이유** — 이 토큰은 그 자체가 자격증명이다(쥐고 있으면
# email_verified 가 켜진다). uvicorn 액세스 로그는 요청 라인을 통째로 찍으므로
# `POST /api/auth/verify?token=eyJ...` 로 두면 원문 토큰이 컨테이너 로그에 평문으로
# 쌓인다. 이 저장소는 같은 판단으로 초대 토큰(schemas/invite.py InviteToken)과
# 기기 endpoint(routers/push.py, 09-02)를 이미 본문으로 옮겼고, reset-password 도
# 처음부터 본문이다. **verify 만 안 옮겨져 있었다**(09-04 검사 SEC-07).
# 지금은 allow_signup=False 라 토큰이 발급되지 않아 도달 불가지만, 가입을 여는 날
# 바로 열리는 구멍이라 문을 열기 전에 닫는다.
#
# max_length 는 InviteToken 과 같은 200. JWT 는 그보다 짧고, 없으면 긴 문자열이
# 서명 검증까지 그대로 들어간다.
class VerifyEmailRequest(SafeModel):
    token: str = Field(max_length=200)


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

# 블로그 스킨(CSS) 저장 — 방문자 브라우저에서 실행될 스타일이라 입구에서 거른다.
#
# 이 값은 무인증으로 공개되고(GET /api/skin) 프론트가 <style>에 넣어 적용한다.
# 그래서 위험은 '못생긴 CSS'가 아니라 **CSS를 벗어나는 문자열**이다:
#
#   · `</style>` — HTML로 파싱되는 자리라면 태그를 닫고 밖으로 나간다. 지금 프론트는
#     텍스트 노드로 넣어서(React) 파싱되지 않지만, 정적 아카이브처럼 HTML을 문자열로
#     짜는 경로가 나중에 생기면 그때는 진짜 구멍이 된다. 입구에서 막아두면 그 경로가
#     생겨도 이미 안전하다 — '고친 자리 옆의 안 쓸린 입구'를 미리 닫는 쪽이다.
#   · `@import` — 외부 스타일시트를 끌어온다. CSP가 cdn.jsdelivr.net을 이미 허용하고
#     있어서 실제로 로드된다. 스킨 한 줄이 남의 CSS 전체를 데려오는 건 범위가 다르다.
#   · `javascript:` / `expression(` — 옛 브라우저에서 스크립트가 되는 형태.
#
# `<`를 통째로 막는 이유: CSS에 `<`가 필요한 문법이 없다. 문자 단위로 막는 쪽이
# `</style` 변형(`</ style`, `</STYLE`)을 일일이 쫓는 것보다 안 샌다.
#
# `\`(백슬래시)도 같은 이유로 통째로 막는다 (2026-09-02).
#   CSS 파서는 **식별자 안의 유니코드 이스케이프를 문자로 되돌린 뒤** at-rule을 찾는다.
#   그래서 `@\69 mport url(...)`는 소문자로 바꿔도 `@import`라는 글자가 없고, 위의
#   부분문자열 검사를 그대로 통과한 뒤 브라우저에서는 `@import`로 실행된다.
#   `javascript:`도 `\6a avascript:`로 같은 우회가 된다. 실제 피해가 되는 이유는
#   CSP가 style-src에 jsdelivr를 허용하기 때문이다(terraform/csp-function.js:27) —
#   `/gh/<아무 저장소>` 로 남의 CSS를 통째로 끌어올 수 있다.
#
#   이스케이프를 **해석해서** 검사하는 방법도 있지만(`\[0-9a-f]{1,6}\s?` 치환 후 재검사)
#   그건 브라우저의 토크나이저를 우리가 다시 구현하는 일이고, 한 글자만 달라도 다시
#   샌다. 금지 문자 하나를 더 얹는 쪽이 짧고 안 샌다 — `<`에서 이미 고른 답이다.
#
#   정상 스킨이 백슬래시를 필요로 하는가: **이 저장소에서는 아니다.** 확인한 것 —
#   frontend/src/App.css·index.css에 백슬래시가 0건, 테스트가 '평범한 스킨'으로 쓰는
#   예시도 `content: "읽기"`처럼 문자를 그대로 쓴다. 스킨의 용도가 색·모서리 변수와
#   레이아웃 조정이라 `content: "\2192"` 같은 코드포인트 표기가 필요한 자리가 없다
#   (필요하면 화살표 문자를 그대로 적으면 된다 — DB도 응답도 UTF-8이다).
#   막아서 잃는 것: 이스케이프 표기와 `\3a hover` 류의 별난 선택자. 얻는 것: 위 우회 전부.
#
# ⚠️ 막지 **않는** 것: `url(https://...)`. 배경 이미지로 방문자 접속이 외부에 알려질 수
# 있지만, 본문의 외부 이미지가 이미 같은 성질이고(img-src https:) 배경까지 막으면
# 스킨으로 할 수 있는 일이 크게 줄어든다. 감수하는 위험으로 적어둔다.
#
# 50KB는 넉넉한 상한이다 — 변수 몇 줄이 보통이고, 통째로 갈아엎는 스킨도 이 안에 든다.
# 빈 문자열은 '기본 스킨으로 되돌린다'는 뜻으로 받는다(NULL로 저장).
CSS_MAX = 50_000
_CSS_FORBIDDEN = ("<", "\\", "@import", "javascript:", "expression(")


class SkinUpdate(SafeModel):
    custom_css: str = Field(max_length=CSS_MAX)

    @field_validator("custom_css")
    @classmethod
    def _no_escape(cls, v: str) -> str:
        low = v.lower()
        for bad in _CSS_FORBIDDEN:
            if bad in low:
                raise ValueError(f"CSS에 쓸 수 없는 것이 있어: {bad}")
        return v


# 블로그 '내 문장' — 제목 아래·사이드바·푸터에 넣는 HTML.
#
# 여긴 **거절하지 않는다.** CSS는 금지 문자를 만나면 422로 막았지만(위), HTML은
# 허용 목록으로 **다시 쓴다**(app/core/html_slots.py). 이유:
#   · CSS의 `<`는 실수로 들어갈 일이 없어서 막으면 사람이 바로 안다.
#     HTML에서 `<div>`를 막으면 "왜 안 되는지"가 설명 없이는 안 보인다.
#   · 붙여 넣기 한 번에 `<span style>`·`<font>` 같은 게 잔뜩 딸려 온다. 그때마다
#     저장을 거절하면 사람은 어느 글자를 지워야 하는지 모른 채 갇힌다.
#   · 씻은 결과를 **응답으로 돌려주므로** 편집기가 그걸 다시 채운다 — 무엇이
#     사라졌는지 눈으로 보인다. 거절보다 이쪽이 배우기 쉽다.
#
# 길이만 여기서 본다. 씻기 전 원문 기준이라 상한이 조금 넉넉한 셈인데,
# 씻은 뒤는 항상 더 짧으므로 DB에 들어가는 값은 이 안에 든다.
class SlotsUpdate(SafeModel):
    intro: str = Field(default="", max_length=SLOT_MAX)
    aside: str = Field(default="", max_length=SLOT_MAX)
    footer: str = Field(default="", max_length=SLOT_MAX)

# 블로그 주소(handle) 정하기 — 주소에 그대로 박히는 값이라 입구에서 좁게 받는다.
#
# 허용: 영소문자·숫자·하이픈·밑줄, 2~20자. 대문자는 받아서 **소문자로 내린다**
# (거절하지 않는다 — 사람은 대문자로 쓰고 주소는 소문자인 게 자연스럽다).
#
# 막는 것과 이유:
#   · 한글·공백 — 주소에 들어가면 인코딩해야 하고, 인코딩한 파일명이 라이브에서 403이던
#     2026-08-17의 그 문제를 주소에서 다시 만든다.
#   · 하이픈·밑줄로 시작하거나 끝나기 — 보기에도 이상하고 `-`만으로 된 주소가 생긴다.
#   · 예약어 — `/@blog` 같은 걸 허용하면 나중에 그 이름의 진짜 경로를 못 만든다.
#     지금 존재하는 경로 이름과 흔히 쓸 이름을 미리 잠근다.
#
# 빈 문자열은 '주소를 없앤다'는 뜻으로 받는다(NULL로 저장). 한 번 정하면 못 지우는
# 상태를 만들지 않는다 — display_name과 같은 방침이다.
HANDLE_MIN, HANDLE_MAX = 2, 20
_HANDLE_RE = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{0,18}[a-z0-9])?$")
_HANDLE_RESERVED = {
    "admin", "api", "blog", "about", "login", "logout", "register", "settings",
    "status", "search", "new", "edit", "posts", "post", "tag", "tags", "rss",
    "feed", "sitemap", "static", "assets", "uploads", "devlog", "lessons",
    "pricing", "payment", "subscriptions", "verify", "forgot", "reset", "me",
    "null", "undefined", "www",
}


class HandleUpdate(SafeModel):
    handle: str = Field(max_length=HANDLE_MAX)

    @field_validator("handle")
    @classmethod
    def _shape(cls, v: str) -> str:
        v = v.strip().lower()
        if not v:
            return ""  # 빈 값 = 주소 없앰
        if len(v) < HANDLE_MIN:
            raise ValueError(f"주소는 {HANDLE_MIN}자 이상이어야 해")
        if not _HANDLE_RE.match(v):
            raise ValueError("영소문자·숫자·하이픈·밑줄만 쓸 수 있고, 하이픈/밑줄로 시작하거나 끝날 수 없어")
        if v in _HANDLE_RESERVED:
            raise ValueError(f"'{v}'는 사이트가 쓰는 이름이라 못 써")
        return v

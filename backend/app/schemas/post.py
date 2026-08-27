from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.base import SafeModel

# 공개범위는 이 세 값만 허용 (다른 값 보내면 422)
#  - public:      전체공개 (누구나)
#  - subscribers: 구독자공개 (그 작성자를 구독한 사람 + 본인 + 관리자)
#  - private:     나만 보기 (본인 + 관리자만)
Visibility = Literal["public", "subscribers", "private"]

# 길이 제한: 제목은 DB varchar(200)에 맞춤, 본문은 과대입력(DoS) 방지 상한.
# 한도 넘으면 422(친절한 검증 오류)로 막힘 — 예전엔 검증이 없어 DB가 500을 냈음.
TITLE_MAX = 200
CONTENT_MAX = 50_000
COVER_MAX = 500  # 커버 이미지 URL 길이 상한
TAG_MAX_COUNT = 10  # 글당 최대 태그 수
TAG_MAX_LEN = 30  # 태그 한 개 최대 길이
SERIES_MAX = 100  # 연재 이름 길이 상한 (DB varchar(100)에 맞춤)


# 글 생성/수정 공통 필드 (id·시각은 서버가 채움)
class _PostBody(SafeModel):
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    content: str = Field(min_length=1, max_length=CONTENT_MAX)
    # 커버 이미지 URL(선택). 빈 값이면 None으로 저장
    cover_image: str | None = Field(default=None, max_length=COVER_MAX)
    # 태그(선택·다중). 아래 검증에서 공백정리·빈값제거·중복제거·개수/길이 제한
    tags: list[str] = Field(default_factory=list)
    visibility: Visibility = "public"
    # 연재 이름(선택). 같은 이름끼리 한 시리즈. 빈 문자열은 None으로 정규화 —
    # 안 그러면 ''인 글끼리 '이름 없는 연재'로 묶여버린다.
    series: str | None = Field(default=None, max_length=SERIES_MAX)

    @field_validator("cover_image")
    @classmethod
    def _check_cover_image(cls, v: str | None) -> str | None:
        """커버 URL은 https(또는 same-origin 상대경로)만 받는다.

        보안이라기보단 '조용한 실패' 제거다: CSP가 `img-src 'self' data: https:`라
        http:// 커버는 브라우저가 차단해 화면에서 그냥 안 보인다. 저장은 됐는데
        이미지만 사라지니 원인을 알 방법이 없었다 → 저장 시점에 400으로 알려준다.

        http://localhost·127.0.0.1은 허용한다. 로컬 개발의 public_base_url이
        http://localhost:8000이라, 막으면 자기 업로더가 준 URL이 거부된다.
        """
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        # 백슬래시를 먼저 접는다 — 브라우저는 `/\host/x`를 `//host/x`와 같게 읽는다.
        # 접지 않으면 아래 `//` 검사가 백슬래시 한 글자로 뚫린다(2026-08-19 보안검사).
        v = v.replace("\\", "/")
        # '//host/x'는 프로토콜 상대 URL = 외부 호스트다. 상대경로처럼 보이지만
        # same-origin이 아니므로 '/'로 시작한다고 통과시키면 안 된다.
        if v.startswith("//"):
            raise ValueError("커버 이미지 주소는 https:// 로 시작해야 해")
        if v.startswith("/") or v.startswith("https://"):
            return v
        if v.startswith(("http://localhost", "http://127.0.0.1")):
            return v
        raise ValueError("커버 이미지 주소는 https:// 여야 해 (http는 브라우저가 차단해서 안 보여)")

    @field_validator("series")
    @classmethod
    def _clean_series(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for t in v:
            t = t.strip()
            if t and len(t) <= TAG_MAX_LEN and t not in out:
                out.append(t)
            if len(out) >= TAG_MAX_COUNT:
                break
        return out


class PostCreate(_PostBody):
    pass


class PostUpdate(_PostBody):
    pass


# 공개범위만 바꿀 때 (작성 후 상세 화면에서 빠르게 전환)
class PostVisibilityUpdate(BaseModel):
    visibility: Visibility


# 서버가 클라이언트에 돌려주는 데이터 (DB의 모든 필드 포함)
class PostRead(BaseModel):
    # from_attributes=True: SQLAlchemy 객체(.속성)를 그대로 변환 가능하게
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content: str
    cover_image: str | None
    tags: list[str]
    series: str | None
    owner_id: int | None
    # 상세 화면도 글쓴이를 그린다. PostSummary 와 같은 규칙이다(그쪽 주석 참고).
    # 기본값을 두는 이유: 이 스키마는 from_attributes 로 ORM 객체에서 바로 만들어지는
    # 자리가 여럿인데(작성·수정·공개범위 변경), 그 응답들은 방금 자기가 쓴 글이라
    # 글쓴이를 안 실어도 화면이 아쉽지 않다. 기본값이 없으면 그 세 곳이 전부
    # ValidationError 로 죽는다.
    author_name: str | None = None
    author_handle: str | None = None
    visibility: str
    created_at: datetime
    updated_at: datetime


# 목록용 — 본문 전체 대신 발췌+읽기시간만 담아 응답 크기를 줄인다(증폭 DoS·대역폭 방지).
# 본문 전체는 상세(GET /posts/{id}=PostRead)에서만 내려간다.
class PostSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    excerpt: str  # 마크다운 기호 벗긴 짧은 발췌
    reading_minutes: int  # 읽기 시간(분)
    cover_image: str | None
    tags: list[str]
    series: str | None  # 연재 이름. 목록에서 뱃지를 그리고 `/blog?series=` 로 잇는다
    owner_id: int | None
    # 글쓴이 표시용 (2026-08-27). 예전엔 owner_id 숫자뿐이라 **다중 글쓴이 플랫폼인데
    # 목록도 상세도 누가 쓴 글인지 표시할 수 없었다.** 그래서 `/@handle` 화면·필터·스킨이
    # 전부 만들어져 있는데도 앱 안에서 거기로 가는 링크가 자기 자신 주소 둘뿐이었다.
    #
    # handle 은 **공개 블로그를 가질 수 있는 역할일 때만** 채운다(PUBLIC_BLOG_ROLES).
    # 차단·승인취소된 사람의 `/@handle` 은 빈 목록이라(posts.py 의 author 필터가 같은
    # 조건을 건다), 링크를 그리면 빈 페이지로 보내게 된다. name 은 역할과 무관하게
    # 채운다 — 누가 썼는지는 회수 대상이 아니고 댓글·구독 목록에도 이미 나온다.
    author_name: str | None
    author_handle: str | None
    visibility: str
    created_at: datetime
    updated_at: datetime


# 목록 응답 봉투. 발췌만 담아도 '글 개수'가 무제한이면 응답이 계속 커지므로
# limit/offset으로 끊는다. total은 프론트 페이지 UI(전체 N개 중 몇 쪽)에 필요.
class PostList(BaseModel):
    items: list[PostSummary]
    total: int  # 필터(q·tag) + 공개범위를 적용한 전체 개수
    limit: int
    offset: int


class TagCount(BaseModel):
    tag: str
    count: int


# 사이드바용 집계. 목록이 페이지로 끊기면서 필요해졌다 — 사이드바가 현재 페이지만
# 보고 집계하면 2쪽에서 태그 목록·글 수가 그 페이지 기준으로 틀어진다.
class PostMeta(BaseModel):
    total: int
    tags: list[TagCount]
    # 연재 집계 (2026-08-27). 태그와 같은 모양이라 TagCount 를 그대로 쓴다.
    # 이게 없어서 연재는 **그 연재에 속한 글 하나를 이미 우연히 연 사람에게만** 보였다.
    # 1편부터 읽고 싶은 방문자에게는 입구가 없었다.
    series: list[TagCount]
    recent: list[PostSummary]


# 연재 목록의 한 항목 — 네비에 쓸 최소 정보만(발췌·본문 없음)
class SeriesItem(BaseModel):
    id: int
    title: str
    created_at: datetime


# 글 상세의 연재 네비. 이 글이 연재에 속하지 않으면 엔드포인트가 null을 준다.
class SeriesNav(BaseModel):
    series: str
    total: int  # 이 연재에서 '내가 볼 수 있는' 글 수
    index: int  # 이 글이 몇 번째인지 (1부터)
    items: list[SeriesItem]
    prev: SeriesItem | None  # 이전 편(더 오래된 글)
    next: SeriesItem | None  # 다음 편(더 최신 글)

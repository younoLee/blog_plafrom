from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

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


# 글 생성/수정 공통 필드 (id·시각은 서버가 채움)
class _PostBody(BaseModel):
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    content: str = Field(min_length=1, max_length=CONTENT_MAX)
    # 커버 이미지 URL(선택). 빈 값이면 None으로 저장
    cover_image: str | None = Field(default=None, max_length=COVER_MAX)
    # 태그(선택·다중). 아래 검증에서 공백정리·빈값제거·중복제거·개수/길이 제한
    tags: list[str] = Field(default_factory=list)
    visibility: Visibility = "public"

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
    owner_id: int | None
    visibility: str
    created_at: datetime
    updated_at: datetime

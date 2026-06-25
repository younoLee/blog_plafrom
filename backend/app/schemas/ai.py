from pydantic import BaseModel, Field


class DraftRequest(BaseModel):
    # 메모 길이 제한 = 입력 토큰(=비용) 상한
    memo: str = Field(min_length=1, max_length=5000)


class DraftResponse(BaseModel):
    markdown: str

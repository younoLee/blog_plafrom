from pydantic import BaseModel, Field


class DraftRequest(BaseModel):
    # 메모 길이 제한 = 입력 토큰(=비용) 상한
    memo: str = Field(min_length=1, max_length=5000)
    # 쓸 모델. 안 보내면 서버가 기본 모델(소넷). 허용 안 된 모델이면 403.
    # 카탈로그에 없는 커스텀 모델 ID도 가능(BYOK 전용) — 이땐 provider도 함께 보냄.
    # 모델ID는 짧다(예: meta-llama/llama-3.1-70b-instruct). 무제한이면 그대로 provider로 넘어가니 상한.
    model: str | None = Field(default=None, max_length=100)
    # 커스텀 모델일 때만 필요: 'openai' | 'gemini' (카탈로그 모델은 무시됨)
    provider: str | None = Field(default=None, max_length=20)


class DraftResponse(BaseModel):
    markdown: str
    model: str  # 실제로 어떤 모델로 생성했는지 (프론트 표시용)


# 서버키(Claude) 사용량 + 캡 (프론트에 '남은 횟수' 표시용). BYOK는 무제한이라 제외.
class UsageResponse(BaseModel):
    daily_used: int
    daily_cap: int
    monthly_used: int
    monthly_cap: int


# AI 모델 한 개 정보 (드롭다운용)
class AiModelInfo(BaseModel):
    id: str
    label: str
    provider: str  # claude / openai / gemini


# 현재 사용자가 고를 수 있는 모델 목록 + 기본값
class AiModelsResponse(BaseModel):
    models: list[AiModelInfo]
    default: str


# BYOK 키 등록 여부 (키 값은 절대 안 내려줌. base_url은 비밀 아니라 표시용으로 내려줌)
class KeyStatus(BaseModel):
    provider: str
    has_key: bool
    base_url: str | None = None


class KeysResponse(BaseModel):
    keys: list[KeyStatus]


# 키 저장 요청 (평문 키 — 저장 시 즉시 암호화). compatible은 base_url 필수
class SetKeyRequest(BaseModel):
    key: str = Field(min_length=10, max_length=500)
    base_url: str | None = Field(default=None, max_length=255)

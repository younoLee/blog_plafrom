"""AI 글 초안 생성 — 거친 메모를 정돈된 글 구조 마크다운으로.

제공자(provider) 3종:
- claude: 서버 키(settings.anthropic_api_key) 사용, 티어로 모델 게이팅
- openai / gemini: 사용자가 등록한 자기 키(BYOK) 사용

키가 없으면 각 단계에서 친절한 에러(503 등)로 라우터가 변환.
키는 .env / DB(암호문)에만 — 코드/커밋 금지.
"""

import anthropic

from app.core.config import settings
from app.models.user import User

# 전체 모델 카탈로그: id → (라벨, provider)
MODELS: dict[str, tuple[str, str]] = {
    # Claude — 서버 키, 티어 게이팅
    "claude-sonnet-4-6": ("Claude Sonnet 4.6 (기본)", "claude"),
    "claude-opus-4-8": ("Claude Opus 4.8 (고품질·결제)", "claude"),
    "claude-haiku-4-5": ("Claude Haiku 4.5 (저비용)", "claude"),
    # OpenAI — 사용자 키(BYOK)
    "gpt-4o": ("GPT-4o", "openai"),
    "gpt-4o-mini": ("GPT-4o mini (저비용)", "openai"),
    # Google — 사용자 키(BYOK)
    "gemini-2.5-flash": ("Gemini 2.5 Flash", "gemini"),
    "gemini-2.5-pro": ("Gemini 2.5 Pro", "gemini"),
}

# 기본 모델: 누구나 쓸 수 있는 소넷
DEFAULT_MODEL = "claude-sonnet-4-6"

# Claude 티어별 허용 집합
_CLAUDE_FREE = {"claude-sonnet-4-6", "claude-haiku-4-5"}  # Opus만 잠금
_CLAUDE_ALL = {"claude-sonnet-4-6", "claude-opus-4-8", "claude-haiku-4-5"}


def model_provider(model: str) -> str | None:
    info = MODELS.get(model)
    return info[1] if info else None


def allowed_models_for(user: User, providers_with_keys: set[str]) -> list[str]:
    """이 사용자가 고를 수 있는 모델 목록.
    - Claude: admin/유료=전부, 일반=Opus만 잠금(소넷+하이쿠)
    - OpenAI/Gemini: 그 provider 키를 등록했을 때만 노출
    """
    allowed: set[str] = set(_CLAUDE_ALL if (user.role == "admin" or user.is_pro) else _CLAUDE_FREE)
    for mid, (_label, prov) in MODELS.items():
        if prov in ("openai", "gemini") and prov in providers_with_keys:
            allowed.add(mid)
    # 카탈로그 순서 유지
    return [m for m in MODELS if m in allowed]


# Claude/GPT/Gemini 공통 지시. 출력이 '마크다운 글 구조'만 나오게 강하게 지시.
SYSTEM_PROMPT = """너는 기술 블로그 글쓰기를 돕는 편집자야.
사용자가 주는 거친 메모(음성 받아쓰기, 토막 생각 등)를 잘 정돈된 블로그 글의 '구조 + 초안'으로 바꿔줘.

규칙:
- 출력은 한국어 마크다운만. 인사말·설명·"네 알겠습니다" 같은 사족은 절대 쓰지 마.
- 맨 위에 `# 제목` 한 줄(메모 내용에 맞는 제목을 제안).
- 그 아래 `## 소제목`으로 단락을 나누고, 필요하면 `-` 불릿이나 번호 목록을 써.
- 메모에 있는 내용을 살려 자연스러운 문장으로 풀어 쓰되, 없는 사실을 지어내지 마.
- 내용이 부족한 부분은 `[여기에 ~를 더 써주세요]` 같은 플레이스홀더로 표시해.
"""

MAX_TOKENS = 4000  # 초안 1개에 충분하면서 비용 상한 역할


class AIKeyMissingError(RuntimeError):
    """필요한 API 키(서버 Claude 키 또는 사용자 BYOK 키)가 없을 때."""


def _claude(memo: str, model: str, api_key: str | None = None) -> str:
    # api_key 주면 사용자 BYOK 키, 아니면 서버 키
    key = api_key or settings.anthropic_api_key
    if not key:
        raise AIKeyMissingError("Claude 키 없음")
    client = anthropic.Anthropic(api_key=key)
    resp = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": memo}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def _openai(memo: str, model: str, api_key: str, base_url: str | None = None) -> str:
    from openai import OpenAI

    # base_url 지정 시 OpenAI 호환 엔드포인트(Grok/DeepSeek/OpenRouter/로컬 등)
    client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=model,
        max_tokens=MAX_TOKENS,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": memo},
        ],
    )
    return resp.choices[0].message.content or ""


def _gemini(memo: str, model: str, api_key: str) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model=model,
        contents=memo,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=MAX_TOKENS,
        ),
    )
    return resp.text or ""


def _cohere(memo: str, model: str, api_key: str) -> str:
    import cohere

    client = cohere.ClientV2(api_key=api_key)
    resp = client.chat(
        model=model,
        max_tokens=MAX_TOKENS,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": memo},
        ],
    )
    parts = resp.message.content or []
    return "".join(getattr(p, "text", "") for p in parts)


def generate_draft(
    memo: str,
    model: str = DEFAULT_MODEL,
    provider: str | None = None,
    user_key: str | None = None,
    base_url: str | None = None,
) -> str:
    """provider에 따라 분기. claude=서버키, 나머지=user_key(BYOK).
    provider 미지정 시 카탈로그에서 추론(커스텀 모델은 호출부가 명시).
    - claude(서버키) / anthropic(자기 Claude 키) → Anthropic
    - openai / compatible → OpenAI SDK (compatible은 base_url)
    - gemini → Google, cohere → Cohere"""
    provider = provider or model_provider(model)
    # 서버 Claude(claude) 또는 자기 Claude 키(anthropic)
    if provider == "claude":
        return _claude(memo, model)
    if provider == "anthropic":
        if not user_key:
            raise AIKeyMissingError("anthropic 키 미등록")
        return _claude(memo, model, user_key)
    if provider in ("openai", "gemini", "compatible", "cohere"):
        if not user_key:
            raise AIKeyMissingError(f"{provider} 키 미등록")
        if provider == "gemini":
            return _gemini(memo, model, user_key)
        if provider == "cohere":
            return _cohere(memo, model, user_key)
        # openai / compatible 모두 OpenAI SDK 사용 (compatible은 base_url 지정)
        return _openai(memo, model, user_key, base_url)
    raise ValueError(f"알 수 없는 모델/provider: {model} / {provider}")

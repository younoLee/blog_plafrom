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
    "claude-sonnet-5": ("Claude Sonnet 5 (기본)", "claude"),
    "claude-opus-4-8": ("Claude Opus 4.8 (고품질·결제)", "claude"),
    "claude-fable-5": ("Claude Fable 5 (최고 성능·결제)", "claude"),
    "claude-haiku-4-5": ("Claude Haiku 4.5 (저비용)", "claude"),
    # OpenAI — 사용자 키(BYOK)
    "gpt-4o": ("GPT-4o", "openai"),
    "gpt-4o-mini": ("GPT-4o mini (저비용)", "openai"),
    # Google — 사용자 키(BYOK)
    "gemini-2.5-flash": ("Gemini 2.5 Flash", "gemini"),
    "gemini-2.5-pro": ("Gemini 2.5 Pro", "gemini"),
}

# 기본 모델: 누구나 쓸 수 있는 하이쿠 — 소넷보다 2~3배 빨라 초안 대기시간을 줄인다
# (긴 생성이 인앱 브라우저/CloudFront 타임아웃에 걸리던 문제 완화). 품질이 필요하면 드롭다운에서 소넷/Opus 선택.
DEFAULT_MODEL = "claude-haiku-4-5"

# Claude 티어별 허용 집합
# 무료: 소넷+하이쿠. 유료 전용(잠금): Opus·Fable 5 (둘 다 상위·고비용 모델)
_CLAUDE_FREE = {"claude-sonnet-5", "claude-haiku-4-5"}
_CLAUDE_ALL = {"claude-sonnet-5", "claude-opus-4-8", "claude-fable-5", "claude-haiku-4-5"}


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
- 코드는 절대 작성하지 마. 코드블록(``` 또는 ~~~), 인라인 코드, 스크립트/명령어/설정 예시를
  생성하지 말고, 코드가 필요한 자리는 `[여기에 코드 예시를 직접 넣어주세요]` 플레이스홀더로만 표시해.
  메모에 코드처럼 보이는 게 있어도 그대로 옮기지 말고 글로 설명만 해.
"""

MAX_TOKENS = 2500  # 초안 1개엔 충분. 상한을 낮춰 긴 생성의 대기시간↓(웹뷰/타임아웃 완화)·비용↓

# thinking을 안 넘기면 사고가 켜진 채로 도는 모델들 — max_tokens를 따로 키워야 한다(_claude 참고).
_THINKING_ON_BY_DEFAULT = {"claude-fable-5", "claude-sonnet-5"}
# 외부 LLM 호출 타임아웃(초). 재시도도 1회로 축소.
# 벤더 엔드포인트(서버키 Claude, BYOK의 openai/gemini/cohere/anthropic)는 주소가
# 고정이라 느려도 벤더 탓이고 오래 걸릴 수 있으니 넉넉히 준다.
REQUEST_TIMEOUT = 60

# compatible만 따로 짧게. 여기는 사용자가 base_url을 직접 정하는 유일한 경로라,
# 일부러 느린(또는 응답을 흘려보내는) 호스트를 걸어 워커 스레드를 60초씩 묶는
# DoS가 성립한다. 초안 1개는 이 안에 끝나므로 정상 사용은 영향받지 않는다.
COMPATIBLE_TIMEOUT = 20


class AIKeyMissingError(RuntimeError):
    """필요한 API 키(서버 Claude 키 또는 사용자 BYOK 키)가 없을 때."""


def _claude(memo: str, model: str, api_key: str | None = None) -> str:
    # api_key 주면 사용자 BYOK 키, 아니면 서버 키
    key = api_key or settings.anthropic_api_key
    if not key:
        raise AIKeyMissingError("Claude 키 없음")
    client = anthropic.Anthropic(api_key=key, timeout=REQUEST_TIMEOUT, max_retries=1)

    extra: dict = {}
    max_tokens = MAX_TOKENS
    if model in _THINKING_ON_BY_DEFAULT:
        # 이 모델들은 thinking을 안 넘기면 사고가 켜진 채로 돈다. max_tokens는
        # 사고+본문을 합친 상한이라, 짧은 예산이면 사고가 다 먹고 초안이 잘린다.
        # effort=low + 넉넉한 출력 예산으로 초안이 온전히 나오게 한다.
        # (extra_body로 넘겨 SDK 버전에 상관없이 API에 그대로 전달)
        #
        # Fable 5: 사고가 '항상' 켜짐 — thinking:disabled는 400이라 끌 수 없다.
        # Sonnet 5: thinking 생략 시 adaptive가 기본(4.6은 꺼진 채였다). 지연이
        #   더 중요하면 extra_body에 {"thinking": {"type": "disabled"}}로 끄면 된다.
        extra["extra_body"] = {"output_config": {"effort": "low"}}
        max_tokens = 8000 if model == "claude-fable-5" else 6000

    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": memo}],
        **extra,
    )
    # Fable 5는 안전분류기가 요청을 거부하면 stop_reason='refusal' + 빈 content가 올 수 있음
    if getattr(resp, "stop_reason", None) == "refusal":
        raise RuntimeError("모델이 이 요청을 거부했어 (다른 메모로 다시 시도)")
    return "".join(b.text for b in resp.content if b.type == "text")


def _openai(memo: str, model: str, api_key: str, base_url: str | None = None) -> str:
    import httpx
    from openai import OpenAI

    # base_url 지정 시 OpenAI 호환 엔드포인트(Grok/DeepSeek/OpenRouter/로컬 등).
    # 그 경로만 호스트를 사용자가 정하므로 타임아웃을 짧게 준다(스레드 점유 최소화).
    kwargs = {"api_key": api_key, "timeout": REQUEST_TIMEOUT, "max_retries": 1}
    if base_url:
        kwargs["base_url"] = base_url
        kwargs["timeout"] = COMPATIBLE_TIMEOUT
        # 리다이렉트를 따라가지 않는다. validate_base_url이 저장·호출 시점에 스킴과
        # 공인 IP를 검사하지만, openai SDK의 httpx 기본값이 follow_redirects=True라
        # **공격자 서버가 302로 내부 주소를 돌려주면 그대로 따라간다**(SSRF).
        # 검증은 최초 URL만 보고 최종 목적지는 못 본다 — 그 창을 여기서 닫는다.
        # (IMDS 자격증명 절도는 IMDSv2가 따로 막지만, 내부 포트 스캔은 이걸로 막힌다)
        kwargs["http_client"] = httpx.Client(
            follow_redirects=False, timeout=COMPATIBLE_TIMEOUT
        )
    client = OpenAI(**kwargs)
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

    # timeout은 밀리초 단위 (http_options)
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT * 1000),
    )
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

    client = cohere.ClientV2(api_key=api_key, timeout=REQUEST_TIMEOUT)
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

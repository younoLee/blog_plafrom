"""AI 글 초안 생성 — Claude API로 거친 메모를 정돈된 글 구조 마크다운으로.

키(settings.anthropic_api_key)가 없으면 AIKeyMissingError를 던져서
라우터가 친절한 503 메시지로 바꿔줌. (키는 .env에만, 코드/커밋 금지)
"""

import anthropic

from app.core.config import settings

# Claude에게 주는 역할/규칙. 출력이 '마크다운 글 구조'만 나오게 강하게 지시.
SYSTEM_PROMPT = """너는 기술 블로그 글쓰기를 돕는 편집자야.
사용자가 주는 거친 메모(음성 받아쓰기, 토막 생각 등)를 잘 정돈된 블로그 글의 '구조 + 초안'으로 바꿔줘.

규칙:
- 출력은 한국어 마크다운만. 인사말·설명·"네 알겠습니다" 같은 사족은 절대 쓰지 마.
- 맨 위에 `# 제목` 한 줄(메모 내용에 맞는 제목을 제안).
- 그 아래 `## 소제목`으로 단락을 나누고, 필요하면 `-` 불릿이나 번호 목록을 써.
- 메모에 있는 내용을 살려 자연스러운 문장으로 풀어 쓰되, 없는 사실을 지어내지 마.
- 내용이 부족한 부분은 `[여기에 ~를 더 써주세요]` 같은 플레이스홀더로 표시해.
"""


class AIKeyMissingError(RuntimeError):
    """ANTHROPIC_API_KEY가 설정되지 않았을 때."""


def generate_draft(memo: str) -> str:
    if not settings.anthropic_api_key:
        raise AIKeyMissingError("ANTHROPIC_API_KEY 미설정")

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    response = client.messages.create(
        model=settings.ai_model,
        max_tokens=4000,  # 초안 1개에 충분하면서 비용 상한 역할
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": memo}],
    )
    # 응답 content는 블록 리스트 → text 블록만 이어붙임
    return "".join(block.text for block in response.content if block.type == "text")

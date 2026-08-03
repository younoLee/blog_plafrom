"""AI 초안 가드 v2 — 캐너리 + 출력단 기계 판정.

기존 가드(ai.py의 SYSTEM_PROMPT 역할 고정 + _as_material의 nonce 태그)는 '명령형
인젝션'을 확률적으로 막는다. 잘 듣지만 **뚫렸는지 알 방법이 없었다.** 이 모듈은 그
빈자리를 메운다 — 방어를 한 겹 더 쌓는 게 아니라, 뚫렸을 때 기계적으로 알아채는 층이다.

- 캐너리: 시스템 프롬프트에 매 요청 새 토큰을 심고 "절대 출력하지 마"라고 못박는다.
  출력에 그게 보이면 프롬프트 유출로 확정한다. 판정이 '느낌'이 아니라 문자열 일치
  하나로 끝난다는 게 요점.
- validate_draft: 출력이 약속한 마크다운 모양(`# 제목`으로 시작)이 아니면 인젝션 의심.
  형식 이탈은 "모델이 우리 지시 대신 메모를 따랐다"는 가장 싼 증거다.

**한계를 적어둔다.** 캐너리는 '프롬프트를 그대로 뱉는' 유출만 잡는다. 모델이 지침을
자기 말로 요약해서 흘리면 안 걸린다. 완전 커버가 아니라 값싼 탐지기다 — 그 값이
싸다는 게(호출 0회, 토큰 0개) 이걸 넣는 이유다.

**멀티턴 히스토리 강등(작업 지시서 §5)은 넣지 않았다.** 이 서비스엔 재생성/개선 요청이
없어서(초안은 1회 생성 후 에디터로 들어가고 끝) 강등할 history 자체가 존재하지 않는다.
지시서도 "재생성 기능 있을 때만"이라고 조건을 달아뒀다. 나중에 재생성을 붙이면 그때
사용자가 편집한 이전 출력을 assistant 롤로 되돌려 보내지 말 것 — 그게 "AI가 이미
동의했다"는 가짜 전제의 통로다.
"""

import hashlib
import re
import secrets
from functools import lru_cache

# 프롬프트가 시킨 거부 한 줄. 이건 정상 동작이지 형식 이탈이 아니다(ai.py와 같은 값).
REFUSAL_LINE = "이 기능은 블로그 초안 생성 전용입니다"

# 거부 응답으로 인정할 최대 길이. 거부는 한 줄이라고 시켰으므로, 이 문구를 담고 있어도
# 길면 "거부 문구를 인용하며 딴 걸 쓴" 것에 가깝다 → 형식 검사를 정상적으로 받게 한다.
_REFUSAL_MAX_LEN = 200

_FENCE = re.compile(r"```|~~~")


class GuardViolation(RuntimeError):
    """출력이 가드를 통과 못 했다.

    reason은 **로그용이지 사용자에게 보여주는 값이 아니다.** 어떤 입력이 어떤 가드에
    걸렸는지 알려주면 그게 그대로 공격자 피드백 루프가 된다(작업 지시서 §4).
    """

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def new_canary() -> str:
    """매 요청 새로 만든다. 재사용하면 한 번 유출된 값이 계속 유효해져서,
    공격자가 '이 토큰만 피해서 프롬프트를 뱉게' 유도할 수 있다."""
    return f"CNRY-{secrets.token_hex(8)}"


def memo_fingerprint(memo: str) -> str:
    """로그용 지문. **메모 원문은 절대 로그에 남기지 않는다.**

    같은 메모로 반복 시도하는 걸 상관짓기 위한 값일 뿐이라 12자면 충분하다.
    (역산 방지용 해시가 아니다 — 짧은 메모는 어차피 사전공격이 된다. 로그에 사용자
    글 원문이 쌓이는 걸 막는 게 목적이다.)
    """
    return hashlib.sha256(memo.encode("utf-8")).hexdigest()[:12]


def validate_draft(raw: str, canary: str) -> None:
    """치명 신호만 예외로 올린다. 통과하면 None.

    '치명'의 기준: 그대로 사용자에게 보내면 안 되는 것(유출) 또는 초안으로 못 쓰는
    것(빈 출력, 마크다운이 아닌 것). 고칠 수 있는 흠(코드 펜스)은 여기가 아니라
    ai.py의 _neutralize_code_fences가 접는다 — fence_signal() 주석 참고.
    """
    # 1) 프롬프트 유출. 다른 무엇보다 먼저 본다 — 유출된 출력은 형식이 멀쩡해도 나가면 안 된다.
    #
    # **정규화해서 본다.** 예전엔 `canary in raw`로 원문을 그대로 봤는데, 같은 모듈의
    # n-gram 쪽은 _normalize를 거치면서 여기만 안 거치는 비대칭이었다. 토큰 사이에
    # 줄바꿈 하나만 끼면("CNRY-\nab12…") 1차 탐지기가 눈을 감는다. 캐너리는
    # token_hex라 공백·대문자가 없으니, 공백 제거 + 소문자화로 오탐 위험 없이 좁힐 수 있다.
    if _normalize(raw).lower().find(canary.lower()) != -1:
        raise GuardViolation("canary_leak")

    text = raw.strip()
    if not text:
        # 빈 출력은 정상 초안이 아니다. 프론트가 빈 문자열을 에디터에 붙여넣으면
        # 사용자는 '아무 일도 안 일어났다'고 느낀다 — 실패로 말해주는 게 낫다.
        raise GuardViolation("empty")

    # 2) 프롬프트가 시킨 정상 거부는 통과. 모델이 문장부호를 붙이거나 조사를 다는
    #    경우가 있어 완전일치가 아니라 '짧고 그 문구를 담고 있으면'으로 본다.
    if REFUSAL_LINE in text and len(text) <= _REFUSAL_MAX_LEN:
        return

    # 3) 형식 이탈 = 인젝션 의심. 약속한 건 `# 제목`으로 시작하는 마크다운 하나뿐이고
    #    (SYSTEM_PROMPT [출력 형식]), 프론트도 그걸 전제로 에디터에 붙여넣는다.
    #    CommonMark에서 `#제목`(공백 없음)은 헤딩이 아니므로 공백까지 요구한다.
    if not text.startswith("# "):
        raise GuardViolation("schema_mismatch")


# ── 축자 유출 탐지(n-gram) ────────────────────────────────────────────────────
#
# 캐너리는 '그 토큰이 나온 경우'만 잡는다. 모델이 지침을 줄줄 뱉으면서 캐너리 줄만
# 빠뜨리거나 잘리면 안 걸린다. 그 틈을 메운다: 출력이 시스템 프롬프트와 **긴 연속
# 문자열**을 공유하면 유출로 본다.
#
# 25자인 이유 — 한국어 25자가 우연히 일치할 일은 사실상 없다. 짧게 잡을수록
# 흔한 표현("~하지 마라", "블로그 초안")에 걸려 오탐이 난다.
#
# **이건 축자 유출만 잡는다.** 모델이 지침을 자기 말로 풀어 쓰면 n-gram이 안 겹쳐서
# 통과한다. 캐너리(정확 일치) → n-gram(축자 재현)까지가 이 층의 한계고, 진짜 의역
# 유출은 여전히 못 잡는다.
_LEAK_NGRAM = 25

# 시스템 프롬프트에 있으면서 **정상 출력에도 당연히 나오는** 문자열.
# 안 빼면 멀쩡한 초안이 전부 유출로 잡힌다(플레이스홀더·거부 문구·헤딩 예시).
_LEGIT_ECHOES = (
    REFUSAL_LINE,
    "[여기에 코드 예시를 직접 넣어주세요]",
    "[여기에 ~를 더 써주세요]",
)

_WS = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """공백만 걷어낸다. 줄바꿈·들여쓰기를 바꿔 n-gram을 피해가는 걸 막되,
    그 이상 건드리면(조사 제거 등) 오탐이 늘어서 여기까지만 한다."""
    return _WS.sub("", text)


def _ngrams(text: str) -> set[str]:
    t = _normalize(text)
    return {t[i : i + _LEAK_NGRAM] for i in range(len(t) - _LEAK_NGRAM + 1)}


@lru_cache(maxsize=4)
def _system_ngrams(system_template: str) -> frozenset[str]:
    """시스템 프롬프트의 n-gram 집합. 템플릿(캐너리 치환 전)은 상수라 캐시가 항상 맞는다.

    정상 반향 문구는 \\x00으로 치환해 **경계를 끊는다.** 단순 삭제하면 앞뒤가 이어붙어
    원문에 없던 n-gram이 생기고, 그게 오탐의 원인이 된다.
    """
    s = _normalize(system_template)
    for legit in _LEGIT_ECHOES:
        s = s.replace(_normalize(legit), "\x00")
    return frozenset(
        g for g in (s[i : i + _LEAK_NGRAM] for i in range(len(s) - _LEAK_NGRAM + 1))
        if "\x00" not in g
    )


def verbatim_leak(raw: str, system_template: str, memo: str) -> bool:
    """출력이 시스템 프롬프트를 축자 재현했나.

    **memo에 있는 건 유출이 아니다.** 사용자가 자기 메모에 프롬프트 텍스트를 적었다면
    그건 우리가 흘린 게 아니라 사용자가 넣은 것이고, 그걸 막으면 '프롬프트 인젝션'을
    주제로 글 쓰는 사람이 자기 글을 못 쓰게 된다 — 작업 지시서 §7이 키워드 블랙리스트를
    기각한 바로 그 이유다. 이 블로그 주인이 실제로 그런 글(개발일지)을 쓰므로 가정이
    아니라 확실한 오탐 경로다. 그래서 메모 n-gram을 빼고 본다.
    """
    suspect = _ngrams(raw) & _system_ngrams(system_template)
    if not suspect:
        return False
    return bool(suspect - _ngrams(memo))


def fence_signal(raw: str) -> bool:
    """코드 펜스가 있었나 — **치명이 아니라 신호다.**

    지시서 원안은 형식 이탈을 전부 거부하지만, 여기선 펜스만 예외로 둔다. 이유는 둘:
    - _neutralize_code_fences가 이미 렌더 전에 접어서 안전하게 만든다(기존 방어).
    - 이 서비스는 **재시도를 안 한다**(ai.py VENDOR_MAX_RETRIES=0 주석 참고). 그래서
      여기서 422로 죽이면 곧바로 사용자에게 실패다 — 모델이 펜스 하나 흘린 것 말고는
      멀쩡한 초안까지 버리게 된다.
    치명으로 올리진 않되 로그엔 남긴다. 펜스 빈도가 튀면 그때 판단을 바꿀 근거가 된다.
    """
    return bool(_FENCE.search(raw))

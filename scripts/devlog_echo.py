"""초안 메아리 점검 — 새 개발일지가 지난 편들과 **같은 얘기**를 하는지 문장 단위로 잡는다.

왜 필요한가: 이 연재는 32편·27만 자고, 편마다 '오늘 배운 것'을 쓴다. 그런데 이 저장소의
교훈은 서로 비슷하게 생겼다(조용한 실패·낡은 목록·두 벌이 갈라지는 것…). 실제로 같은
교훈을 여러 편에서 다시 쓴 적이 있고, 그건 독자에게는 "저번에 읽은 것 같은데"가 되고
글쓴이에게는 **새로 배운 게 없는 날처럼** 보인다. 사람 기억으로는 27만 자를 못 뒤진다.

무엇을 하나: 초안의 문장을 지난 편들의 문장과 대조해 **많이 겹치는 짝**을 보여준다.
판단은 사람이 한다 — 이 스크립트는 "지웠어야 한다"고 말하지 않고 "여기 비슷한 게 있다,
그 편은 이거다"까지만 한다. 일부러 되짚는 것(앞 편을 이어받는 서술)은 이 연재의 관례라
자동으로 막으면 안 된다.

왜 형태소 분석기를 안 쓰나: 이 저장소의 로컬 파이썬에는 pip이 없다(sudo도 안 된다).
표준 라이브러리만으로 돈다 — n-gram 자카드면 '거의 같은 문장'을 잡는 데 충분하고,
이 도구의 목적은 정밀한 유사도 점수가 아니라 **사람이 다시 볼 자리를 고르는 것**이다.

사용:
  python scripts/devlog_echo.py content/devlog/2026-08-18.md      # 그 편 vs 나머지 전부
  python scripts/devlog_echo.py 초안.md --threshold 0.5           # 더 느슨하게 (기본 0.6)
  python scripts/devlog_echo.py content/devlog/2026-08-15.md --top 5

종료 코드는 항상 0이다. **이건 게이트가 아니라 읽을거리다** — 빌드를 세우면 일부러
되짚는 편을 쓸 수 없게 된다.
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEVLOG = ROOT / "content" / "devlog"

# 편마다 반복되는 상용구. 잡아봐야 전부 걸려서 신호가 죽는다.
# "회색 고정폭 글씨는…"은 실제로 첫 시험에서 100%로 걸렸다 — 범례 문장이라 당연하다.
BOILERPLATE = re.compile(
    r"^(입문자가 읽어도|이번 편의 형식|오늘 한 일|검증 —|관련:|회색 고정폭|이 글은 그날)"
)


def sentences(md: str) -> list[str]:
    """마크다운에서 산문 문장만. 코드블록·표·인용 지시문은 뺀다."""
    md = re.sub(r"```[\s\S]*?```", " ", md)  # 코드펜스
    out = []
    for line in md.splitlines():
        line = line.strip()
        # ▶는 이 연재가 "실제 출력" 앞에 붙이는 표식이라 편마다 반복된다.
        # 0.35로 낮춰 보다가 이것만 올라와서 알았다 — 구조는 겹쳐도 내용은 안 겹친다.
        if not line or line.startswith(("#", "|", ">", "!", "---", "▶")):
            continue
        line = re.sub(r"`[^`]*`", " ", line)  # 인라인 코드
        line = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line)  # 링크는 글자만
        line = re.sub(r"[*_>#`\[\]]", "", line)
        for s in re.split(r"(?<=[.!?다])\s+", line):
            s = s.strip(" -·")
            if len(s) >= 25 and not BOILERPLATE.match(s):
                out.append(s)
    return out


def grams(s: str, n: int = 4) -> set[str]:
    """공백을 지운 n-gram. 한국어는 띄어쓰기가 흔들려서 지우고 보는 게 안정적이다."""
    t = re.sub(r"\s+", "", s)
    return {t[i : i + n] for i in range(max(0, len(t) - n + 1))}


def similarity(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def main() -> None:
    ap = argparse.ArgumentParser(description="새 개발일지 초안이 지난 편과 겹치는지 본다")
    ap.add_argument("draft", help="점검할 마크다운 파일")
    ap.add_argument("--threshold", type=float, default=0.6, help="겹침 기준 (0~1, 기본 0.6)")
    ap.add_argument("--top", type=int, default=10, help="보여줄 개수 (기본 10)")
    args = ap.parse_args()

    draft_path = Path(args.draft)
    if not draft_path.exists():
        sys.exit(f"{draft_path} 가 없다.")

    draft_sents = sentences(draft_path.read_text(encoding="utf-8"))
    if not draft_sents:
        sys.exit("초안에서 문장을 못 찾았다. 마크다운이 맞나?")
    draft_grams = [(s, grams(s)) for s in draft_sents]

    # 지난 편들. 자기 자신은 뺀다(같은 파일을 두 번 세면 전부 1.0이다).
    past = []
    for f in sorted(DEVLOG.glob("*.md")):
        if f.resolve() == draft_path.resolve():
            continue
        for s in sentences(f.read_text(encoding="utf-8")):
            past.append((f.stem, s, grams(s)))

    hits = []
    for ds, dg in draft_grams:
        best = max(past, key=lambda p: similarity(dg, p[2]), default=None)
        if not best:
            continue
        score = similarity(dg, best[2])
        if score >= args.threshold:
            hits.append((score, ds, best[0], best[1]))

    hits.sort(reverse=True, key=lambda h: h[0])

    print(f"초안 {draft_path.name}: 문장 {len(draft_sents)}개 · 지난 편 문장 {len(past)}개와 대조")
    if not hits:
        looser = round(max(0.3, args.threshold - 0.15), 2)
        print(f"\n겹치는 문장 없음 (기준 {args.threshold}). 더 느슨하게 보려면 --threshold {looser}")
        return

    print(f"\n비슷한 문장 {len(hits)}건 — 상위 {min(args.top, len(hits))}건:\n")
    for score, ds, date, ps in hits[: args.top]:
        print(f"  [{score:.0%}] 초안: {ds[:90]}")
        print(f"        {date}: {ps[:90]}")
        print(f"        → content/devlog/{date}.md\n")

    print("판단은 사람이 한다 — 일부러 되짚는 것이면 그대로 두면 된다.")


if __name__ == "__main__":
    main()

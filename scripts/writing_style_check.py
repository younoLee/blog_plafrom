#!/usr/bin/env python3
"""글투 점검 — AI 티가 나는 강조 장치를 센다.

`docs/voice/style-guide.md`의 목표치와 대조한다. 그 지침은 사람이 쓴 기술 글
(NAVER D2 8편)과 우리 개발일지를 같은 방법으로 재서 나온 것이다.

    python3 scripts/writing_style_check.py content/devlog/2026-08-19.md
    python3 scripts/writing_style_check.py content/devlog/*.md

코드블록과 인용문(>)은 세지 않는다. 터미널 출력을 그대로 싣는 형식이라
그걸 포함하면 글투가 아니라 출력 길이를 재게 된다.
"""
import glob
import re
import statistics
import sys

# 1만 자 기준. 사람 글에 맞추는 게 아니라 그쪽으로 절반쯤 가는 선이다.
LIMITS = {
    "em대시": 10.0,   # 사람 1.4 / 우리(08-17) 71.5
    "굵게": 30.0,     # 사람 13.6 / 우리 83.8
    "소제목": 18.0,   # 사람 13.6 / 우리 25.0
}
MIN_SENT_LEN = 50  # 사람 67자 / 우리 40자


def prose_only(text: str) -> str:
    """코드블록·인용문을 뺀 본문만 남긴다."""
    text = re.sub(r"(?s)```.*?```", "", text)
    text = re.sub(r"(?m)^>.*$", "", text)
    return text


def measure(text: str) -> dict:
    body = prose_only(text)
    n = len(body)
    if n == 0:
        return {}
    sents = [
        s.strip()
        for s in re.split(r"(?<=[.!?다요])\s+", body)
        if 5 < len(s.strip()) < 400
    ]
    per10k = lambda c: round(c / n * 10000, 1)  # noqa: E731
    return {
        "글자": n,
        "문장": len(sents),
        "평균문장": round(statistics.mean(sents_len := [len(s) for s in sents]), 1) if sents else 0,
        "중앙문장": round(statistics.median(sents_len), 1) if sents else 0,
        "em대시": per10k(body.count("—")),
        "굵게": per10k(len(re.findall(r"\*\*[^*]+\*\*", body))),
        "소제목": per10k(len(re.findall(r"(?m)^#{2,3} ", body))),
        # 같은 구조를 셋 이상 반복하는 문장은 AI 문체의 지문이다(지침 4번).
        "삼항반복": len(re.findall(r"([^,.]{4,25}),\s*\1", body)),
    }


def main(paths: list[str]) -> int:
    files = [f for p in paths for f in sorted(glob.glob(p))]
    if not files:
        print("파일이 없다", file=sys.stderr)
        return 2

    bad = 0
    for path in files:
        with open(path, encoding="utf-8") as fh:
            m = measure(fh.read())
        if not m:
            continue
        print(f"\n{path}  ({m['글자']:,}자 · 문장 {m['문장']}개)")
        print(f"  문장 길이  평균 {m['평균문장']}자 · 중앙 {m['중앙문장']}자", end="")
        if m["평균문장"] < MIN_SENT_LEN:
            print(f"   ← 짧다 (목표 {MIN_SENT_LEN}자 이상)")
            bad += 1
        else:
            print()
        for key, limit in LIMITS.items():
            over = m[key] > limit
            bad += over
            print(f"  {key:6} {m[key]:6.1f} / 1만자   (한도 {limit})" + ("   ← 넘음" if over else ""))
        if m["삼항반복"]:
            print(f"  같은 구조 반복 {m['삼항반복']}곳   ← 지침 4번")

    print("\n" + ("고칠 자리 %d곳" % bad if bad else "지침 안에 있다"))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or ["content/devlog/*.md"]))

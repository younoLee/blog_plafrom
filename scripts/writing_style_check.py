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
    """코드블록·인용문·인라인 코드를 뺀 본문만 남긴다.

    2026-08-27: **인라인 코드 제거가 빠져 있었다.** 백틱으로 감싼 것도 그대로 세어져서,
    규칙을 인용하느라 적은 `—` 한 글자가 em대시 위반으로 잡혔다. 대시 두 개만 든
    시험 파일을 돌리니 487.8/1만자가 나왔다. 코드 안의 문자는 글투가 아니다.
    """
    text = re.sub(r"(?s)```.*?```", "", text)
    text = re.sub(r"(?m)^>.*$", "", text)
    text = re.sub(r"`[^`\n]*`", "", text)
    return text


# 절을 가르는 자리. 쉼표가 기본이고, 연결어미로 끝나는 절도 같이 자른다.
_CLAUSE_SPLIT = re.compile(r"[,，]|(?<=고)\s+|(?<=며)\s+")
# 비교할 때 지우는 것 — 공백과 따옴표. 조사는 안 지운다(지우면 서로 다른 절이 같아진다).
_NORMALIZE = re.compile(r"[\s'\"“”‘’]")


def triads(sent: str) -> bool:
    r"""한 문장 안에서 같은 구조가 셋 이상 반복되는가 (지침 4번).

    **왜 다시 만들었나 (2026-08-27)** — 예전 판은 `([^,.]{4,25}),\s*\1` 라는 역참조
    정규식이었다. 역참조는 **글자 그대로 같은 문자열**이 두 번 나와야만 잡히므로,
    지침 문서 자신이 표준 예문으로 적어둔 문장조차 못 잡았다. 실제로 잡히던 3건은
    전부 라우트 문자열과 역할 열거였다. 즉 지침 4번은 한 번도 측정된 적이 없다.

    이번 판은 **절의 앞머리**를 본다. 삼항 반복의 지문은 뒷말이 아니라 앞말이
    같다는 것이다("세 번 다 …, 세 번 다 …, 세 번 다 …").

    짧은 절은 뺀다 — 목록이나 열거("A, B, C")를 문장으로 오인하지 않으려는 것이다.
    """
    clauses = [c for c in _CLAUSE_SPLIT.split(sent) if c and len(c.strip()) >= 8]
    if len(clauses) < 3:
        return False
    heads: dict[str, int] = {}
    for c in clauses:
        head = _NORMALIZE.sub("", c)[:3]
        if len(head) < 3:
            continue
        heads[head] = heads.get(head, 0) + 1
    return any(v >= 3 for v in heads.values())


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
        "삼항반복": sum(1 for s in sents if triads(s)),
    }


# 이 탐지기가 다시 죽었을 때 알아채는 장치.
#
# **왜 필요한가** — 앞선 판은 역참조 정규식이라 아무것도 못 잡았는데, 잡히는 건수가
# 0이 아니어서(라우트 문자열 오탐 3건) 죽은 줄 몰랐다. 규칙이 있는데 한 번도 측정된
# 적이 없는 상태가 규칙이 없는 것보다 나쁘다. 잡아야 할 것과 잡으면 안 되는 것을
# 둘 다 박아둔다 — 잡는 것만 확인하면 '항상 참'인 탐지기와 구분할 수 없다.
#
# 첫 예문은 docs/voice/style-guide.md 규칙 4번의 표준 예문 그대로다. 지침이 예문을
# 고치면 여기도 같이 고쳐야 한다(그게 이 픽스처가 지침과 이어져 있다는 뜻이다).
SELFTEST_HITS = [
    "세 번 다 로컬에서는 초록이었고, 세 번 다 화면은 멀쩡했고, 세 번 다 내가 '됐다'고 말한 뒤였다.",
]
SELFTEST_MISSES = [
    "복원 656ms, 전송 포함 RTO 약 2초, 그리고 RPO는 마지막 정지 시점이다.",
    "글쓴이 이름을 목록에 그리고, 연재 뱃지를 붙이고, 사이드바에 연재 목록을 뒀다.",
    "이 값은 A, B, C 셋 중 하나다.",
]


def selftest() -> int:
    fail = 0
    for t in SELFTEST_HITS:
        if not triads(t):
            print(f"❌ 잡아야 하는데 놓쳤다: {t}", file=sys.stderr)
            fail += 1
    for t in SELFTEST_MISSES:
        if triads(t):
            print(f"❌ 잡으면 안 되는데 잡았다: {t}", file=sys.stderr)
            fail += 1
    # 인라인 코드가 실제로 걷혀야 em대시 계산이 맞는다(2026-08-27에 안 걷히고 있었다).
    if prose_only("가`—`나").count("—"):
        print("❌ prose_only가 인라인 코드를 안 걷어낸다", file=sys.stderr)
        fail += 1
    print("자가검증 실패 %d건" % fail if fail else "자가검증 통과")
    return 1 if fail else 0


# 지침 발효일. **이 날짜 이후에 쓴 글만** 검사 대상이다.
#
# docs/voice/style-guide.md 의 "안 바꾸는 것"에 "이미 발행된 33편 — 소급하지 않는다.
# 앞으로 쓰는 글에만 적용한다"고 적혀 있다. 그 결정을 **코드로 표현한 것**이 이 상수다.
# 산문으로만 적어두면 CI 에 붙일 수가 없다 — 인자 없이 돌리면 36편 전부를 재서
# 고칠 자리 106곳으로 영원히 빨간불이고, 영원히 빨간불인 검사는 잡으로 만들 수 없다.
#
# 파일명이 날짜인 것(content/devlog/YYYY-MM-DD.md)에 기댄다. 날짜가 안 붙은 경로는
# **거르지 않는다** — 사람이 직접 지목한 파일이라 그 판단을 뒤집지 않는다.
GUIDE_EFFECTIVE = "2026-08-18"  # #34가 처음 지침을 지켜 쓴 편

_DATED = re.compile(r"(\d{4}-\d{2}-\d{2})")


def after_guide(path: str) -> bool:
    m = _DATED.search(path)
    return m.group(1) >= GUIDE_EFFECTIVE if m else True


def main(paths: list[str]) -> int:
    if paths and paths[0] == "--selftest":
        return selftest()
    since = paths and paths[0] == "--since-guide"
    if since:
        paths = paths[1:] or ["content/devlog/*.md"]
    files = [f for p in paths for f in sorted(glob.glob(p))]
    if since:
        before = len(files)
        files = [f for f in files if after_guide(f)]
        print(f"지침 발효({GUIDE_EFFECTIVE}) 이후 {len(files)}편만 본다 (전체 {before}편)")
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
            # **종료코드에 넣는다.** 예전엔 인쇄만 하고 bad 를 안 올려서, 잡아도
            # CI 가 초록이었다. 이 저장소가 watch.sh 의 WARN 에서 이미 겪은 모양이다
            # ("경고가 아무에게도 안 갔다", 2026-07-22).
            bad += 1
            print(f"  같은 구조 반복 {m['삼항반복']}곳   ← 지침 4번")

    print("\n" + ("고칠 자리 %d곳" % bad if bad else "지침 안에 있다"))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or ["content/devlog/*.md"]))

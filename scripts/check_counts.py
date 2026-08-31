"""문서에 박힌 숫자가 실제와 맞는지 잰다.

## 왜 만들었나 (2026-08-31)

README.md 첫 화면이 '개발일지 28편'이라고 적고 있었다. 실제는 38편이다. ROADMAP.md는
26편, content/about.md는 '30편이 넘고'였다. 즉 **평가자가 가장 먼저 읽는 줄이 자산을
3분의 1 작게 말하고 있었다.** 설명 자료(docs/talk-track-project.md)의 숫자 카드도
'라우터 12 · 페이지 22'였는데 실제로는 11과 19다(전자는 `__init__.py`를 세고 있었고
후자는 `*.test.tsx`를 세고 있었다).

더 나쁜 것은 숫자가 틀렸다는 사실 자체가 아니라, **이 프로젝트가 기록으로 신뢰를 산다**는
점이다. 설명 자료가 직접 "숫자 하나가 어긋나면 그 자리에서 신뢰가 깎인다"고 적어놨다.
이 저장소는 같은 사고를 한 번 겪고 README.md에 "개수는 박지 않는다"는 주석까지 남겼는데
편수에는 그 규칙이 적용되지 않았다.

숫자를 한 번 고치는 것으로 끝내면 또 낡는다. 그래서 **재는 장치**를 같이 만든다.

## 무엇을 하지 않는가

**문서를 자동으로 고치지 않는다.** 다르면 실패하고 사람이 고친다 — tags.json 검사가
택한 방식과 같다. 문장은 사람이 쓰는 것이고, 숫자만 기계가 갈아끼우면 앞뒤 문장이
어긋난 채로 통과한다("28편이고 그중 절반은…" 같은 자리).

**커밋 수는 정확히 일치하라고 하지 않는다.** 그 값은 커밋할 때마다 늘어나므로 정확히
맞추라고 하면 문서를 고치는 그 커밋에서 다시 어긋난다. 영구 빨간불이 되고, 이 저장소가
반복해서 경계한 '아무도 안 보는 신호'가 된다. 대신 두 방향만 본다.
  · 문서값이 실제보다 **크면** 실패한다(없는 작업량을 말하는 것이다).
  · 실제보다 `COMMIT_SLACK` 이상 작으면 실패한다(너무 낡았다).

## 사용

    python3 scripts/check_counts.py            # 대조하고 어긋나면 종료코드 1
    python3 scripts/check_counts.py --measure  # 실측값만 출력(문서 고칠 때 참고)
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 커밋 수가 이만큼 뒤처지면 낡은 것으로 본다. 하루 커밋이 많을 때 20개쯤 나오므로
# 30이면 '며칠 지난 문서'는 통과하고 '몇 달 방치'는 걸린다.
COMMIT_SLACK = 30


def _git_commits() -> int:
    out = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return int(out.stdout.strip())


def _ci_jobs() -> int:
    """ci.yml의 jobs 아래 최상위 키 수. 워크플로 파일의 다른 키를 세지 않게 jobs 뒤만 본다."""
    text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    body = text.split("\njobs:\n", 1)[1]
    return len(re.findall(r"^  ([a-z0-9_-]+):", body, re.M))


# 이름 → (재는 법, 무엇을 세는지 한 줄). **정의가 한 줄로 떨어지는 것만 넣는다.**
# 애매한 것을 넣으면 이 검사 자신이 '무엇을 세는지 모르는 검사'가 된다.
MEASURES = {
    "devlog": (lambda: len(list((ROOT / "content/devlog").glob("*.md"))), "content/devlog/*.md 편수"),
    "migrations": (
        lambda: len(list((ROOT / "backend/alembic/versions").glob("*.py"))),
        "alembic 마이그레이션 파일 수",
    ),
    "backend_tests": (
        lambda: sum(
            len(re.findall(r"^def test_", p.read_text(encoding="utf-8"), re.M))
            for p in (ROOT / "backend/tests").rglob("*.py")
        ),
        "backend/tests의 test_ 함수 수",
    ),
    "commits": (_git_commits, "git rev-list --count HEAD"),
    "ci_jobs": (_ci_jobs, "ci.yml의 잡 수"),
    "routers": (
        lambda: len([p for p in (ROOT / "backend/app/routers").glob("*.py") if p.name != "__init__.py"]),
        "라우터 모듈 수(__init__.py 제외)",
    ),
    "pages": (
        lambda: len([p for p in (ROOT / "frontend/src/pages").glob("*.tsx") if ".test." not in p.name]),
        "프론트 화면 수(*.test.tsx 제외)",
    ),
}

# (파일, 정규식, 재는 이름). 정규식의 첫 그룹이 문서에 적힌 숫자다.
# **한 번도 안 걸리는 정규식은 실패로 본다** — 문장을 고치면서 이 검사가 조용히
# 대상 0개로 도는 것이 이 저장소가 가장 자주 만난 결함이다.
CLAIMS = [
    ("README.md", r"개발일지 (\d+)편", "devlog"),
    ("ROADMAP.md", r"개발일지 (\d+)편", "devlog"),
    ("content/about.md", r"연재는 (\d+)편이고", "devlog"),
    ("docs/talk-track-project.md", r"개발일지 (\d+)편이 읽는 글", "devlog"),
    ("docs/talk-track-project.md", r"\| 개발일지 \| (\d+)편", "devlog"),
    ("docs/talk-track-project.md", r"\| 커밋 \| (\d+) \|", "commits"),
    ("docs/talk-track-project.md", r"\| 백엔드 테스트 \| (\d+)개", "backend_tests"),
    ("docs/talk-track-project.md", r"\| DB 마이그레이션 \| (\d+) \|", "migrations"),
    ("docs/talk-track-project.md", r"라우터 (\d+) · 페이지 \d+", "routers"),
    ("docs/talk-track-project.md", r"라우터 \d+ · 페이지 (\d+)", "pages"),
    ("docs/talk-track-project.md", r"\| 자동 검사 묶음 \| (\d+) \|", "ci_jobs"),
    ("docs/talk-track-project.md", r"백엔드 테스트가 (\d+)개", "backend_tests"),
]


def main(argv: list[str]) -> int:
    actual = {}
    for name, (fn, what) in MEASURES.items():
        actual[name] = fn()
        if actual[name] <= 0:
            print(f"❌ 실측값이 0이다: {name} ({what}) — 세는 자리가 옮겨졌는지 확인할 것.")
            return 1

    if "--measure" in argv:
        for name, (_, what) in MEASURES.items():
            print(f"  {name:14} {actual[name]:>6}   {what}")
        return 0

    bad = 0
    for path, pattern, key in CLAIMS:
        f = ROOT / path
        if not f.exists():
            print(f"❌ {path} 가 없다 — 이 검사의 대상 목록을 고쳐라.")
            bad += 1
            continue
        text = f.read_text(encoding="utf-8")
        hits = re.findall(pattern, text)
        if not hits:
            print(f"❌ {path}: `{pattern}` 이 한 번도 안 걸린다 — 문장이 바뀌었으면 이 검사도 같이 고쳐라.")
            print("     (걸리는 게 없으면 이 줄은 '통과'가 아니라 '안 봤다'다)")
            bad += 1
            continue
        for hit in hits:
            claimed = int(hit)
            real = actual[key]
            if key == "commits":
                # 위 머리말 참고 — 정확히 일치를 요구하지 않는다.
                if claimed > real:
                    print(f"❌ {path}: 커밋 {claimed} 이라고 적었는데 실제는 {real} 이다(과장).")
                    bad += 1
                elif real - claimed > COMMIT_SLACK:
                    print(f"❌ {path}: 커밋 {claimed} 은 너무 낡았다(실제 {real}, 허용 {COMMIT_SLACK}).")
                    bad += 1
                else:
                    print(f"  --   {path}: 커밋 {claimed} (실제 {real}, 허용 안)")
            elif claimed != real:
                print(f"❌ {path}: {key} 를 {claimed} 이라고 적었는데 실제는 {real} 이다.")
                bad += 1
            else:
                print(f"✅ {path}: {key} {claimed}")

    if bad:
        print(f"\n어긋난 곳 {bad}건. **문서를 사람이 고친다** — 이 스크립트는 고치지 않는다.")
        print("실측값 보기: python3 scripts/check_counts.py --measure")
        return 1
    print("\n문서의 숫자가 전부 실측과 맞는다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

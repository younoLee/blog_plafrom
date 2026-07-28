"""의존성 취약점 검사 — pip-audit + npm audit을 돌리고 '판단 기록'과 대조한다.

왜 스크립트인가 — `npm audit --audit-level=high`를 CI에 그냥 걸면 오늘 당장 빨간불이다.
지금 뜨는 high 하나가 이 앱에 해당하지 않는 것(RSC 모드 전용)이기 때문이다. 그렇다고
`--audit-level=critical`로 낮추면 진짜 high가 와도 조용하다. 둘 다 틀렸다:

  영구 빨간불 = 아무도 안 보는 신호  /  영구 초록 = 검사가 없는 것

그래서 '판단한 것만 통과'로 바꾼다. 예외는 .vuln-allowlist.json에 근거·날짜와 함께
적고, 만료되면 다시 실패한다. 안 쓰이는 예외가 남아 있어도 실패한다 — 예외 목록이
조용히 쌓이는 게 이 부류 검사가 죽는 가장 흔한 방식이다.

사용:
  python3 scripts/check_vulns.py                     # 실패하면 exit 1 (CI 게이트)
  python3 scripts/check_vulns.py --today 2026-12-01  # 만료 동작 시험용
"""

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST = ROOT / ".vuln-allowlist.json"

BOLD = "\033[1m"
OFF = "\033[0m"

failures: list[str] = []
matched: set[str] = set()  # 실제로 쓰인 예외 id (안 쓰인 것을 찾으려고 센다)


def say(msg: str) -> None:
    print(f"\n{BOLD}{msg}{OFF}")


def ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def bad(msg: str) -> None:
    print(f"  ❌ {msg}")
    failures.append(msg)


def run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    """취약점 도구는 '발견'을 0이 아닌 종료코드로 알린다 — 실행 실패로 보면 안 된다."""
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    except FileNotFoundError:
        return 127, ""
    return p.returncode, p.stdout


def parse_json(out: str, code: int, tool: str) -> dict | None:
    """도구가 JSON 대신 다른 걸 뱉으면 traceback 말고 사람 말로 알린다.

    검사 도구가 검사보다 먼저 죽는 건 조용한 실패의 한 형태다 — 설치가 안 됐는데
    '취약점 없음'으로 읽히면 최악이다. 그래서 여기서 반드시 실패로 센다.
    """
    if not out.strip():
        bad(f"{tool}이 아무것도 출력하지 않았습니다(exit={code}). 설치돼 있나요?")
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        bad(f"{tool} 출력이 JSON이 아닙니다(exit={code}). 앞부분: {out.strip()[:160]}")
        return None


def judge(vuln_id: str, label: str, allowed: dict[str, dict]) -> None:
    if vuln_id in allowed:
        matched.add(vuln_id)
        ok(f"{vuln_id}  {label}  (판단 기록 있음 · ~{allowed[vuln_id]['expires']})")
    else:
        bad(
            f"{vuln_id}  {label} — 판단 기록이 없습니다. "
            "고치거나, 해당 없는 이유를 .vuln-allowlist.json에 근거와 함께 적으세요."
        )


def check_pip(allowed: dict[str, dict]) -> None:
    say("1/2 백엔드 의존성 (pip-audit)")
    code, out = run(
        ["pip-audit", "-r", "requirements.txt", "-f", "json", "--progress-spinner", "off"],
        ROOT / "backend",
    )
    data = parse_json(out, code, "pip-audit")
    if data is None:
        return
    deps = data.get("dependencies", [])
    found = 0
    for dep in deps:
        for v in dep.get("vulns", []):
            found += 1
            judge(v.get("id", "?"), f"{dep.get('name')} {dep.get('version')}", allowed)
    if found == 0:
        ok("취약점 없음")
    print(f"     (패키지 {len(deps)}개 검사)")


def check_npm(allowed: dict[str, dict]) -> None:
    say("2/2 프론트 의존성 (npm audit)")
    code, out = run(["npm", "audit", "--json"], ROOT / "frontend")
    data = parse_json(out, code, "npm audit")
    if data is None:
        return

    # 같은 권고(GHSA)가 여러 패키지에 걸쳐 중복 보고되므로 id로 묶는다.
    advisories: dict[str, str] = {}
    for name, v in data.get("vulnerabilities", {}).items():
        for via in v.get("via", []):
            if isinstance(via, dict) and via.get("url"):
                gid = via["url"].rsplit("/", 1)[-1]
                advisories.setdefault(gid, f"{name} ({via.get('severity')})")

    for gid, label in sorted(advisories.items()):
        judge(gid, label, allowed)
    if not advisories:
        ok("취약점 없음")
    print(f"     (npm 집계: {data.get('metadata', {}).get('vulnerabilities', {})})")


def main() -> None:
    today = date.today()
    if "--today" in sys.argv:  # 만료 동작을 실제로 시험해보기 위한 문
        today = date.fromisoformat(sys.argv[sys.argv.index("--today") + 1])

    doc = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    allowed: dict[str, dict] = {}
    expired: list[dict] = []
    for eco in ("npm", "pip"):
        for e in doc.get(eco, []):
            if date.fromisoformat(e["expires"]) < today:
                expired.append(e)
            else:
                allowed[e["id"]] = e

    check_pip(allowed)
    check_npm(allowed)

    say("판단 기록 점검")
    for e in expired:
        bad(
            f"{e['id']} — 예외가 {e['expires']}에 만료됐습니다. 다시 판단해서 고치거나 "
            f"날짜를 미루세요(자동 연장 없음). 다음 단계로 적어둔 것: {e.get('next_step', '없음')}"
        )
    for gid in sorted(set(allowed) - matched):
        bad(f"{gid} — 이제 안 뜨는 취약점입니다. .vuln-allowlist.json에서 지우세요(낡은 예외는 검사를 무디게 합니다).")
    if not expired and not (set(allowed) - matched):
        ok(f"예외 {len(allowed)}건 — 만료·미사용 없음")

    say("결과")
    if failures:
        print(f"  {len(failures)}건 — 위를 처리하세요.", file=sys.stderr)
        sys.exit(1)
    print("  통과.")


if __name__ == "__main__":
    main()

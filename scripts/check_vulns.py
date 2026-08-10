"""의존성 취약점 검사 — pip-audit + npm audit을 돌리고 '판단 기록'과 대조한다.

왜 스크립트인가 — `npm audit --audit-level=high`를 CI에 그냥 걸면 오늘 당장 빨간불이다.
지금 뜨는 high 하나가 이 앱에 해당하지 않는 것(RSC 모드 전용)이기 때문이다. 그렇다고
`--audit-level=critical`로 낮추면 진짜 high가 와도 조용하다. 둘 다 틀렸다:

  영구 빨간불 = 아무도 안 보는 신호  /  영구 초록 = 검사가 없는 것

그래서 '판단한 것만 통과'로 바꾼다. 예외는 .vuln-allowlist.json에 근거·날짜와 함께
적고, 만료되면 다시 실패한다. 안 쓰이는 예외가 남아 있어도 실패한다 — 예외 목록이
조용히 쌓이는 게 이 부류 검사가 죽는 가장 흔한 방식이다.

**"검사했는데 깨끗함"과 "검사를 못 함"을 반드시 구분한다.** 2026-07-28 심층검사에서
이 스크립트가 정확히 그 구분을 못 하고 있었다: npm 레지스트리가 안 잡히면 npm audit이
`vulnerabilities` 키 없이 `{"message":…,"error":…}`를 **정상 JSON으로** 내는데, 그걸
'취약점 0건'으로 읽고 초록을 냈다(실측 재현함). 검사 도구가 죽었는데 통과하는 게
이 파일이 막겠다고 써놓은 바로 그 실패였다. 그래서 지금은 도구 출력에 기대하는 키가
없으면 실패로 센다.

ID 표기 주의 — 같은 취약점이 도구에 따라 다른 id로 나온다(pip-audit은 PYSEC-…,
GitHub 권고 페이지는 GHSA-…). 그래서 allowlist의 id는 **도구가 출력한 값**과 맞추되,
도구가 alias를 함께 주면 그것도 인정한다.

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
# 생태계별로 '검사가 끝까지 갔는가'. 못 갔으면 그 생태계의 예외를 낡았다고 판정하면 안 된다
# (검사가 죽어서 아무것도 안 나온 걸 '이제 안 뜨는 취약점'으로 읽으면 정반대 조언이 된다).
scanned: dict[str, bool] = {"pip": False, "npm": False}


def say(msg: str) -> None:
    print(f"\n{BOLD}{msg}{OFF}")


def ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def bad(msg: str) -> None:
    print(f"  ❌ {msg}")
    failures.append(msg)


def run(cmd: list[str], cwd: Path) -> tuple[int, str, str]:
    """취약점 도구는 '발견'을 0이 아닌 종료코드로 알린다 — 실행 실패로 보면 안 된다."""
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    except FileNotFoundError:
        return 127, "", f"{cmd[0]} 를 찾을 수 없습니다"
    return p.returncode, p.stdout, p.stderr


def parse_report(out: str, err: str, code: int, tool: str, key: str) -> dict | None:
    """도구 출력을 '진짜 보고서'일 때만 돌려준다.

    `key`는 성공했을 때 반드시 있는 최상위 키다(npm=vulnerabilities, pip=dependencies).
    취약점이 0건이어도 그 키는 빈 값으로 존재하므로, 키의 유무로 '깨끗함'과
    '검사 못 함'을 가를 수 있다(둘 다 실측 확인).
    """
    if not out.strip():
        bad(f"{tool}이 아무것도 출력하지 않았습니다(exit={code}). {err.strip()[:120]}")
        return None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        bad(f"{tool} 출력이 JSON이 아닙니다(exit={code}). 앞부분: {out.strip()[:140]}")
        return None
    if not isinstance(data, dict) or key not in data:
        # npm audit은 레지스트리 장애를 이 모양(정상 JSON + error/message)으로 알린다.
        detail = ""
        if isinstance(data, dict):
            detail = str(data.get("message") or data.get("error") or "")
        bad(
            f"{tool}이 검사를 수행하지 못했습니다(exit={code}, '{key}' 없음). "
            f"→ 결과를 '취약점 없음'으로 읽으면 안 됩니다. {detail[:140]}"
        )
        return None
    return data


def judge(ids: set[str], label: str, allowed: dict[str, dict]) -> None:
    """id 또는 그 alias 중 하나라도 판단 기록에 있으면 통과."""
    hit = next((i for i in ids if i in allowed), None)
    shown = sorted(ids)[0] if ids else "?"
    if hit:
        matched.update(ids & set(allowed))
        ok(f"{hit}  {label}  (판단 기록 있음 · ~{allowed[hit]['expires']})")
    else:
        bad(
            f"{shown}  {label} — 판단 기록이 없습니다. 고치거나, 해당 없는 이유를 "
            f".vuln-allowlist.json에 근거와 함께 적으세요. (도구가 낸 id: {', '.join(sorted(ids))})"
        )


def check_pip(allowed: dict[str, dict]) -> None:
    say("1/2 백엔드 의존성 (pip-audit)")
    code, out, err = run(
        ["pip-audit", "-r", "requirements.txt", "-f", "json", "--progress-spinner", "off"],
        ROOT / "backend",
    )
    data = parse_report(out, err, code, "pip-audit", "dependencies")
    if data is None:
        return
    scanned["pip"] = True

    deps = data.get("dependencies", [])
    if not deps:
        # 0개를 검사하고 '깨끗하다'로 읽히면 안 된다. requirements.txt 경로가 틀렸거나
        # 해석이 통째로 실패한 경우가 여기로 온다(pip-audit은 그때도 exit 0을 낸다).
        bad("pip-audit이 패키지를 하나도 검사하지 않았습니다 — 감사가 성립하지 않았습니다.")
        return
    found = 0
    # 검사를 건너뛴 패키지를 '깨끗함'으로 세면 안 된다. pip-audit은 해석 못 한 항목에
    # skip_reason을 달고 vulns를 비운 채 내보낸다 — 그대로 두면 조용히 통과한다.
    skipped = [d.get("name", "?") for d in deps if d.get("skip_reason")]
    for dep in deps:
        for v in dep.get("vulns", []):
            found += 1
            ids = {v.get("id", "?")} | set(v.get("aliases", []) or [])
            judge(ids, f"{dep.get('name')} {dep.get('version')}", allowed)
    if skipped:
        bad(f"pip-audit이 건너뛴 패키지 {len(skipped)}개: {', '.join(skipped[:8])} — 검사되지 않았습니다.")
    if found == 0 and not skipped:
        ok("취약점 없음")
    print(f"     (패키지 {len(deps)}개 중 {len(deps) - len(skipped)}개 검사)")


def check_npm(allowed: dict[str, dict]) -> None:
    say("2/2 프론트 의존성 (npm audit)")
    code, out, err = run(["npm", "audit", "--json"], ROOT / "frontend")
    data = parse_report(out, err, code, "npm audit", "vulnerabilities")
    if data is None:
        return
    scanned["npm"] = True

    # 같은 권고(GHSA)가 여러 패키지에 걸쳐 중복 보고되므로 id로 묶는다.
    advisories: dict[str, str] = {}
    for name, v in data.get("vulnerabilities", {}).items():
        for via in v.get("via", []):
            if isinstance(via, dict) and via.get("url"):
                gid = via["url"].rsplit("/", 1)[-1]
                advisories.setdefault(gid, f"{name} ({via.get('severity')})")

    for gid, label in sorted(advisories.items()):
        judge({gid}, label, allowed)

    # npm 자신의 합계와 대조한다. 위 추출은 `via`가 dict이고 url이 있을 때만 세는데,
    # 전이 의존성에서 `via`는 **문자열**로 온다. 그래서 추출이 한 건도 못 하면
    # advisories가 비어 ✅ "취약점 없음"이 찍히고 **바로 다음 줄에 {'high': 3, ...}가
    # 같이 인쇄되는** 상태가 된다 — 단서가 화면에 있는데 판정이 그걸 안 보는 것이다
    # (2026-08-10 심층검사). 이 파일이 선언한 "검사했는데 깨끗함 ≠ 검사를 못 함"의
    # 마지막 한 칸이 비어 있었다. 합계가 0이 아닌데 추출이 0이면 **검사 실패**로 본다.
    meta = data.get("metadata", {}).get("vulnerabilities", {}) or {}
    meta_total = sum(v for k, v in meta.items() if k != "total" and isinstance(v, int))
    if not meta_total and isinstance(meta.get("total"), int):
        meta_total = meta["total"]
    if meta_total and not advisories:
        bad(
            f"npm은 취약점 {meta_total}건을 보고하는데 권고 id를 하나도 추출하지 못했습니다 "
            f"— 파서와 npm 출력 형식이 어긋났습니다(집계: {meta}). "
            "'취약점 없음'으로 넘기지 않습니다."
        )
    elif not advisories:
        ok("취약점 없음")
    print(f"     (npm 집계: {meta})")


def load_allowlist(today: date) -> tuple[dict[str, dict], list[dict], dict[str, str]]:
    """판단 기록을 읽는다. 파일이 깨져 있으면 traceback 말고 사람 말로 알린다."""
    try:
        doc = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    except FileNotFoundError:
        bad(f"{ALLOWLIST.name} 가 없습니다. 예외 정책 파일이라 없으면 검사를 신뢰할 수 없습니다.")
        return {}, [], {}
    except json.JSONDecodeError as e:
        bad(f"{ALLOWLIST.name} 가 올바른 JSON이 아닙니다: {e}")
        return {}, [], {}

    allowed: dict[str, dict] = {}
    expired: list[dict] = []
    eco_of: dict[str, str] = {}
    for eco in ("npm", "pip"):
        for e in doc.get(eco, []):
            vid = e.get("id")
            if not vid or "expires" not in e:
                bad(f"{ALLOWLIST.name} 항목에 id 또는 expires가 없습니다: {str(e)[:100]}")
                continue
            try:
                exp = date.fromisoformat(e["expires"])
            except ValueError:
                bad(f"{ALLOWLIST.name} 의 {vid} expires 값이 날짜가 아닙니다: {e['expires']}")
                continue
            eco_of[vid] = eco
            (expired.append(e) if exp < today else allowed.update({vid: e}))
    return allowed, expired, eco_of


def main() -> None:
    today = date.today()
    if "--today" in sys.argv:  # 만료 동작을 실제로 시험해보기 위한 문
        i = sys.argv.index("--today")
        if i + 1 >= len(sys.argv):
            sys.exit("--today 뒤에 날짜(YYYY-MM-DD)가 없습니다.")
        today = date.fromisoformat(sys.argv[i + 1])

    allowed, expired, eco_of = load_allowlist(today)

    check_pip(allowed)
    check_npm(allowed)

    say("판단 기록 점검")
    for e in expired:
        bad(
            f"{e['id']} — 예외가 {e['expires']}에 만료됐습니다. 다시 판단해서 고치거나 "
            f"날짜를 미루세요(자동 연장 없음). 다음 단계로 적어둔 것: {e.get('next_step', '없음')}"
        )
    # 검사가 끝까지 못 간 생태계의 예외는 '낡음' 판정에서 뺀다 — 스캔이 죽어서 안 나온 것을
    # '이제 안 뜨는 취약점이니 지우세요'로 안내하면, 그 조언대로 하는 순간 방어가 사라진다.
    stale = [g for g in sorted(set(allowed) - matched) if scanned.get(eco_of.get(g, ""), False)]
    unverifiable = sorted(set(allowed) - matched - set(stale))
    for gid in stale:
        bad(f"{gid} — 이제 안 뜨는 취약점입니다. .vuln-allowlist.json에서 지우세요(낡은 예외는 검사를 무디게 합니다).")
    for gid in unverifiable:
        print(f"  --  {gid} — 해당 생태계 검사가 실패해 확인 불가(위 ❌ 참고). 낡음 판정은 보류합니다.")
    if not expired and not stale:
        ok(f"예외 {len(allowed)}건 — 만료·미사용 없음")

    say("결과")
    if failures:
        print(f"  {len(failures)}건 — 위를 처리하세요.", file=sys.stderr)
        sys.exit(1)
    print("  통과.")


if __name__ == "__main__":
    main()

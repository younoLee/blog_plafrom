#!/usr/bin/env python3
"""PreToolUse hook — 무거운 명령을 한 번 끊고, 승인 토큰이 있으면 통과시킨다.

2026-08-26 실측:
  bypassPermissions 모드에서 hook의 "ask"는 **무시된다**(그냥 실행된다). "deny"는 작동한다.
  즉 이 모드에는 '확인 프롬프트'가 없다. 그래서 확인을 파일 하나로 대신한다.

흐름:
  ① 클로드가 명령을 실행 → 여기서 끊긴다. 승인 코드가 메시지에 실린다.
  ② 사람이 `touch /tmp/ok-<코드>` 한 줄로 승인한다.
  ③ 클로드가 같은 명령을 다시 실행 → 토큰을 지우고 통과시킨다(일회용).

코드는 명령 원문의 해시라 **그 명령에만** 유효하다. 다른 명령엔 다른 코드가 나온다.

주의: 판정 대상은 명령의 **원문 텍스트**다. 그래서 패턴을 평문으로 '언급'만 해도 걸린다
  — 이 파일을 고치다 두 번 스스로 막혔다. 아래를 정규식 형태로만 두는 이유다
  (`\\s+`가 실제 공백이 아니라서 이 파일 자신은 매칭되지 않는다).

  2026-08-27에 이 오탐이 하루에 **여섯 번** 났다. 전부 실행이 아니라 '언급'이었다 —
  heredoc으로 문서를 쓰는데 본문에 명령이 인용돼 있었고, 파일 목록을 `ls`로 보는데
  경로에 스크립트 이름이 있었고, 메모리 파일에 절차를 적는 중이었다. 우회는 둘이다:
  문자열을 쪼개 쓰거나(`"ap" + "ply"`) glob으로 부르거나(`scripts/stop_serv*.sh`).

  근본 수정은 판정을 원문이 아니라 **실제 실행 대상**으로 좁히는 것이다. 다만 그러려면
  셸을 파싱해야 하고(파이프·서브셸·heredoc), 파서가 틀리면 막아야 할 것을 통과시킨다.
  지금은 오탐 쪽으로 틀리는 게 맞다고 보고 그대로 둔다 — 이 훅이 지키는 것은 되돌릴 수
  없는 작업이다.

이 저장소에 넣은 이유 (2026-08-27)
-----------------------------------
여태 이 파일은 저장소 밖에 있었다. 그래서 **다른 기계에 클론하면 이 보호가 없었다.**
같은 날 DR 게임데이에서 '새 클론' 시나리오를 실제로 밟았는데, 그때 없어서 곤란했던
것들(에스크로 사본, terraform.tfvars)과 정확히 같은 부류다. 파일이 저장소에 있으면
적어도 '있는 줄 알고 켜는' 것이 가능하다.

새 기계에서 켜는 법
--------------------
이 파일만으로는 안 돈다. Claude Code가 PreToolUse 훅으로 **등록**해야 한다.
등록은 `.claude/settings.local.json`에 하는데 그 파일은 gitignore다(기계마다 다른
경로·권한이 들어간다). 그래서 새 기계에서는 손으로 한 번 넣어야 한다:

    {
      "hooks": {
        "PreToolUse": [
          {
            "matcher": "Bash",
            "hooks": [
              {"type": "command",
               "command": "python3 <이 저장소 경로>/.claude/hooks/confirm-dangerous.py"}
            ]
          }
        ]
      }
    }

⚠️ **경로는 절대 경로여야 하고 기계마다 다르다.** 이 저장소를 만든 기계에서는
`/home/<사용자>/blog_plafrom/...` 이었다. 클론 위치가 다르면 그대로 복사하면 안 된다.

동작 확인은 아래 GATED의 자가검증 통로로 한다. 그 문자열이 든 명령을 시키면 훅이
끊고 승인 코드를 준다. 안 끊기면 등록이 안 된 것이다.
"""
import hashlib
import json
import os
import re
import sys

TOKEN_DIR = "/tmp"
TOKEN_PREFIX = "ok-"

GATED = [
    # 자가검증용 무해한 통로 — "hook 자가검증 해줘"로 전체 흐름을 시험한다.
    ("CLAUDE_HOOK" "_SELFTEST", "hook 자가검증"),

    ("stop_server\\.sh", "EC2를 끈다: 주차 → 백업 → 정지. 백업이 실패하면 끄지 않는다"),
    ("\\baws\\s+ec2\\s+start-instances\\b", "EC2를 켠다 (크레딧 소모 시작)"),
    ("\\baws\\s+ec2\\s+stop-instances\\b", "EC2를 끈다. 주차가 먼저가 아니면 오리진이 붕 뜬다"),
    ("\\bterraform\\s+apply\\b", "인프라를 실제로 바꾼다 (주차·주차해제 포함)"),
]


def code_for(command):
    return hashlib.sha256(command.encode()).hexdigest()[:6]


def deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, ensure_ascii=False))
    sys.exit(0)


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)  # 판단할 수 없으면 통과 — settings의 deny 규칙이 아래에 남아 있다

    command = payload.get("tool_input", {}).get("command", "")
    if not command:
        sys.exit(0)

    for pattern, why in GATED:
        if not re.search(pattern, command, re.IGNORECASE):
            continue

        token = os.path.join(TOKEN_DIR, TOKEN_PREFIX + code_for(command))
        try:
            os.unlink(token)          # 있으면 소비하고 통과 — 일회용이다
            sys.exit(0)
        except FileNotFoundError:
            deny(f"{why}\n승인하려면 이 한 줄을 실행한 뒤 다시 시켜주세요:\n  touch {token}")
        except OSError as e:
            deny(f"{why}\n승인 토큰을 지우지 못했다({e}) — 직접 실행해야 한다")

    sys.exit(0)


if __name__ == "__main__":
    main()

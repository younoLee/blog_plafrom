#!/usr/bin/env bash
# 주입: <대상> <모드>
#
#   대상  db smtp s3 anthropic push toss openai gemini cohere none
#   모드  refuse hang error gone pass
#
# db·smtp 는 우리 컨테이너라 docker stop 으로 죽인다(07-28과 같은 방법).
# 나머지는 목적지가 바깥이라 blackhole 이 대신 받는다 — 모드 파일 한 줄로 바뀐다.
#
# **주입이 실제로 닿았는지 반드시 확인한다.** 안 닿았는데 앱이 멀쩡한 것을
# '견뎠다'로 읽으면 훈련이 거짓말을 한다. blackhole 은 /state/hits.log 에 기록한다.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
DC="docker compose -p chaos -f docker-compose.yml -f ops/chaos/docker-compose.chaos.yml"
TARGET="${1:-}"; MODE="${2:-refuse}"

case "$TARGET" in
  none)
    $DC start db mailpit >/dev/null 2>&1 || true
    $DC exec -T blackhole sh -c 'echo pass > /state/mode'
    echo "  원상 복구 — 모든 의존이 정상"
    ;;
  db)   $DC stop db      >/dev/null; echo "  db 정지 (07-28 ①과 동일)" ;;
  smtp) $DC stop mailpit >/dev/null; echo "  SMTP 정지 (07-28 ②와 동일)" ;;
  s3|anthropic|push|toss|openai|gemini|cohere)
    case "$MODE" in refuse|hang|error|gone|pass) ;; *) echo "모드가 잘못됐다: $MODE" >&2; exit 2 ;; esac
    $DC exec -T blackhole sh -c "echo $MODE > /state/mode"
    echo "  $TARGET → $MODE"
    echo "  ⚠️ blackhole 은 대상별이 아니라 **전역** 모드다. 한 번에 하나씩 재라."
    ;;
  *) echo "사용: inject.sh <db|smtp|s3|anthropic|push|toss|openai|gemini|cohere|none> [모드]" >&2; exit 2 ;;
esac

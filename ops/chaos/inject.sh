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
# 레인 — 여러 훈련을 동시에 돌리려면 스택이 서로 격리돼야 한다.
# 블랙홀 모드가 전역이라 한 스택을 공유하면 주입이 서로를 오염시킨다.
: "${CHAOS_LANE:=0}"
export COMPOSE_PROJECT_NAME="chaos${CHAOS_LANE}"
export CHAOS_PORT_API=$((18000 + CHAOS_LANE * 100))
export CHAOS_PORT_DB=$((15432 + CHAOS_LANE * 100))
export CHAOS_PORT_SMTP=$((11025 + CHAOS_LANE * 100))
export CHAOS_PORT_MAILUI=$((18025 + CHAOS_LANE * 100))
export CHAOS_PORT_WEB=$((15173 + CHAOS_LANE * 100))
export CHAOS_SUBNET="172.$((30 + CHAOS_LANE)).0"
export CHAOS_BASE="http://localhost:$CHAOS_PORT_API"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
DC="docker compose -f docker-compose.yml -f ops/chaos/docker-compose.chaos.yml"
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

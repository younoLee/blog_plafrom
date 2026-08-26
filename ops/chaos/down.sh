#!/usr/bin/env bash
# 정리. 볼륨까지 지운다 — 훈련 잔재를 남기지 않는다.
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
docker compose -f docker-compose.yml -f ops/chaos/docker-compose.chaos.yml down -v
echo "  격리 스택 제거 완료 (개발 스택은 그대로)"

#!/usr/bin/env bash
# 정리. 볼륨까지 지운다 — 훈련 잔재를 남기지 않는다.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
docker compose -p chaos -f docker-compose.yml -f ops/chaos/docker-compose.chaos.yml down -v
echo "  격리 스택 제거 완료 (개발 스택은 그대로)"

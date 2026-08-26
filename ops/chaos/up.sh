#!/usr/bin/env bash
# 격리 스택 기동. 개발 스택(8000·5432·1025)은 건드리지 않는다.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
"$HERE/make_ca.sh"
cd "$ROOT"
docker compose -p chaos -f docker-compose.yml -f ops/chaos/docker-compose.chaos.yml up -d
echo
echo "  백엔드   http://localhost:18000"
echo "  메일 UI  http://localhost:18025"
echo "  프론트   http://localhost:15173"
echo
echo "  다음: ops/chaos/probe.sh  ← **주입 전에 기준선을 먼저 찍는다**"
echo "        비교 대상이 없으면 '원래 그랬던 것'과 구분이 안 된다(07-28의 규칙)."

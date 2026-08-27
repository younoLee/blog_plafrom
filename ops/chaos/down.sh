#!/usr/bin/env bash
# 정리. 볼륨까지 지운다 — 훈련 잔재를 남기지 않는다.
set -euo pipefail
# 레인 설정은 lane.sh 하나에 있다 — 복붙본이 넷이라 갈라졌던 자리다(lane.sh 주석 참고).
. "$(dirname "${BASH_SOURCE[0]}")/lane.sh"
# pause 된 컨테이너가 있으면 down 이 걸린다. 08-27에 db hang(=docker pause)이 생겨
# 훈련이 중간에 죽으면 얼어붙은 채로 남는다 — 정리가 그것부터 풀어야 잔재가 안 남는다.
chaos_dc unpause db mailpit >/dev/null 2>&1 || true
chaos_dc down -v
echo "  격리 스택 제거 완료 (개발 스택은 그대로)"

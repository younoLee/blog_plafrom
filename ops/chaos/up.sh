#!/usr/bin/env bash
# 격리 스택 기동. 개발 스택(8000·5432·1025)은 건드리지 않는다.
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
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
"$HERE/make_ca.sh"

# 훈련용 VAPID 키쌍. 없으면 push_enabled가 False라 푸시 주입이 아무것도 안 잰다.
# 운영 키를 쓰지 않는다 — 훈련 스택이 실제 기기로 발송할 이유가 없다.
ENVF="$HERE/.env.chaos"
if [ ! -f "$ENVF" ]; then
  python3 - > "$ENVF" <<'PY'
import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

def b64(b): return base64.urlsafe_b64encode(b).decode().rstrip("=")

k = ec.generate_private_key(ec.SECP256R1())
pub = k.public_key().public_bytes(serialization.Encoding.X962,
                                  serialization.PublicFormat.UncompressedPoint)
priv = k.private_numbers().private_value.to_bytes(32, "big")
print(f"CHAOS_VAPID_PUBLIC={b64(pub)}")
print(f"CHAOS_VAPID_PRIVATE={b64(priv)}")
PY
  chmod 600 "$ENVF"
  echo "  훈련용 VAPID 키쌍 생성: $ENVF"
fi
set -a; . "$ENVF"; set +a

cd "$ROOT"
docker compose -f docker-compose.yml -f ops/chaos/docker-compose.chaos.yml up -d
echo
echo "  백엔드   http://localhost:18000"
echo "  메일 UI  http://localhost:18025"
echo "  프론트   http://localhost:15173"
echo
echo "  다음: ops/chaos/probe.sh  ← **주입 전에 기준선을 먼저 찍는다**"
echo "        비교 대상이 없으면 '원래 그랬던 것'과 구분이 안 된다(07-28의 규칙)."

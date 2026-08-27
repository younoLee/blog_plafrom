#!/usr/bin/env bash
# 훈련용 계정 두 개를 만들고 토큰을 받아 `.tokens.<레인>` 에 적는다.
#
# 왜 파일로 남기나 (2026-08-27) —
#   08-26 회차는 "SKIP 0건"으로 끝났는데, **토큰을 손으로 만들었다.** 그래서 그 '0건'을
#   다시 만들 수단이 저장소에 없었다. 프로브의 절반(글 작성·AI 초안·결제·초대)이 토큰에
#   달려 있으므로, 토큰 만드는 법이 없으면 훈련의 절반이 재현 불가다.
#   이 폴더가 생긴 이유("결과는 남았는데 방법이 안 남았다")와 정확히 같은 병이다.
#
# 왜 계정이 둘인가 — 한 계정으로는 프로브 열 개를 다 못 밟는다.
#   · `/api/admin/invites` 는 admin 이 필요하다.
#   · `/api/payments/checkout` 은 **admin 을 400 으로 거부한다**
#     (payments.py:58 "관리자는 결제할 필요가 없어"). 돈 경로는 writer 로만 밟힌다.
#   한쪽만 만들면 둘 중 하나가 조용히 SKIP 되거나, 더 나쁘게는 주입과 무관한 400/403 을
#   '주입 결과'로 읽게 된다.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lane.sh"

TOKF="$CHAOS_HERE/.tokens.$CHAOS_LANE"
WRITER_EMAIL="chaos-writer@example.com"
ADMIN_EMAIL="chaos-admin@example.com"
# 훈련 스택 전용. 이 값은 격리 스택 밖으로 나가지 않는다(포트가 다르고 볼륨도 다르다).
PW="chaos-drill-pw-0827"

mk() {  # $1=이메일 $2=역할
  chaos_dc exec -T backend python scripts/create_user.py "$1" \
    --role "$2" --password "$PW" --update-if-exists --display-name "chaos-$2" >/dev/null 2>&1 \
  || chaos_dc exec -T backend python scripts/create_user.py "$1" \
    --role "$2" --password "$PW" --display-name "chaos-$2" >/dev/null
}

login() {  # $1=이메일 → 토큰을 stdout 으로
  curl -s -X POST "$CHAOS_BASE/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"email\":\"$1\",\"password\":\"$PW\"}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin).get("access_token",""))' 2>/dev/null
}

echo "  계정 생성 (레인 $CHAOS_LANE)"
mk "$WRITER_EMAIL" writer
mk "$ADMIN_EMAIL"  admin

WT="$(login "$WRITER_EMAIL")"
AT="$(login "$ADMIN_EMAIL")"

# **빈 토큰을 조용히 넘기지 않는다.** 빈 채로 프로브를 돌리면 인증 프로브가 전부 SKIP 이
# 되고, SKIP 은 표에서 한 줄씩 조용히 지나간다 — "잰 것이 아니다"라고 적혀 있어도
# 열 줄 중 넉 줄이 그러면 사람은 그걸 통과로 읽는다.
if [ -z "$WT" ] || [ -z "$AT" ]; then
  echo "! 토큰을 못 받았다 (writer=${#WT}자 admin=${#AT}자). 스택이 떴는지, 로그인 캡에 걸렸는지 확인." >&2
  exit 1
fi

umask 077
cat > "$TOKF" <<EOF
export CHAOS_TOKEN='$WT'
export CHAOS_ADMIN_TOKEN='$AT'
export CHAOS_WRITER_EMAIL='$WRITER_EMAIL'
export CHAOS_ADMIN_EMAIL='$ADMIN_EMAIL'
EOF
echo "  토큰 기록: $TOKF   (writer ${#WT}자 · admin ${#AT}자)"
echo "  쓰는 법:  . $TOKF && CHAOS_LANE=$CHAOS_LANE ops/chaos/probe.sh"

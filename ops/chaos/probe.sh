#!/usr/bin/env bash
# 프로브 — 사용자가 실제로 밟는 경로를 훑어 **상태코드·Content-Type·소요시간**을 찍는다.
#
# 07-28은 7개였다(헬스·상태·글목록·내정보·글작성·AI초안·로그인). 그 뒤 늘어난 셋을 더한다:
#   발행→푸시 · 결제 confirm · 초대 발급
#
# 세 가지를 함께 보는 이유 —
#   · **상태코드**: 500과 503은 다르다. 프론트(api/http.ts의 isAsleepStatus)는 502/503/504만
#     '일시적 장애'로 안내한다. 500은 그 경로를 안 타서 사용자는 그냥 빨간 에러를 본다.
#   · **Content-Type**: text/plain이면 프론트의 res.json()이 파싱조차 못 한다.
#     07-28이 DB 정지에서 잡은 것이 정확히 이 조합이었다(500 + text/plain).
#   · **소요시간**: '거부'와 '무응답'을 가르는 유일한 신호다. 07-28 실측으로
#     연결 거부 0.5초 vs 무응답 115초였다. 코드가 같아도 사고의 무게가 다르다.
#
# 인증이 필요한 프로브는 토큰이 있으면 돌고 없으면 SKIP으로 남긴다.
# **SKIP은 통과가 아니다.** 안 잰 것을 잰 것처럼 보이게 하지 않으려고 따로 표시한다.
set -uo pipefail   # -e 없음: 프로브 하나가 실패해도 나머지를 계속 재야 한다
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
BASE="${CHAOS_BASE:-http://localhost:18000}"
TOKEN="${CHAOS_TOKEN:-}"

hdr=(-H 'Content-Type: application/json')
[ -n "$TOKEN" ] && hdr+=(-H "Authorization: Bearer $TOKEN")

probe() {  # $1=이름 $2=메서드 $3=경로 $4=본문(선택) $5=auth필요?
  local name=$1 method=$2 path=$3 body=${4:-} needs_auth=${5:-no}
  if [ "$needs_auth" = "yes" ] && [ -z "$TOKEN" ]; then
    printf '  %-22s SKIP   (CHAOS_TOKEN 없음 — 잰 것이 아니다)\n' "$name"
    return
  fi
  local args=(-s -o /tmp/chaos_body -w '%{http_code} %{content_type} %{time_total}'
              --max-time "${CHAOS_TIMEOUT:-130}" -X "$method" "${hdr[@]}" "$BASE$path")
  [ -n "$body" ] && args+=(-d "$body")
  local out; out=$(curl "${args[@]}" 2>/dev/null) || out="000 - timeout"
  local code ctype t; read -r code ctype t <<<"$out"
  local flag=""
  case "$code" in
    500) flag=" ← 500은 '이 요청이 잘못됐다'로 읽힌다. 상황은 '지금 못 한다'다" ;;
    000) flag=" ← 응답 없음(타임아웃). '거부'가 아니라 '무응답'이다" ;;
  esac
  case "$ctype" in
    text/plain*) flag="$flag ← text/plain: 프론트가 res.json()으로 파싱 못 한다" ;;
  esac
  printf '  %-22s %-4s %-26s %6.2fs%s\n' "$name" "$code" "${ctype%%;*}" "$t" "$flag"
}

echo "대상 $BASE  ($(date '+%H:%M:%S'))"
echo "── 07-28의 7개 ──"
probe "헬스체크"       GET  /api/health
probe "서비스 상태"     GET  /api/status
probe "글 목록(비로그인)" GET  /api/posts
probe "내 정보"        GET  /api/auth/me             ""  yes
probe "글 작성"        POST /api/posts '{"title":"chaos","content":"chaos probe"}' yes
probe "AI 초안"        POST /api/ai/draft '{"memo":"chaos probe"}' yes
probe "로그인"         POST /api/auth/login '{"email":"nobody-chaos@example.com","password":"x0123456789"}'

echo "── 07-28 이후 늘어난 셋 ──"
# 푸시: 공개키 조회는 무인증이라 항상 잰다. 503이면 VAPID 미설정 — 주입 결과가 아니다.
probe "푸시 공개키"     GET  /api/push/key
probe "결제 confirm"    POST /api/payments/confirm '{"paymentKey":"chaos","orderId":"chaos","amount":1}' yes
probe "초대 발급"       POST /api/admin/invites '{}' yes

echo
echo "── 주입이 실제로 닿았는가 (blackhole 기록) ──"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
(cd "$ROOT" && docker compose -f docker-compose.yml -f ops/chaos/docker-compose.chaos.yml \
   exec -T blackhole sh -c 'tail -5 /state/hits.log 2>/dev/null || echo "  (기록 없음 — 주입이 안 닿았거나 아직 안 했다)"') 2>/dev/null \
  || echo "  (blackhole 미기동)"

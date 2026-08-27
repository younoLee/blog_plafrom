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
# 토큰은 손으로 만들지 말고 `ops/chaos/token.sh` 로 받는다 — 08-26 회차는 이게 수동이라
# "SKIP 0건"이라는 결과를 **재현할 수단이 없었다.**
set -uo pipefail   # -e 없음: 프로브 하나가 실패해도 나머지를 계속 재야 한다
# 레인 설정은 lane.sh 하나에 있다 — 복붙본이 넷이라 갈라졌던 자리다(lane.sh 주석 참고).
. "$(dirname "${BASH_SOURCE[0]}")/lane.sh"
BASE="${CHAOS_BASE:-http://localhost:18000}"
TOKEN="${CHAOS_TOKEN:-}"
# 이름표 — 한 레인에서 주입을 여러 번 하므로, 어느 주입의 측정인지 출력에 박아둔다.
LABEL="${CHAOS_LABEL:-baseline}"
# 기계 판독용. 비어 있으면 안 쓴다. 사람이 읽는 표는 그대로 둔다 —
# 표를 JSON으로 바꾸면 훈련 중에 사람이 못 읽는다.
OUT="${CHAOS_OUT:-}"

ADMIN_TOKEN="${CHAOS_ADMIN_TOKEN:-}"

# 프로브마다 어느 계정으로 밟을지가 다르다 — 한 계정으로는 열 개를 다 못 밟는다.
# `/admin/invites` 는 admin 이 필요하고, `/payments/checkout` 은 admin 을 400 으로
# 거부한다(payments.py:58). token.sh 가 둘 다 만든다.
auth_hdr() {  # $1=writer|admin|none
  case "$1" in
    admin) [ -n "$ADMIN_TOKEN" ] && printf '%s' "Authorization: Bearer $ADMIN_TOKEN" ;;
    writer) [ -n "$TOKEN" ] && printf '%s' "Authorization: Bearer $TOKEN" ;;
  esac
}
have_token() { case "$1" in admin) [ -n "$ADMIN_TOKEN" ] ;; writer) [ -n "$TOKEN" ] ;; *) true ;; esac; }

json_row() {  # OUT 이 설정됐을 때만
  [ -z "$OUT" ] && return
  python3 -c '
import json,sys
print(json.dumps(dict(zip(["lane","label","probe","code","ctype","secs"], sys.argv[1:])), ensure_ascii=False))
' "$CHAOS_LANE" "$LABEL" "$1" "$2" "$3" "$4" >> "$OUT"
}

probe() {  # $1=이름 $2=메서드 $3=경로 $4=본문(선택) $5=계정(no|yes=writer|admin)
  local name=$1 method=$2 path=$3 body=${4:-} who=${5:-no}
  [ "$who" = "yes" ] && who=writer
  if [ "$who" != "no" ] && ! have_token "$who"; then
    printf '  %-22s SKIP   (%s 토큰 없음 — 잰 것이 아니다. ops/chaos/token.sh)\n' "$name" "$who"
    json_row "$name" SKIP - -
    return
  fi
  local args=(-s -o /tmp/chaos_body -w '%{http_code} %{content_type} %{time_total}'
              --max-time "${CHAOS_TIMEOUT:-130}" -H 'Content-Type: application/json')
  local a; a="$(auth_hdr "$who")"
  [ -n "$a" ] && args+=(-H "$a")
  # AI 초안은 slowapi IP 캡(10/hour)에 먼저 걸린다. 캡의 키는 client_ip() 이고
  # 그건 X-Forwarded-For 를 신뢰 홉 수만큼 뒤에서 읽는다(core/ratelimit.py).
  # 훈련은 한 호스트에서 도므로 모든 프로브가 같은 키를 쓰고, 08-26 레인3은 그래서
  # 8회 만에 말라 anthropic refuse · gemini/cohere 의 error·gone 을 통째로 못 쟀다.
  # **캡을 코드에서 없애지 않는다** — 운영 방어를 훈련 편의로 낮추면 그 방어는 다시는
  # 안 밟힌다. 대신 프로브마다 다른 키를 준다. 계정 기준 캡(ai_hourly_cap)은 그대로
  # 살아 있고, 그쪽은 훈련 스택 환경변수로만 올린다.
  [ -n "${CHAOS_XFF:-}" ] && args+=(-H "X-Forwarded-For: $CHAOS_XFF")
  args+=(-X "$method" "$BASE$path")
  [ -n "$body" ] && args+=(-d "$body")
  # **세 번째 필드는 반드시 숫자여야 한다.** 예전엔 실패 시 "000 - timeout" 을 넣었는데,
  # 아래 printf 가 '%6.2f' 로 읽으려다 `printf: timeout: invalid number` 를 stderr 로
  # 뱉고 표에는 **0.00s** 를 찍었다. 이 훈련이 존재하는 이유가 "거부(0.5초)와
  # 무응답(115초)은 다른 사고"인데, 하네스가 무응답을 **가장 빠른 응답으로 인쇄**하고
  # 있었다. 08-27 회차의 db hang 6줄이 전부 그 모양이었다(JSONL 에도 secs:"timeout").
  # 상한값을 그대로 넣는다 — "적어도 이만큼은 붙들렸다"가 참인 유일한 숫자다.
  local cap="${CHAOS_TIMEOUT:-130}"
  local out; out=$(curl "${args[@]}" 2>/dev/null) || out="000 (무응답) $cap"
  local code ctype t; read -r code ctype t <<<"$out"
  local flag=""
  case "$code" in
    500) flag=" ← 500은 '이 요청이 잘못됐다'로 읽힌다. 상황은 '지금 못 한다'다" ;;
    000) flag=" ← 응답 없음. 시간은 '상한까지 붙들렸다'는 뜻이지 실제 상한이 아니다" ;;
    429) flag=" ← 캡에 걸렸다. 주입 결과가 아니다 — 잰 것이 아니라고 읽어라" ;;
  esac
  case "$ctype" in
    text/plain*) flag="$flag ← text/plain: 프론트가 res.json()으로 파싱 못 한다" ;;
  esac
  printf '  %-22s %-4s %-26s %6.2fs%s\n' "$name" "$code" "${ctype%%;*}" "$t" "$flag"
  json_row "$name" "$code" "${ctype%%;*}" "$t"
}

echo "대상 $BASE  레인 $CHAOS_LANE  [$LABEL]  ($(date '+%H:%M:%S'))"
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
# ⚠️ 본문은 **snake_case** 다. 08-26 회차는 camelCase(`paymentKey`/`orderId`)로 적혀 있어
# ConfirmRequest(routers/payments.py:45-48) 와 안 맞았고, 그래서 이 프로브는 **항상 422로
# 끝나 결제 로직에 아예 닿지 않았다.** 그대로 읽으면 "결제는 주입에도 멀쩡했다"는 거짓말이
# 된다. 하네스가 거짓말할 뻔한 자리 셋 중 첫째.
# ── 결제: **진짜 주문을 먼저 만든다.** ──────────────────────────────────────────
# 08-26 회차는 본문이 camelCase 라 422 로 끝났다. 그런데 snake_case 로 고쳐도 부족하다 —
# confirm 은 `order_id` 로 DB 를 먼저 뒤지고 **없으면 404 로 끝낸다**(payments.py:97-99).
# 즉 `order_id:"chaos"` 는 토스를 부르기도 전에 돌아온다. 주입이 토스에 걸려 있어도
# 이 프로브는 영원히 주입을 안 밟고, 그걸 "결제는 멀쩡했다"로 읽으면 두 번째 거짓말이 된다.
#
# 그래서 checkout 으로 pending 주문을 하나 만들고 그 order_id 로 confirm 을 친다.
# 금액도 서버가 만든 값을 그대로 쓴다(안 맞으면 400 에서 끝난다 — 또 다른 조기 반환).
# checkout 은 writer 여야 한다(admin 은 400). 캡이 20/hour 라 한 레인에서 20회까지.
# **Pro 상태를 먼저 되돌린다.** confirm 이 한 번 성공하면(blackhole pass 모드가 200을
# 주므로 baseline 에서 반드시 일어난다) writer 가 Pro 가 되고, 그때부터 checkout 은
# 400("이미 Pro 구독 중")으로 끝난다 — 그러면 이후 **모든** 회차의 결제 프로브가 조용히
# SKIP 된다. 첫 측정만 진짜이고 나머지는 빈칸인데 표에서는 똑같아 보인다.
# 훈련은 매번 같은 출발점에서 시작해야 한다. 훈련 스택 전용 DB 라 이 초기화는 안전하다.
if [ -n "${CHAOS_WRITER_EMAIL:-}" ]; then
  printf '%s\n' "update users set is_pro=false, pro_until=null
     where lower(email)=lower('$CHAOS_WRITER_EMAIL');
   delete from payments
     where user_id in (select id from users where lower(email)=lower('$CHAOS_WRITER_EMAIL'));" | (
    cd "$CHAOS_ROOT" || exit 1
    # **-p 를 반드시 명시한다.** 없으면 compose 가 디렉터리명(blog_plafrom)으로 떨어져
    # **개발 스택 DB** 를 친다. 스크립트 안에서는 lane.sh 가 COMPOSE_PROJECT_NAME 을
    # export 하므로 실제로는 안전하지만, 08-27 훈련에서 에이전트 둘이 이 줄을 **떼어내
    # 손으로 실행했고** 그때는 그 export 가 없다. 이 줄은 읽기가 아니라 `update`+`delete`다.
    timeout 12 docker compose -p "$COMPOSE_PROJECT_NAME" \
      -f docker-compose.yml -f ops/chaos/docker-compose.chaos.yml \
      exec -T db psql -U postgres -d blog -q
  ) >/dev/null 2>&1 || true
fi

ORDER_JSON=""
if have_token writer; then
  ORDER_JSON=$(curl -s --max-time 20 -X POST "$BASE/api/payments/checkout" \
    -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" 2>/dev/null)
fi
ORDER_ID=$(printf '%s' "$ORDER_JSON" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("order_id",""))
except Exception: print("")' 2>/dev/null)
ORDER_AMT=$(printf '%s' "$ORDER_JSON" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("amount",""))
except Exception: print("")' 2>/dev/null)

if [ -n "$ORDER_ID" ]; then
  probe "결제 confirm"    POST /api/payments/confirm \
    "{\"payment_key\":\"chaos-pk\",\"order_id\":\"$ORDER_ID\",\"amount\":$ORDER_AMT}" writer
else
  # 주문을 못 만들면 confirm 은 재도 의미가 없다. **그 사실을 적는다.**
  printf '  %-22s SKIP   (checkout 실패 — 주문 없이 confirm 은 404 로 끝나 주입에 안 닿는다)\n' "결제 confirm"
  printf '           checkout 응답: %s\n' "${ORDER_JSON:0:120}"
  json_row "결제 confirm" SKIP - -
fi

# 초대는 **매번 다른 주소**여야 한다. `{}` 는 email 이 필수라 422 로 끝나고(08-27 기준선에서
# 실측), 같은 주소를 반복하면 "살아 있는 초대가 이미 있다"로 400 이 된다(admin.py:302).
# 둘 다 주입에 닿기 전에 돌아오는 조기 반환이라, 표에서는 '실패'로 보이지만 잰 것은 없다.
INV_EMAIL="chaos-invite-$$-${RANDOM}@example.com"
probe "초대 발급"       POST /api/admin/invites \
  "{\"email\":\"$INV_EMAIL\",\"role\":\"pending\",\"expires_days\":7}" admin

echo
echo "── 커넥션 풀 (08-26 레인2의 최대 발견이 프로브 10개 어디에도 안 드러났다) ──"
# 왜 이게 필요한가 — 08-26에 푸시 hang 이 커넥션 4개를 24초씩 `idle in transaction` 으로
# 묶는 것을 잡았는데, **그건 프로브가 아니라 손으로 psql 을 쳐서 본 것**이었다.
# 응답만 보는 프로브는 응답 경로 **밖**의 사고를 구조적으로 못 본다(그 회차의 결론).
# 발행 응답은 먼저 나가고 발송은 뒤에서 도니까, 사용자 화면은 멀쩡하고 사고는 안쪽에 쌓인다.
#
# timeout 을 씌우는 이유: db hang(=pause) 중에는 psql 자신이 영원히 안 돌아온다.
# 재는 도구가 측정 대상과 같이 얼면 훈련이 그 자리에서 멈춘다.
POOL_SQL="select coalesce(state, 'unknown'), count(*),
       coalesce(round(max(extract(epoch from now() - state_change))::numeric, 1), 0)
from pg_stat_activity
where datname = 'blog' and pid <> pg_backend_pid()
group by 1 order by 2 desc;"

pool_snapshot() {
  # timeout 은 셸 함수를 못 받는다(외부 명령만). chaos_dc 를 못 쓰고 여기서만 펼친다.
  printf '%s\n' "$POOL_SQL" | (
    cd "$CHAOS_ROOT" || exit 1
    # -p 명시 이유는 위 결제 초기화 블록의 주석과 같다(복붙하면 개발 스택을 친다).
    timeout 12 docker compose -p "$COMPOSE_PROJECT_NAME" \
      -f docker-compose.yml -f ops/chaos/docker-compose.chaos.yml \
      exec -T db psql -U postgres -d blog -tA -F'|'
  ) 2>/dev/null
}
snap="$(pool_snapshot)"
if [ -z "$snap" ]; then
  # 08-27 훈련 지적: 이 문장이 hang 케이스에서 틀렸다. pause 된 컨테이너에는
  # `docker exec` 가 1초 미만에 **거부**된다 — '기다리다 못 쟀다'와 '재는 도구가 아예
  # 못 들어갔다'는 다른 사건인데 한 문장이 둘을 덮고 있었다.
  echo "  (못 쟀다 — 정지=exec 거부 / 동결=exec 즉시 거부 / 살아있음=psql 12초 초과."
  echo "   셋은 다른 사건이다. 위 [컨테이너] 줄의 state 로 갈라 읽어라. 통과가 아니다)"
  json_row "커넥션풀" UNREAD - -
else
  echo "$snap" | while IFS='|' read -r state n age; do
    f=""
    [ "$state" = "idle in transaction" ] && f=" ← 트랜잭션을 연 채 붙들고 있다. 풀 정원은 20이다"
    printf '  %-24s %3s개  최장 %6ss%s\n' "$state" "$n" "$age" "$f"
  done
  iit=$(echo "$snap" | awk -F'|' '$1=="idle in transaction"{print $2}')
  json_row "커넥션풀_idle_in_tx" "${iit:-0}" - "$(echo "$snap" | awk -F'|' '$1=="idle in transaction"{print $3}')"
fi

echo
echo "── 주입이 실제로 닿았는가 ──"
# 08-26 회차의 이 자리는 blackhole 기록만 봤다. 그래서 `db stop`·`smtp stop` 처럼
# blackhole 을 안 거치는 주입에서는 **항상 "기록 없음"** 이 찍혔고, 규칙 5("기록 0이면
# 안 닿은 것")를 글자 그대로 따랐으면 레인1이 통째로 거짓 보고가 됐다.
# 주입 경로가 둘이면 도달 확인도 둘이어야 한다.
echo "  [컨테이너]"
chaos_dc ps --format '    {{.Service}}\t{{.State}}' 2>/dev/null | grep -E 'db|mailpit|backend|blackhole' \
  || echo "    (스택 조회 실패)"
echo "  [blackhole 기록]"
chaos_dc exec -T blackhole sh -c 'echo "    모드=$(cat /state/mode 2>/dev/null || echo ?)"; tail -5 /state/hits.log 2>/dev/null | sed "s/^/    /" || echo "    (기록 없음 — 이 주입이 blackhole 을 안 거치는 것일 수도 있다. 위 컨테이너 상태를 함께 보라)"' 2>/dev/null \
  || echo "    (blackhole 미기동)"

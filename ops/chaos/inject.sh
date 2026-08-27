#!/usr/bin/env bash
# 주입: <대상> <모드>
#
#   대상  db smtp s3 anthropic push toss openai gemini cohere none
#   모드  refuse hang error gone notfound slow pass
#         notfound(404)·slow(N초 뒤 응답)는 2026-08-27 추가. blackhole.py 머리주석 참고 —
#         404는 push.py:169의 '410과 같게 본 경계'를 밟는 유일한 길이고, slow는 재시도가
#         상한 직전에 한 바퀴 더 도는 모양을 만든다.
#
# db·smtp 는 우리 컨테이너라 도커로 직접 죽인다.
# 나머지는 목적지가 바깥이라 blackhole 이 대신 받는다 — 모드 파일 한 줄로 바뀐다.
#
# **주입이 실제로 닿았는지 반드시 확인한다.** 안 닿았는데 앱이 멀쩡한 것을
# '견뎠다'로 읽으면 훈련이 거짓말을 한다. blackhole 은 /state/hits.log 에 기록한다.
#
# ── db 의 두 모드 (2026-08-27 추가) ────────────────────────────────────────────
# 08-26 훈련이 남긴 **가장 큰 빈칸**이 `db hang` 이었다. 그때는 `stop` 하나뿐이라
# 잰 것이 전부 '거부'(3.8초)였고, 07-28이 Anthropic 에서 배운 "거부와 무응답은 다른
# 사고"(0.5초 vs 115초)를 정작 DB 에는 한 번도 적용해보지 못했다.
#
#   refuse = docker stop   — 컨테이너가 사라져 커널이 RST. connect() 가 즉시 실패한다.
#   hang   = docker pause  — 프로세스만 얼린다. **리스닝 소켓은 커널에 그대로 살아 있어
#            TCP 핸드셰이크는 성공하고, 그 뒤 startup 패킷에 아무도 답하지 않는다.**
#            이게 "연결은 받고 대답을 안 한다"의 정확한 재현이고, RDS 가 페일오버
#            중이거나 호스트가 스왑에 빠졌을 때 실제로 보이는 모양이다.
#
# 왜 이 구분이 중요한가 — `core/database.py` 에 connect_timeout 이 **없다**.
# refuse 는 커널이 즉시 끊어주니 상한이 저절로 생기지만, hang 은 끊어줄 사람이 없다.
# 상한이 없으면 얼마나 붙들리는지 아무도 모른다. 그 값을 재는 것이 이 모드의 목적이다.
set -euo pipefail
# 레인 설정은 lane.sh 하나에 있다 — 복붙본이 넷이라 갈라졌던 자리다(lane.sh 주석 참고).
. "$(dirname "${BASH_SOURCE[0]}")/lane.sh"

TARGET="${1:-}"; MODE="${2:-refuse}"

# 컨테이너를 얼리거나 죽이는 대상(db·mailpit)에서 모드를 해석한다.
# pause 된 컨테이너는 stop 이 안 먹으므로(도커가 거부한다) 무슨 모드로 가든
# **항상 unpause 를 먼저** 통과시킨다. 상태를 모르는 채로 전이하면 조용히 실패한다.
freeze_or_kill() {  # $1=서비스명 $2=모드 $3=07-28 대응표기
  local svc=$1 mode=$2 note=$3
  chaos_dc unpause "$svc" >/dev/null 2>&1 || true
  case "$mode" in
    refuse)
      chaos_dc start "$svc" >/dev/null 2>&1 || true
      chaos_dc stop "$svc" >/dev/null
      echo "  $svc 정지(refuse — 연결 거부) $note"
      ;;
    hang)
      # start 를 먼저 태운다. stop 된 상태에서 pause 하면 도커가 거부하고,
      # 그 실패를 무시하면 "주입했다"고 적힌 채 아무 일도 안 일어난다.
      chaos_dc start "$svc" >/dev/null 2>&1 || true
      chaos_dc pause "$svc" >/dev/null
      echo "  $svc 동결(hang — 연결은 받고 무응답)"
      echo "  ⚠️ 얼린 것은 프로세스뿐이다. 리스닝 소켓이 살아 있어 connect() 는 성공한다."
      ;;
    pass)
      chaos_dc start "$svc" >/dev/null 2>&1 || true
      echo "  $svc 정상"
      ;;
    *) echo "$svc 에 쓸 수 없는 모드: $mode (refuse|hang|pass)" >&2; exit 2 ;;
  esac
}

case "$TARGET" in
  none)
    # 원상 복구도 unpause 가 먼저다. 08-26 판에는 pause 가 없어 이 줄이 필요 없었다.
    chaos_dc unpause db mailpit >/dev/null 2>&1 || true
    chaos_dc start   db mailpit >/dev/null 2>&1 || true
    chaos_dc exec -T blackhole sh -c 'echo pass > /state/mode'
    echo "  원상 복구 — 모든 의존이 정상"
    ;;
  db)   freeze_or_kill db      "$MODE" "(07-28 ①과 동일)" ;;
  smtp) freeze_or_kill mailpit "$MODE" "(07-28 ②와 동일)" ;;
  s3|anthropic|push|toss|openai|gemini|cohere)
    case "$MODE" in refuse|hang|error|gone|notfound|slow|pass) ;; *) echo "모드가 잘못됐다: $MODE" >&2; exit 2 ;; esac
    chaos_dc exec -T blackhole sh -c "echo $MODE > /state/mode"
    echo "  $TARGET → $MODE"
    echo "  ⚠️ blackhole 은 대상별이 아니라 **전역** 모드다. 한 번에 하나씩 재라."
    [ "$TARGET" = "s3" ] && echo "  ※ S3 는 CHAOS_S3_BUCKET 이 설정된 스택에서만 닿는다(up.sh 가 넣는다)."
    ;;
  *) echo "사용: inject.sh <db|smtp|s3|anthropic|push|toss|openai|gemini|cohere|none> [모드]" >&2; exit 2 ;;
esac

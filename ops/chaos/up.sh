#!/usr/bin/env bash
# 격리 스택 기동. 개발 스택(8000·5432·1025)은 건드리지 않는다.
set -euo pipefail
# 레인 설정은 lane.sh 하나에 있다 — 복붙본이 넷이라 갈라졌던 자리다(lane.sh 주석 참고).
. "$(dirname "${BASH_SOURCE[0]}")/lane.sh"
HERE="$CHAOS_HERE"   # lane.sh 가 이미 풀어놨다
"$HERE/make_ca.sh"

# 훈련용 VAPID 키쌍. 없으면 push_enabled가 False라 푸시 주입이 아무것도 안 잰다.
# 운영 키를 쓰지 않는다 — 훈련 스택이 실제 기기로 발송할 이유가 없다.
# 훈련용 가짜 키 묶음. 없으면 그 기능이 **주입에 닿기도 전에** 꺼진 채로 끝난다.
#   · VAPID 없음 → push_enabled 가 False(두 키의 AND) → 푸시 주입이 아무것도 안 잰다
#   · ANTHROPIC_API_KEY 없음 → AI 초안이 **벤더를 부르기도 전에** 503(키 없음)
#   · LLM_ENCRYPTION_KEY 없음 → BYOK(openai·gemini·cohere) 경로가 통째로 막힌다
# 08-26 회차는 뒤의 둘이 빠져 있어서 레인3이 컨테이너 환경변수로 손수 주입해 재생성한
# 뒤에야 잴 수 있었다. 그 수동 절차가 이번엔 여기 들어온다.
#
# **재생성이 아니라 보충이다.** `if [ ! -f ]` 로 통째 건너뛰면 지난 회차에 만들어진
# 파일에는 새 키가 영원히 안 들어온다 — 08-26에 만든 .env.chaos 가 정확히 그 상태다.
ENVF="$HERE/.env.chaos"
touch "$ENVF"; chmod 600 "$ENVF"

add_key() {  # $1=키이름 $2=값 (이미 있으면 손대지 않는다)
  grep -q "^$1=" "$ENVF" && return 0
  printf '%s=%s\n' "$1" "$2" >> "$ENVF"
  echo "  훈련용 키 보충: $1"
}

if ! grep -q '^CHAOS_VAPID_PUBLIC=' "$ENVF"; then
  read -r _vp _vs <<<"$(python3 "$HERE/genkeys.py" vapid)"
  printf 'CHAOS_VAPID_PUBLIC=%s\nCHAOS_VAPID_PRIVATE=%s\n' "$_vp" "$_vs" >> "$ENVF"
  echo "  훈련용 VAPID 키쌍 생성"
fi
# 진짜 키가 아니다. blackhole 이 받으므로 값이 유효할 필요가 없다 — 필요한 건
# "설정돼 있다"뿐이고, 그래야 주입이 벤더 호출 자리까지 **도달한다**.
add_key CHAOS_ANTHROPIC_KEY "sk-ant-chaos-not-a-real-key"
# 이쪽은 형식이 맞아야 한다. Fernet 은 로드 시점에 32바이트 base64 를 검증하므로
# 아무 문자열이나 넣으면 BYOK 경로가 주입이 아니라 **설정 오류로** 죽는다.
add_key CHAOS_LLM_ENC_KEY "$(python3 "$HERE/genkeys.py" fernet)"
# S3 는 08-26에 아예 못 쟀다 — 버킷이 비어 있으면(`settings.s3_bucket`) 업로드가
# 로컬 디스크로 가서 **주입 대상 코드에 들어가지도 않는다**(uploads.py:126).
# 버킷 이름을 정해야 extra_hosts 로 가로챌 주소가 결정된다(가상호스팅 방식).
# 실재하지 않는 버킷이고, DNS 를 blackhole 로 돌리므로 AWS 로 나가지 않는다.
add_key CHAOS_S3_BUCKET "chaosbucket"
# 경로가 실행 시점에 정해져(레인·저장소 위치) shellcheck 가 따라갈 수 없다.
# 이 파일은 훈련용 가짜 키만 담고 git 에 안 올라간다(.gitignore).
# ⚠️ 지시자 줄에는 설명을 붙이지 마라(SC1125). 그리고 `set -a; . x; set +a` 처럼
#    한 줄에 붙여 쓰면 지시자가 source 에 안 붙는다 — 줄을 나눠야 먹는다.
set -a
# shellcheck source=/dev/null
. "$ENVF"
set +a

chaos_dc up -d
echo
# ⚠️ 하드코딩 금지. 2026-08-26 훈련에서 이 세 줄이 레인과 무관하게 18000·18025·15173을
# 찍고 있었다. 포트 계산(:8-12)은 맞는데 **안내문만 틀려서**, 안내를 믿고 프로브를 돌리면
# 남의 레인 스택을 재게 된다. 하네스가 거짓말할 뻔한 자리 셋 중 하나였다.
echo "  레인     $CHAOS_LANE  (프로젝트 $COMPOSE_PROJECT_NAME)"
echo "  백엔드   http://localhost:$CHAOS_PORT_API"
echo "  메일 UI  http://localhost:$CHAOS_PORT_MAILUI"
echo "  프론트   http://localhost:$CHAOS_PORT_WEB"
echo "  DB       localhost:$CHAOS_PORT_DB"
echo
echo "  이 레인에서 뭘 하든 앞에 붙인다:  CHAOS_LANE=$CHAOS_LANE ops/chaos/<스크립트>"
echo
echo "  다음: ops/chaos/probe.sh  ← **주입 전에 기준선을 먼저 찍는다**"
echo "        비교 대상이 없으면 '원래 그랬던 것'과 구분이 안 된다(07-28의 규칙)."

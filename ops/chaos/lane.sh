#!/usr/bin/env bash
# 레인 설정 — up/down/inject/probe 가 **전부** 이 파일 하나를 읽는다.
#
# 왜 파일로 뺐나 (2026-08-27):
#   이 블록이 네 스크립트에 복붙돼 있었다. 계산은 네 곳 다 맞았는데 up.sh의 **안내문만**
#   18000·18025·15173으로 하드코딩돼 있어서, 안내를 믿고 프로브를 돌리면 남의 레인을
#   재게 됐다(08-26 훈련 '하네스가 거짓말할 뻔한 자리' #2).
#   복붙은 처음엔 같고 나중에 갈라진다. 갈라진 걸 아무도 안 보는 게 하네스의 기본 사고다.
#
# 여러 훈련을 동시에 돌리려면 스택이 서로 격리돼야 한다 — blackhole 모드가 **전역**이라
# 한 스택을 공유하면 주입이 서로를 오염시킨다. 레인마다 포트·서브넷·프로젝트가 다르다.
# CHAOS_LANE 을 안 주면 0 으로 떨어진다. 편의는 유지하되 **조용하지는 않게** 한다 —
# 08-27 훈련에서 레인3 담당이 앞에 CHAOS_LANE 을 안 붙인 명령을 몇 번 실행했고,
# 그게 전부 레인0(18000)으로 갔다. 레인0 스택이 떠 있었으면 200 이 돌아와
# **그럴듯해 보였을** 자리다. lane.sh 의 기존 검사는 개발 포트·프로젝트명만 막지
# '엉뚱한 레인'은 안 막는다. 막을 수 없으면 최소한 화면에 적는다.
if [ -z "${CHAOS_LANE:-}" ]; then
  CHAOS_LANE=0
  echo "  ⚠️ CHAOS_LANE 미지정 → 레인 0(포트 18000)을 쓴다. 의도한 레인이 맞나?" >&2
fi
export CHAOS_LANE
export COMPOSE_PROJECT_NAME="chaos${CHAOS_LANE}"
export CHAOS_PORT_API=$((18000 + CHAOS_LANE * 100))
export CHAOS_PORT_DB=$((15432 + CHAOS_LANE * 100))
export CHAOS_PORT_SMTP=$((11025 + CHAOS_LANE * 100))
export CHAOS_PORT_MAILUI=$((18025 + CHAOS_LANE * 100))
export CHAOS_PORT_WEB=$((15173 + CHAOS_LANE * 100))
# ⚠️ **사설 대역 안에 있어야 한다.** 예전엔 172.$((30+LANE)) 이었는데 RFC1918 의
# 172.16/12 는 **172.31 에서 끝난다** — 레인 2 이상이 172.32·172.33 … 즉 공인 대역을
#받고 있었다. 08-27 훈련에서 그게 실제로 결과를 뒤집었다: BYOK 의 base_url SSRF 가드가
# `ip.is_global` 하나로 판단하는데, 레인3(172.33)에서는 훈련 스택의 내부 주소가
# **공인으로 판정돼 통과**했다. 하마터면 하네스 산물이 medium 짜리 앱 결함으로
# 보고될 뻔했다. 같은 코드를 레인0·1 에서 밟은 사람은 '차단됨'을 본다.
# 10.0.0.0/8 은 통째로 사설이라 레인 번호가 몇이든 이 사고가 안 난다.
export CHAOS_SUBNET="10.$((200 + CHAOS_LANE)).0"
export CHAOS_BASE="http://localhost:$CHAOS_PORT_API"

CHAOS_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHAOS_ROOT="$(cd "$CHAOS_HERE/../.." && pwd)"
export CHAOS_HERE CHAOS_ROOT

# 개발 스택 보호. 레인 계산이 어떤 이유로든 어긋나 8000·5432·1025를 집으면 남의(=내)
# 작업 환경을 죽인다. 07-28의 규칙 "훈련이 남의 작업 환경을 죽이면 안 된다"를 주석이
# 아니라 **검사**로 만든다 — 주석은 어긋나도 아무 일이 안 일어난다.
if [ "$CHAOS_PORT_API" = "8000" ] || [ "$CHAOS_PORT_DB" = "5432" ] || [ "$CHAOS_PORT_SMTP" = "1025" ]; then
  echo "레인 계산이 개발 스택 포트를 집었다 (CHAOS_LANE=$CHAOS_LANE). 중단한다." >&2
  exit 3
fi
if [ "$COMPOSE_PROJECT_NAME" = "blog_plafrom" ]; then
  echo "프로젝트 이름이 개발 스택과 같다. 중단한다." >&2
  exit 3
fi

# compose 호출 한 줄. 두 파일을 겹쳐 쓰는 것을 각 스크립트가 따로 적고 있었다.
chaos_dc() { (cd "$CHAOS_ROOT" && docker compose -f docker-compose.yml -f ops/chaos/docker-compose.chaos.yml "$@"); }

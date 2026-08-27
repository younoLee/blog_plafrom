#!/usr/bin/env bash
# 사설 CA + 와일드카드 인증서 생성. 블랙홀이 TLS를 종단하려면 필요하다.
#
# 왜 사설 CA인가 — 가로챌 대상이 전부 https다(FCM·토스·Anthropic·OpenAI…).
# 자체 서명 인증서만 쓰면 클라이언트가 검증에 실패해 **전부 '연결 오류'로 수렴**한다.
# 그러면 'refuse'와 'hang'과 'error'를 구분할 수 없어 이 훈련의 요점이 사라진다.
# CA를 컨테이너 신뢰 저장소에 넣어야 세 모드가 서로 다르게 보인다.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/certs"
mkdir -p "$DIR"

# 대상 도메인 전부를 SAN에 넣는다. 하나라도 빠지면 그 의존만 검증 실패로 갈라진다 —
# 그리고 그 갈라짐은 '주입 결과'와 구분이 안 된다.
DOMAINS=(
  fcm.googleapis.com
  web.push.apple.com
  api.tosspayments.com
  api.anthropic.com
  api.openai.com
  generativelanguage.googleapis.com
  api.cohere.com
  # S3 (2026-08-27 추가) — 08-26 회차엔 하네스에 S3 자체가 없었다.
  # boto3 는 가상호스팅 방식이라 `<버킷>.s3.<리전>.amazonaws.com` 으로 간다.
  # 와일드카드는 라벨 하나만 덮으므로 버킷명이 바뀌어도 이 한 줄로 충분하다.
  "*.s3.ap-northeast-2.amazonaws.com"
  s3.ap-northeast-2.amazonaws.com
)
# IP SAN (2026-08-27 추가) — 사용자가 `base_url` 을 정하는 compatible provider 를 재려면
# `https://<IP>/v1` 형태를 밟아야 한다. IP SAN 이 없으면 그 요청이 **TLS 단계에서 16ms에**
# 죽고, blackhole 에 기록이 0줄 남는다. 08-27 훈련에서 그 상태로 다섯 모드가 전부 동일한
# 503 을 냈고, 상태코드만 봤으면 "compatible 은 네 모드 전부 견뎠다"는 **다섯 줄짜리 거짓
# 표**가 나올 자리였다. 그걸 잡아낸 근거는 hits 20→20 하나뿐이었다.
# 레인은 lane.sh 가 10.$((200+LANE)).0.9 로 준다. 0~9번 레인의 blackhole IP 를 전부 넣는다.
IPS=()
for _l in 0 1 2 3 4 5 6 7 8 9; do IPS+=("10.$((200 + _l)).0.9"); done

SAN=$(printf 'DNS:%s,' "${DOMAINS[@]}")
SAN+=$(printf 'IP:%s,' "${IPS[@]}")
SAN=${SAN%,}

# ── 왜 '있으면 건너뛰기'를 그만뒀나 (2026-08-27) ───────────────────────────────
# 예전엔 `[ -f ca.crt ] && exit 0` 이었다. 그러면 **DOMAINS 에 도메인을 추가해도
# 인증서는 영영 안 바뀐다.** 새로 넣은 대상만 TLS 검증에 실패하는데, 그 실패는
# 프로브에서 '연결 오류'로 보여 주입 결과와 구분되지 않는다 — 훈련이 새 의존을
# "못 견뎠다"고 잘못 보고하거나, 더 흔하게는 원인을 몇십 분 헤매게 만든다.
# up.sh 의 `.env.chaos` 통째 건너뛰기와 같은 병이고, 08-26에 그것 때문에 레인3이
# 키를 손으로 넣었다. 캐시는 **입력이 그대로일 때만** 유효하다.
#
# 그래서 두 가지를 본다: ① SAN 이 지금 목록과 같은가 ② 아직 안 만료됐는가.
need_new=0
if [ ! -f "$DIR/ca.crt" ] || [ ! -f "$DIR/server.crt" ]; then
  need_new=1
else
  # **DNS 와 IP 를 둘 다 본다.** 예전엔 DNS: 만 비교해서, IP SAN 을 추가해도 드리프트
  # 검사가 "같다"고 판정하고 인증서를 안 갈았다 — 이 파일이 고치려던 병("있으면
  # 건너뛰기")이 검사 자체에 남아 있던 셈이다.
  have=$(openssl x509 -in "$DIR/server.crt" -noout -ext subjectAltName 2>/dev/null \
         | tr -d ' ' | tr ',' '\n' | /usr/bin/grep -E '^(DNS|IPAddress):' \
         | sed 's/^IPAddress:/IP:/' | sort | tr '\n' ',')
  want=$( { printf 'DNS:%s\n' "${DOMAINS[@]}"; printf 'IP:%s\n' "${IPS[@]}"; } | sort | tr '\n' ',')
  if [ "$have" != "$want" ]; then
    need_new=1
    echo "  SAN 이 목록과 다르다 → 다시 만든다"
  # 훈련 도중에 만료되면 그 시점부터의 측정이 전부 오염된다. 하루 여유를 둔다.
  elif ! openssl x509 -in "$DIR/server.crt" -noout -checkend 86400 >/dev/null 2>&1; then
    need_new=1
    echo "  인증서가 24시간 안에 만료된다 → 다시 만든다"
  fi
fi

if [ "$need_new" = "0" ]; then
  echo "  인증서 최신 (SAN: 도메인 ${#DOMAINS[@]}개 + IP ${#IPS[@]}개): $DIR"
  exit 0
fi

rm -f "$DIR"/ca.crt "$DIR"/ca.key "$DIR"/ca.srl "$DIR"/server.crt "$DIR"/server.key

openssl req -x509 -newkey rsa:2048 -nodes -days 30 \
  -keyout "$DIR/ca.key" -out "$DIR/ca.crt" \
  -subj "/CN=blog-chaos-ca" 2>/dev/null

openssl req -newkey rsa:2048 -nodes \
  -keyout "$DIR/server.key" -out "$DIR/server.csr" \
  -subj "/CN=chaos-blackhole" 2>/dev/null

openssl x509 -req -in "$DIR/server.csr" -days 30 \
  -CA "$DIR/ca.crt" -CAkey "$DIR/ca.key" -CAcreateserial \
  -extfile <(printf 'subjectAltName=%s\n' "$SAN") \
  -out "$DIR/server.crt" 2>/dev/null

rm -f "$DIR/server.csr"
chmod 600 "$DIR"/*.key
echo "  CA와 서버 인증서 생성: $DIR"
echo "  SAN: 도메인 ${#DOMAINS[@]}개 + IP ${#IPS[@]}개 (유효기간 30일 — 훈련용이라 짧게)"

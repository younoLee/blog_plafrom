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

if [ -f "$DIR/ca.crt" ] && [ -f "$DIR/server.crt" ]; then
  echo "  이미 있음: $DIR (다시 만들려면 지우고 실행)"
  exit 0
fi

# 대상 도메인 전부를 SAN에 넣는다. 하나라도 빠지면 그 의존만 검증 실패로 갈라진다.
DOMAINS=(
  fcm.googleapis.com
  web.push.apple.com
  api.tosspayments.com
  api.anthropic.com
  api.openai.com
  generativelanguage.googleapis.com
  api.cohere.com
)
SAN=$(printf 'DNS:%s,' "${DOMAINS[@]}"); SAN=${SAN%,}

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
echo "  SAN: ${#DOMAINS[@]}개 도메인 (유효기간 30일 — 훈련용이라 짧게)"

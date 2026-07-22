#!/usr/bin/env bash
# 운영 .env 에스크로 — 프로드 시크릿의 사본을 워크스테이션에 안전하게 보관/대조한다.
#
# 왜 필요한가 (백업이 있어도 못 막는 손실) —
#   EC2 `~/blog/.env`는 깃에도 S3에도 없고 그 서버에만 있다. 인스턴스를 잃으면
#   같이 사라지는데, 그중 `LLM_ENCRYPTION_KEY`는 잃는 순간 **DB 백업이 멀쩡해도**
#   `llm_credentials`의 Fernet 암호문을 영원히 못 푼다(사용자들이 맡긴 BYOK 키가
#   전부 죽는다). 행 수를 아무리 대조해도 이 손실은 안 보인다 — 복원 훈련이
#   "전부 통과"라고 말하는 동안에도 데이터는 이미 못 쓰게 돼 있을 수 있다.
#   SECRET_KEY도 같은 성격이다: 바뀌면 발급된 모든 세션 토큰이 무효가 된다.
#
# 새 노출이 생기지 않는 이유: 이 워크스테이션은 이미 SSH 키와 AWS 자격증명을 갖고
# 있어 언제든 프로드 .env를 읽을 수 있다. 사본을 두는 건 권한을 넓히는 게 아니라
# '단일 사본'을 없애는 것이다. 그래서 S3(백업 버킷)에는 올리지 않는다 — 거기 두면
# 버킷 하나가 뚫렸을 때 데이터와 그걸 푸는 열쇠가 한자리에 있게 된다.
#
# 사용:
#   scripts/env_escrow.sh save    # 프로드 .env를 ~/.blog-secrets/ 로 가져와 보관
#   scripts/env_escrow.sh check   # 원격과 사본이 같은지 해시로만 대조(값은 안 봄)
#
# 값은 어디에도 출력하지 않는다. 비교는 sha256 앞 12자리로만 한다.
#
# ⚠️ 여기까지는 '한 대 더 두는' 것뿐이다. 워크스테이션까지 잃는 경우까지 대비하려면
#    ~/.blog-secrets/prod.env 를 비밀번호 관리자에 한 번 더 넣어두는 게 맞다.
#    그건 자동화할 수 없어서 save가 끝날 때 안내만 한다.

set -euo pipefail

INSTANCE_ID=i-06da19f44d1f38eff
SSH_KEY=~/.ssh/blog-key.pem
ESCROW_DIR="$HOME/.blog-secrets"
ESCROW="$ESCROW_DIR/prod.env"
REMOTE_ENV=/home/ec2-user/blog/.env

MODE=${1:-check}

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

remote_dns() {
  local state
  state=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
    --query 'Reservations[0].Instances[0].State.Name' --output text)
  if [[ "$state" != "running" ]]; then
    echo "EC2가 '$state' 상태라 .env를 확인할 수 없습니다." >&2
    return 2
  fi
  aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
    --query 'Reservations[0].Instances[0].PublicDnsName' --output text
}

# 원격 파일의 sha256. 값은 넘어오지 않고 해시만 넘어온다.
remote_hash() {
  ssh -o StrictHostKeyChecking=no -i "$SSH_KEY" "ec2-user@$1" \
    "sudo sha256sum $REMOTE_ENV | cut -c1-64"
}

case "$MODE" in
  save)
    DNS=$(remote_dns)
    mkdir -p "$ESCROW_DIR"
    chmod 700 "$ESCROW_DIR"

    TMP=$(mktemp)
    trap 'rm -f "$TMP"' EXIT
    chmod 600 "$TMP"

    # sudo로 읽어 stdout으로 받는다(scp는 ec2-user 권한이라 .env를 못 읽을 수 있다).
    ssh -o StrictHostKeyChecking=no -i "$SSH_KEY" "ec2-user@$DNS" \
      "sudo cat $REMOTE_ENV" > "$TMP"

    [ -s "$TMP" ] || { echo "❌ 받아온 .env가 비어 있습니다 — 저장하지 않습니다." >&2; exit 1; }

    new=$(sha256sum "$TMP" | cut -c1-12)

    if [ -f "$ESCROW" ]; then
      old=$(sha256sum "$ESCROW" | cut -c1-12)
      if [ "$old" = "$new" ]; then
        say "이미 최신입니다 (sha256 $new). 그대로 둡니다."
        exit 0
      fi
      # 옛 사본을 지우면 안 된다 — 키를 교체한 경우, 그 전에 암호화된 데이터는
      # '옛 키'로만 풀린다. 새 키로 덮어쓰면 옛 암호문이 복구 불능이 된다.
      ARCHIVE="$ESCROW.$(date -u +%Y%m%dT%H%M%SZ)"
      cp -p "$ESCROW" "$ARCHIVE"
      chmod 600 "$ARCHIVE"
      say "값이 바뀌었습니다 ($old → $new). 이전 사본을 보관했습니다:"
      echo "  $ARCHIVE"
      echo "  (키 교체였다면 이 파일은 지우지 마세요 — 옛 암호문은 옛 키로만 풀립니다)"
    fi

    cp "$TMP" "$ESCROW"
    chmod 600 "$ESCROW"
    say "보관 완료 — $ESCROW (sha256 $new)"
    echo "  다음 한 가지는 손으로 해야 합니다:"
    echo "  이 파일 내용을 비밀번호 관리자에도 넣어두세요. 이 PC까지 잃으면"
    echo "  LLM_ENCRYPTION_KEY가 사라지고, DB 백업이 있어도 BYOK 키는 복구 불가입니다."
    ;;

  check)
    if [ ! -f "$ESCROW" ]; then
      echo "⚠️  운영 .env 사본이 없습니다 ($ESCROW)."
      echo "   LLM_ENCRYPTION_KEY를 잃으면 DB 백업이 있어도 BYOK 키는 복구 불가입니다."
      echo "   지금 만드세요:  scripts/env_escrow.sh save"
      exit 1
    fi

    if ! DNS=$(remote_dns); then
      echo "⚠️  서버가 꺼져 있어 대조는 못 했습니다. 사본 자체는 있습니다:"
      echo "   $ESCROW (sha256 $(sha256sum "$ESCROW" | cut -c1-12))"
      exit 2
    fi

    r=$(remote_hash "$DNS" | cut -c1-12)
    l=$(sha256sum "$ESCROW" | cut -c1-12)
    if [ "$r" = "$l" ]; then
      echo "✅ .env 사본이 서버와 일치합니다 (sha256 $l)"
    else
      echo "⚠️  .env가 서버와 다릅니다 (서버 $r / 사본 $l)."
      echo "   서버에서 값이 바뀐 뒤 사본을 안 떴다는 뜻입니다. 갱신하세요:"
      echo "   scripts/env_escrow.sh save"
      exit 1
    fi
    ;;

  *)
    echo "사용법: $0 [save|check]" >&2
    exit 64
    ;;
esac

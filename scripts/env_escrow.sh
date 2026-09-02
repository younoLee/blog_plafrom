#!/usr/bin/env bash
# 운영 시크릿 에스크로 — 프로드 `.env` 와 **SSH 개인키**의 사본을 보관/대조한다.
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
# SSH 개인키도 같이 다루는 이유 (2026-09-02에 추가) —
#   `.env` 는 사본이 셋인데 **서버에 들어가는 열쇠는 사본이 하나였다.** 키페어는
#   2026-06-24에 콘솔에서 만든 것 하나뿐이고, 개인키 `~/.ssh/blog-key.pem` 은 이 PC에만
#   있다. 인스턴스 역할(`blog-ec2-backup`)에는 SSM 권한이 없어 세션 매니저로 우회할
#   길도 없다(`list-role-policies` → s3-put 하나). 즉 **이 PC가 죽으면 서버에 영원히
#   못 들어간다** — DB도 `.env` 도 멀쩡한데 손이 닿지 않는다. 게다가 RECOVERY.md:56-63
#   자산 표에 키페어 행이 없어서 그 사실이 어디에도 안 적혀 있었다.
#   `.env` 를 지키려고 만든 이 스크립트가, 정작 그 `.env` 를 읽으러 가는 수단은
#   안 지키고 있었던 셈이다. 그래서 **같은 방식**(SSM SecureString)으로 같이 보관한다.
#
# 사용:
#   scripts/env_escrow.sh save    # 프로드 .env + SSH 개인키를 사본 자리에 보관
#   scripts/env_escrow.sh check   # 사본들이 같은지 해시로만 대조(값은 안 봄)
#
# 값은 어디에도 출력하지 않는다. 비교는 sha256 앞 12자리로만 한다.
#
# `.env` 사본은 셋이 된다: 서버 원본 · 이 PC(~/.blog-secrets) · SSM SecureString.
#   PC만 잃음   → 서버·SSM 생존      / 서버만 잃음 → PC·SSM 생존
#   PC+서버 동시 → SSM 생존
#   ⚠️ AWS 계정 자체를 잃으면 → 이 PC 사본만 남는다.
# 그래서 비밀번호 관리자에 한 벌 더 넣는 일은 여전히 사람이 해야 한다(자동화 불가).
#
# SSH 개인키 사본은 **둘**이다: 이 PC(~/.ssh/blog-key.pem) · SSM SecureString.
#   셋이 아닌 이유: 서버에는 공개키(authorized_keys)만 있고 개인키는 애초에 없다.
#   그래서 '서버 원본'에 해당하는 자리가 존재하지 않는다. 하나에서 둘로 늘리는 것이
#   여기서 할 수 있는 전부이고, 그 하나가 이 PC였다는 게 문제였다.
#   ⚠️ AWS 계정을 잃으면 → 역시 이 PC 사본만 남는다. 비밀번호 관리자 한 벌은 사람 몫.

set -euo pipefail

# 인스턴스 ID는 태그로 찾는다 — 재건할 때마다 손으로 고치던 자리다(DR 결함 F5, lib/ec2.sh).
. "$(dirname "${BASH_SOURCE[0]}")/lib/ec2.sh"
INSTANCE_ID=$(resolve_instance_id)

SSH_KEY=~/.ssh/blog-key.pem
ESCROW_DIR="$HOME/.blog-secrets"
# 세 번째 사본. PC와 서버를 **동시에** 잃는 경우를 위한 자리다.
# SSM Standard 파라미터는 무료이고(AWS 요금표: "available at no additional charge"),
# SecureString이 쓰는 AWS 관리 KMS 키도 생성·보관 무료에 요청은 월 2만 건까지 무료다.
# 저장은 이 스크립트가 돌 때뿐이고 읽기는 재해 때뿐이라 사실상 0원이다.
#
# 이걸로도 못 막는 것: **AWS 계정 자체를 잃는 경우**. 그때 남는 건 이 PC 사본뿐이라,
# 비밀번호 관리자에 한 벌 더 넣는 일은 여전히 사람이 해야 한다.
SSM_PARAM=/blog/prod/env
# SSH 개인키의 두 번째 자리. `.env` 와 같은 티어·같은 타입이라 요금도 그대로 0원이다.
SSM_KEY_PARAM=/blog/prod/ssh-key
# SSM Standard 파라미터의 값 상한(바이트). 넘으면 Advanced 티어가 필요한데 그건
# 파라미터당 **월 요금이 붙는 변경**이라 이 스크립트가 마음대로 올리지 않는다.
# RSA 2048 pem 은 1.7KB 안팎, ed25519 는 400B 안팎이라 보통은 여유가 있다.
SSM_STANDARD_MAX=4096
# 템플릿과 실제 키 집합을 대조하기 위한 경로. 값은 읽지 않고 키 '이름'만 본다.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$SCRIPT_DIR/../backend/.env.example"
ESCROW="$ESCROW_DIR/prod.env"
REMOTE_ENV=/home/ec2-user/blog/.env

MODE=${1:-check}

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

# SSM에 올린다. 로컬 사본이 이미 최신이어도 SSM은 비어 있을 수 있으므로
# '값이 바뀐 경우'가 아니라 save를 부를 때마다 확인한다.
# 실패하면 non-zero를 돌려주고 **사유를 보여준다**. 예전엔 2>/dev/null로 원인을 지우고
# 실패해도 save가 "보관 완료"로 끝나서, 헤더가 약속한 "사본은 셋이 된다"가 보장이
# 아니라 희망이 됐다(2026-07-22 코드검사에서 지적됨).
#
# 2026-09-02: 인자를 받게 바꿨다. `.env` 와 SSH 개인키가 **같은 코드**를 타야
# 한쪽만 조용히 다르게 저장되는 일이 안 생긴다(두 벌로 갈라지면 갈라진 걸 아무도 모른다).
#   $1=올릴 파일  $2=파라미터 이름  $3=사람이 읽을 이름(메시지용)
push_ssm() {
  local err size
  # 상한을 **미리** 본다. 안 보면 API가 낸 영문 오류 한 줄만 남고, 왜 실패했는지와
  # 무엇을 해야 하는지(=돈 드는 티어 변경은 사람 판단)가 안 보인다.
  size=$(wc -c < "$1")
  if [ "$size" -gt "$SSM_STANDARD_MAX" ]; then
    echo "  ❌ $3 — ${size}바이트라 SSM Standard 상한(${SSM_STANDARD_MAX}B)을 넘습니다. 저장하지 않았습니다." >&2
    echo "     Advanced 티어로 올리면 파라미터당 월 요금이 붙습니다. 사람이 판단할 일입니다." >&2
    return 1
  fi
  if err=$(aws ssm put-parameter --name "$2" --type SecureString --tier Standard \
             --overwrite --value "file://$1" 2>&1 >/dev/null); then
    echo "  SSM 사본 최신화 — $2 ($3, SecureString, Standard=무료)"
    return 0
  fi
  echo "  ❌ SSM 저장 실패 — $3 의 AWS 쪽 사본이 없습니다." >&2
  echo "     $err" >&2
  return 1
}

# ── SSH 개인키 ──────────────────────────────────────────────────────────────
# 값은 출력하지 않는다. `.env` 와 같은 규칙으로 sha256 앞 12자리로만 말한다.
#
# **키가 없는 기계에서 조용히 성공하면 안 된다.** 이 저장소는 '없는 것을 못 본 것으로
# 넘겨서' 초록이 나온 계열 버그를 세 번 겪었다(cron 백업 0건 · 이미지 AccessDenied ·
# SES 거부). 여기서 `[ -f ]` 가 거짓일 때 조용히 return 0 을 하면, 키가 아예 없는
# 기계에서 "보관 완료"가 찍힌다 — 정확히 같은 모양이다.
save_ssh_key() {
  if [ ! -f "$SSH_KEY" ]; then
    echo "  ❌ 이 기계에 SSH 개인키가 없습니다($SSH_KEY) — 보관할 것이 없습니다." >&2
    echo "     키가 있는 기계에서 돌리세요. 어느 기계에도 없다면 서버 접속 수단이" >&2
    echo "     이미 사라진 것이고, 그때는 키페어를 새로 만들어 붙이는 일이 됩니다" >&2
    echo "     (인스턴스 역할에 SSM 권한이 없어 우회 접속 경로가 없습니다)." >&2
    return 1
  fi
  local h
  h=$(sha256sum "$SSH_KEY" | cut -c1-12)
  say "SSH 개인키 보관 — $SSH_KEY (sha256 $h)"
  push_ssm "$SSH_KEY" "$SSM_KEY_PARAM" "SSH 개인키"
}

# 대조. 하나라도 어긋나면 non-zero 를 돌려준다(호출부가 RC 에 반영한다).
check_ssh_key() {
  local local_h ssm_h ssm_val
  if [ ! -f "$SSH_KEY" ]; then
    echo "⚠️  이 기계에 SSH 개인키가 없습니다($SSH_KEY)."
    # **'이 기계에만 없다'와 '어디에도 없다'는 전혀 다른 사건이다.** 앞은 내려받으면
    # 끝이고, 뒤는 서버에 들어갈 방법이 세상에 없다는 뜻이다. 뭉개지 않는다.
    if aws ssm get-parameter --name "$SSM_KEY_PARAM" --with-decryption \
         --query 'Parameter.Name' --output text >/dev/null 2>&1; then
      echo "   SSM에는 있습니다($SSM_KEY_PARAM). 이 기계로 내려받으려면:"
      echo "     aws ssm get-parameter --name $SSM_KEY_PARAM --with-decryption \\"
      echo "       --query Parameter.Value --output text > $SSH_KEY && chmod 600 $SSH_KEY"
    else
      echo "   SSM에도 없습니다($SSM_KEY_PARAM) — 서버 접속 수단이 어디에도 없습니다."
      echo "   (조회 자체가 실패했을 수도 있습니다. 권한·자격증명도 같이 확인하세요.)"
    fi
    return 1
  fi

  # 끝 개행 기준을 양쪽 다 '없음'으로 맞춘다. `$(aws … --output text)` 는 명령 치환이
  # 끝 개행을 지우는데 pem 파일은 반드시 개행으로 끝나므로, 안 맞추면 내용이 같아도
  # 해시가 달라 "사본이 다릅니다"가 뜬다 — `.env` 쪽이 2026-07-22에 겪은 그 함정이다.
  local_h=$(printf '%s' "$(cat "$SSH_KEY")" | sha256sum | cut -c1-12)
  if ssm_val=$(aws ssm get-parameter --name "$SSM_KEY_PARAM" --with-decryption \
                 --query 'Parameter.Value' --output text 2>/dev/null); then
    ssm_h=$(printf '%s' "$ssm_val" | sha256sum | cut -c1-12)
    unset ssm_val
    if [ "$ssm_h" = "$local_h" ]; then
      echo "✅ SSH 개인키 사본도 일치합니다 ($SSM_KEY_PARAM)"
      return 0
    fi
    echo "⚠️  SSH 개인키 사본이 다릅니다 (SSM $ssm_h / 이 PC $local_h)."
    echo "   키를 새로 만들었다면 갱신하세요:  scripts/env_escrow.sh save"
    return 1
  fi
  echo "⚠️  SSM에 SSH 개인키 사본이 없습니다($SSM_KEY_PARAM)."
  echo "   이 PC를 잃으면 서버에 영원히 못 들어갑니다(인스턴스 역할에 SSM 권한이 없어"
  echo "   세션 매니저 우회도 안 됩니다). 지금 만드세요:  scripts/env_escrow.sh save"
  return 1
}

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
        say "로컬 사본은 이미 최신입니다 (sha256 $new)."
        push_ssm "$TMP" "$SSM_PARAM" ".env" || exit 1
        # ⚠️ 여기서 그냥 `exit 0` 하면 **키 보관을 건너뛴다.** 그리고 `.env` 가 안 바뀐
        # 경우가 곧 평상시라, 그러면 키는 사실상 영원히 안 올라간다. 이 저장소가
        # 반복해서 만든 '있는데 한 번도 안 도는 경로'가 정확히 이 모양이다.
        save_ssh_key || exit 1
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

    # 따로 올리면 언젠가 어긋나고, 어긋난 백업은 없는 것보다 나쁘다(있다고 믿게 만든다).
    push_ssm "$TMP" "$SSM_PARAM" ".env" || exit 1

    # 열쇠도 같은 호출에서 함께 올린다. 별도 명령으로 두면 "그건 안 돌렸다"가 생기고,
    # 그 상태는 아무 데도 안 뜬다(이 스크립트가 애초에 막으려던 것과 같은 병).
    save_ssh_key || exit 1

    echo "  다음 한 가지는 손으로 해야 합니다:"
    echo "  이 파일 내용을 비밀번호 관리자에도 넣어두세요. 이 PC까지 잃으면"
    echo "  LLM_ENCRYPTION_KEY가 사라지고, DB 백업이 있어도 BYOK 키는 복구 불가입니다."
    echo "  SSH 개인키도 같이 넣어두세요 — AWS 계정을 잃으면 SSM 사본도 같이 사라집니다."
    ;;

  check)
    # 하나라도 어긋나면 non-zero로 끝낸다. 예전엔 SSM이 없거나 달라도 ⚠️만 찍고
    # exit 0이라, "세 사본 대조"라는 이름과 달리 세 번째가 종료코드에 없었다.
    RC=0
    if [ ! -f "$ESCROW" ]; then
      echo "⚠️  운영 .env 사본이 없습니다 ($ESCROW)."
      echo "   LLM_ENCRYPTION_KEY를 잃으면 DB 백업이 있어도 BYOK 키는 복구 불가입니다."
      echo "   지금 만드세요:  scripts/env_escrow.sh save"
      exit 1
    fi

    l=$(sha256sum "$ESCROW" | cut -c1-12)

    # SSM 대조를 서버보다 **먼저** 한다. 이 서버는 필요할 때만 켜므로 대부분 꺼져 있는데,
    # 예전엔 서버에 못 닿으면 여기까지 오기 전에 빠져나가 세 번째 사본을 아예 안 봤다.
    # 로컬과 SSM은 서버 상태와 무관하게 언제나 대조할 수 있다.
    #
    # 양쪽을 '끝 개행 제거' 기준으로 맞춰서 비교한다. 파일은 개행으로 끝나는데
    # `$(aws ... --output text)`는 명령 치환이 끝 개행을 지워버려서, 내용이 같은데도
    # 해시가 달라 "사본이 다릅니다"가 뜬다(2026-07-22에 실제로 겪었다).
    if ssm_val=$(aws ssm get-parameter --name "$SSM_PARAM" --with-decryption \
                   --query 'Parameter.Value' --output text 2>/dev/null); then
      ssm_hash=$(printf '%s' "$ssm_val" | sha256sum | cut -c1-12)
      unset ssm_val
      l_norm=$(printf '%s' "$(cat "$ESCROW")" | sha256sum | cut -c1-12)
      if [ "$ssm_hash" = "$l_norm" ]; then
        echo "✅ SSM 사본도 일치합니다 ($SSM_PARAM)"
      else
        echo "⚠️  SSM 사본이 다릅니다 (SSM $ssm_hash / 사본 $l_norm) — scripts/env_escrow.sh save 로 갱신하세요."
        RC=1
      fi
    else
      echo "⚠️  SSM에 사본이 없습니다($SSM_PARAM). PC와 서버를 동시에 잃으면 복구 불가:"
      echo "   scripts/env_escrow.sh save"
      RC=1
    fi

    # 템플릿이 실제 키 집합과 맞는지 본다. 예전엔 세 사본의 **파일 해시**만 대조해서,
    # 운영에 새 키가 생기면 세 사본은 계속 일치하고 템플릿만 조용히 낡았다.
    # `PAYMENTS_REQUIRE_LIVE`가 아예 없던 채로 돌던 것이 정확히 이 장치가 없어서였다.
    if [ -f "$TEMPLATE" ]; then
      only_env=$(comm -23 <(grep -oE '^[A-Za-z0-9_]+=' "$ESCROW" | tr -d = | LC_ALL=C sort) \
                          <(grep -oE '^#? ?[A-Za-z0-9_]+=' "$TEMPLATE" | tr -d '#= ' | LC_ALL=C sort) | tr '\n' ' ')
      if [ -n "${only_env// /}" ]; then
        echo "⚠️  운영에는 있는데 템플릿(backend/.env.example)에 없는 키: $only_env"
        echo "   재해 복구 때 이 값들을 빠뜨리게 됩니다."
        RC=1
      else
        echo "✅ 템플릿이 실제 키 집합을 전부 덮습니다"
      fi
    fi

    # SSH 개인키 사본. **서버 대조보다 앞에 둔다** — 서버가 꺼져 있으면 아래에서
    # 곧바로 exit 하므로, 뒤에 두면 평상시(서버 꺼짐)에 한 번도 안 도는 검사가 된다.
    # SSM 쪽 `.env` 대조를 서버보다 먼저 옮긴 것과 같은 이유다.
    check_ssh_key || RC=1

    # 서버는 꺼져 있을 수 있다. 그건 이상이 아니므로 RC를 올리지 않는다.
    if ! DNS=$(remote_dns 2>/dev/null); then
      echo "--   서버가 꺼져 있어 원본과의 대조는 생략(사본 자체는 위에서 확인함)"
      exit "$RC"
    fi
    r=$(remote_hash "$DNS" | cut -c1-12)

    if [ "$r" = "$l" ]; then
      echo "✅ .env 사본이 서버와 일치합니다 (sha256 $l)"
    else
      echo "⚠️  .env가 서버와 다릅니다 (서버 $r / 사본 $l)."
      echo "   서버에서 값이 바뀐 뒤 사본을 안 떴다는 뜻입니다. 갱신하세요:"
      echo "   scripts/env_escrow.sh save"
      RC=1
    fi
    exit "$RC"
    ;;

  *)
    echo "사용법: $0 [save|check]" >&2
    exit 64
    ;;
esac

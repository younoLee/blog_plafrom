#!/usr/bin/env bash
# EC2 정지 절차: 백업 → 오리진 주차 → 정지 → 검증.
#
# 왜 스크립트인가 —
#   ① 순서가 안전에 직결된다. 주차(terraform apply)가 정지보다 '먼저' 와야 한다.
#      뒤집으면 IP가 반납된 뒤에도 오리진이 옛 ec2-<IP>...를 가리켜, 그 사이
#      /api/*가 그 IP를 새로 받은 제3자에게 간다(dangling origin).
#   ② 백업이 여기 있어야 실제로 돈다. 옛 cron(0 18 * * * = KST 03시)은 그 시각에
#      서버가 꺼져 있어 2026-07-20까지 단 한 번도 실행되지 않았다(그래서 제거했다).
#      DB가 바뀌는 건 EC2가 켜진 동안뿐이니, 백업의 올바른 자리는 '끄기 직전'이다.
#
# 사용:
#   scripts/stop_server.sh                # 백업 → 주차 → 정지
#   scripts/stop_server.sh --skip-backup  # 백업 건너뜀(DB 무변경이 확실할 때만)
#
# 백업이 실패하면 정지하지 않고 멈춘다 — 사본 없이 끄지 않기 위해서다.
# 이때 EC2는 켜진 채로 남으므로, 메시지를 보고 직접 판단해야 한다(크레딧 소모).

set -euo pipefail

INSTANCE_ID=i-06da19f44d1f38eff
BUCKET=blog-db-backups-181568979775
SSH_KEY=~/.ssh/blog-key.pem
CF_URL=https://d2j66m9udyg9yq.cloudfront.net
TF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../terraform" && pwd)"

SKIP_BACKUP=false
[[ "${1:-}" == "--skip-backup" ]] && SKIP_BACKUP=true

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

# ── 0. 상태 확인 ────────────────────────────────────────────────────────────
state=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].State.Name' --output text)
if [[ "$state" != "running" ]]; then
  say "EC2가 이미 '$state' 상태입니다."
  # 켜져 있지 않아도 주차는 해둬야 한다(꺼진 채 오리진만 옛 주소인 경우 방지).
  say "오리진 주차만 확인합니다."
  terraform -chdir="$TF_DIR" apply -auto-approve
  exit 0
fi

DNS=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].PublicDnsName' --output text)

# ── 1. 백업 ─────────────────────────────────────────────────────────────────
if $SKIP_BACKUP; then
  say "1/4 백업 — 건너뜀(--skip-backup)"
else
  say "1/4 백업 — pg_dump → S3"
  before=$(aws s3 ls "s3://$BUCKET/" | wc -l)

  if ! ssh -o StrictHostKeyChecking=no -i "$SSH_KEY" "ec2-user@$DNS" \
      'sudo /usr/local/bin/blog-db-backup.sh'; then
    say "❌ 백업 실패 — 정지하지 않고 멈춥니다. EC2는 아직 켜져 있습니다."
    echo "   사본 없이 끄지 않으려는 의도적 중단입니다. 원인을 보고 판단하세요:"
    echo "     - 다시 시도: $0"
    echo "     - 백업 없이 강행: $0 --skip-backup"
    exit 1
  fi

  # '스크립트가 성공했다'와 '객체가 늘었다'는 다르다 — 산출물로 확인한다.
  after=$(aws s3 ls "s3://$BUCKET/" | wc -l)
  if (( after <= before )); then
    say "❌ 백업 스크립트는 성공했는데 S3 객체가 늘지 않았습니다($before → $after)."
    echo "   정지하지 않습니다. 버킷을 직접 확인하세요: aws s3 ls s3://$BUCKET/"
    exit 1
  fi
  latest=$(aws s3 ls "s3://$BUCKET/" | sort | tail -1)
  echo "   최신 백업: $latest"
fi

# ── 2. 오리진 주차 (반드시 정지보다 먼저) ───────────────────────────────────
say "2/4 오리진 주차 — terraform apply (기본값 → S3 주차 주소)"
terraform -chdir="$TF_DIR" apply -auto-approve

# ── 3. 정지 ─────────────────────────────────────────────────────────────────
say "3/4 EC2 정지"
aws ec2 stop-instances --instance-ids "$INSTANCE_ID" \
  --query 'StoppingInstances[0].CurrentState.Name' --output text
aws ec2 wait instance-stopped --instance-ids "$INSTANCE_ID"

# ── 4. 검증 ─────────────────────────────────────────────────────────────────
say "4/4 검증"
aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].{State:State.Name,PublicIp:PublicIpAddress}' --output json
echo "EIP 개수 (0이어야 함):     $(aws ec2 describe-addresses --query 'length(Addresses)' --output text)"
echo "프론트 홈 (200 기대):      $(curl -s -o /dev/null -w '%{http_code}' --max-time 30 "$CF_URL/")"
echo "/api/status (504 기대):    $(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$CF_URL/api/status")"
say "완료 — 504는 주차가 fail closed로 동작한다는 뜻입니다(정상)."

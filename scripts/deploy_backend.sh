#!/usr/bin/env bash
# 백엔드 배포: 코드를 tar로 묶어 EC2 ~/blog 에 풀고, 재빌드 명령을 안내한다.
#
# 왜 스크립트인가 — 이 저장소의 다른 절차(정지·백업·복원·에스크로·감시)는 전부
# 스크립트인데 **배포만 PROGRESS.md의 산문**으로만 있었다. 그래서 같은 절차가
# 문서마다 달라졌고, 2026-07-22에 실제로 사고를 만들었다: `.dockerignore`를 tar에
# 넣어야 한다는 걸 임시 인스턴스 리허설에서 발견해 RECOVERY.md만 고쳤는데,
# PROGRESS의 배포 서술 두 곳은 그대로여서 그걸 보고 배포하면 재발한다.
# 절차를 코드로 굳혀야 한 곳만 고치면 된다.
#
# `.dockerignore`가 빠지면 무슨 일이 나는가 (실증함):
#   빌드 컨텍스트가 ~/blog 이므로 Dockerfile의 `COPY . .`가 **`.env`를 이미지에 굽는다**
#   (그 파일이 "시크릿은 절대 이미지에 굽지 않음"이라고 못박아둔 바로 그 일). 게다가
#   pydantic이 dotenv의 여분 키(`DB_PASSWORD`·`ADMIN_EMAIL` — Settings에 없는 필드)를
#   extra_forbidden으로 거부해 백엔드가 재시작 루프에 빠진다. 운영 서버는 예전 배포 때
#   올라간 `.dockerignore`가 이미 있어서 안 겪고, **새 인스턴스에서만** 터진다.
#
# 마지막 재빌드는 일부러 여기서 실행하지 않는다 — 규칙7(프로덕션 앱 코드를 갈아끼우는
# 명령은 사용자가 직접 실행). 준비까지 하고 명령을 출력한다.
#
# 사용:
#   scripts/deploy_backend.sh

set -euo pipefail

INSTANCE_ID=i-06da19f44d1f38eff
SSH_KEY=~/.ssh/blog-key.pem
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

state=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].State.Name' --output text)
if [[ "$state" != "running" ]]; then
  echo "EC2가 '$state' 상태입니다. 먼저 켜세요:" >&2
  echo "  aws ec2 start-instances --instance-ids $INSTANCE_ID" >&2
  exit 1
fi
DNS=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].PublicDnsName' --output text)

# ── 1. 묶기 ────────────────────────────────────────────────────────────────
# `.dockerignore`가 첫 항목인 게 중요하다(위 주석 참고). `.env`와 uploads/는
# 그 파일이 알아서 빌드 컨텍스트에서 제외한다 — 여기서 tar에 안 넣는 것과 별개다.
say "1/4 코드 묶기"
tar czf "$STAGE/backend.tgz" -C "$REPO_DIR/backend" \
  .dockerignore app alembic alembic.ini requirements.txt Dockerfile
echo "  $(stat -c%s "$STAGE/backend.tgz") bytes"

# ── 2. .env 보존 확인용 지문 ────────────────────────────────────────────────
# 추출이 `.env`를 건드리지 않는다는 걸 '믿는' 대신 앞뒤로 해시를 재서 확인한다.
# (값은 출력하지 않는다)
before=$(ssh -n -o StrictHostKeyChecking=no -i "$SSH_KEY" "ec2-user@$DNS" \
  'sudo sha256sum /home/ec2-user/blog/.env | cut -c1-12')
echo "  배포 전 .env 지문: $before"

# ── 3. 올리고 풀기 ─────────────────────────────────────────────────────────
say "2/4 전송·추출"
scp -q -o StrictHostKeyChecking=no -i "$SSH_KEY" \
  "$STAGE/backend.tgz" "$REPO_DIR/docker-compose.prod.yml" "ec2-user@$DNS:/home/ec2-user/blog/"
ssh -n -o StrictHostKeyChecking=no -i "$SSH_KEY" "ec2-user@$DNS" \
  'cd /home/ec2-user/blog && tar xzf backend.tgz && rm -f backend.tgz && ls -a | head -20'

say "3/4 .env 보존 확인"
after=$(ssh -n -o StrictHostKeyChecking=no -i "$SSH_KEY" "ec2-user@$DNS" \
  'sudo sha256sum /home/ec2-user/blog/.env | cut -c1-12')
if [ "$before" != "$after" ]; then
  echo "❌ .env가 바뀌었습니다($before → $after). 재빌드하지 마세요." >&2
  exit 1
fi
echo "  동일 ($after) — 시크릿 보존됨"

# ── 4. 방아쇠는 사용자에게 ──────────────────────────────────────────────────
say "4/4 재빌드는 직접 실행하세요 (규칙7)"
cat <<CMD
  ssh -i $SSH_KEY ec2-user@$DNS \\
    'cd ~/blog && sudo docker compose -f docker-compose.prod.yml up -d --build'

  끝나면 확인 — healthy가 될 때까지 **기다린다**(눈으로 보는 대신):
    ssh -i $SSH_KEY ec2-user@$DNS 'for i in \$(seq 1 40); do \\
        s=\$(sudo docker inspect -f "{{.State.Health.Status}}" blog-backend-1 2>/dev/null); echo "  \$s"; \\
        [ "\$s" = healthy ] && exit 0; [ "\$s" = unhealthy ] && exit 1; sleep 5; done; exit 1'
    ssh -i $SSH_KEY ec2-user@$DNS \\
      'cd ~/blog && sudo docker compose -f docker-compose.prod.yml exec -T backend alembic current'
    curl -s https://d2j66m9udyg9yq.cloudfront.net/api/status
CMD
echo
echo "⚠️  이번 재빌드부터 PAYMENTS_REQUIRE_LIVE=true 가 반영됩니다 —"
echo "    토스 라이브 키가 없으면 결제 승인이 503으로 거부됩니다(공짜 Pro 차단, 의도된 동작)."

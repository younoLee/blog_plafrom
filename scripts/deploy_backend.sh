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
# ⚠️ 이 스크립트는 **보내기만 한다.** 나간 것이 실제로 도는지는 짝인
# `scripts/verify_deploy.sh`가 잰다(앱 해시·alembic·uid·헬스·오리진 가드·로그·공개 경로).
# 절차: deploy_backend.sh → 사용자 재빌드 → verify_deploy.sh.
# 왜 나눴는가: 재빌드가 사용자 셸에서 도니 그 뒤에 붙일 자리가 없고, "지금 운영에 뭐가
# 떠 있나"는 배포와 무관한 때에도 물을 수 있어야 한다(2026-08-11에 미배포 목록이 낡아
# 헛수고할 뻔했다 — 해시를 떠보고 알았다).
#
# 사용:
#   scripts/deploy_backend.sh

set -euo pipefail

# 인스턴스 ID는 태그로 찾는다 — 재건할 때마다 손으로 고치던 자리다(DR 결함 F5, lib/ec2.sh).
. "$(dirname "${BASH_SOURCE[0]}")/lib/ec2.sh"
INSTANCE_ID=$(resolve_instance_id)

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
say "1/5 코드 묶기"
# scripts/ 도 포함한다 — 가입이 초대제라 계정은 scripts/create_user.py 로만 만든다.
# 이게 빠지면 `exec backend python scripts/create_user.py` 가 프로드 컨테이너에
# 파일이 없어 실패한다(프로드는 코드 볼륨 마운트가 없어 이미지에 구워진 것만 있다).
tar czf "$STAGE/backend.tgz" -C "$REPO_DIR/backend" \
  .dockerignore app alembic alembic.ini requirements.txt Dockerfile scripts
echo "  $(stat -c%s "$STAGE/backend.tgz") bytes"

# 서버에서 **지울 목록을 tar 자신에게서 뽑는다.** 위 tar 인자를 여기 다시 적으면
# 둘이 갈라지고, 갈라진 건 아무도 모른다(런북 결함 D3와 같은 모양이라 목록을 안 늘린다).
ENTRIES=$(tar tzf "$STAGE/backend.tgz" | cut -d/ -f1 | sort -u | tr '\n' ' ')
# 안전판: 지우면 안 되는 것이 목록에 섞이면 즉시 멈춘다. `rm -rf`를 원격에서 도는
# 명령에 넣는 이상, 목록이 무엇인지 **기계가 확인한 뒤에만** 보낸다.
for e in $ENTRIES; do
  case "$e" in
    .env | .env.* | uploads | docker-compose.prod.yml | . | .. | /* | *"*"* )
      echo "❌ 지우면 안 되는 항목이 tar 목록에 있습니다: '$e' — 중단합니다." >&2
      exit 1 ;;
  esac
done
[ -n "${ENTRIES// /}" ] || { echo "❌ tar 목록이 비었습니다 — 중단합니다." >&2; exit 1; }
echo "  교체 대상: $ENTRIES"

# ── 2. .env 보존 확인용 지문 ────────────────────────────────────────────────
# 추출이 `.env`를 건드리지 않는다는 걸 '믿는' 대신 앞뒤로 해시를 재서 확인한다.
# (값은 출력하지 않는다)
before=$(ssh -n -o StrictHostKeyChecking=accept-new -i "$SSH_KEY" "ec2-user@$DNS" \
  'sudo sha256sum /home/ec2-user/blog/.env | cut -c1-12')
echo "  배포 전 .env 지문: $before"

# ── 3. 올리고 풀기 ─────────────────────────────────────────────────────────
say "2/5 전송·추출"
scp -q -o StrictHostKeyChecking=accept-new -i "$SSH_KEY" \
  "$STAGE/backend.tgz" "$REPO_DIR/docker-compose.prod.yml" "ec2-user@$DNS:/home/ec2-user/blog/"
# **덧씌우기가 아니라 교체한다.** 예전에는 `tar xzf`만 했는데, 그러면 새 파일과 바뀐
# 파일은 가지만 **저장소에서 지운 파일이 서버에 그대로 남는다.** 2026-08-28 배포에서
# 실제로 물렸다 — subscribers 폐기 커밋이 지운 .py 셋이 서버에 남아 그대로 이미지에
# 구워졌고, DB에는 그 테이블이 없는 상태였다. verify_deploy.sh가 사후에 잡아줬지만
# 그건 이미 도는 것을 보고 잡는 것이고, 여기서 안 지우면 다음 삭제 때 또 열린다.
# `.env`·uploads/ 는 위 안전판이 목록에 없음을 확인했으므로 손대지 않는다.
ssh -n -o StrictHostKeyChecking=accept-new -i "$SSH_KEY" "ec2-user@$DNS" \
  "cd /home/ec2-user/blog && rm -rf $ENTRIES && tar xzf backend.tgz && rm -f backend.tgz && ls -a | head -20"

say "3/5 .env 보존 확인"
after=$(ssh -n -o StrictHostKeyChecking=accept-new -i "$SSH_KEY" "ec2-user@$DNS" \
  'sudo sha256sum /home/ec2-user/blog/.env | cut -c1-12')
# 지문이 **비어 있으면** 비교가 성립하지 않는다. 로컬의 set -euo pipefail은 ssh 너머
# 원격 셸에 적용되지 않아서, `.env`가 없거나 sudo가 막히면 파이프라인 종료코드는 cut의
# 0이고 출력은 빈 문자열이다 → `"" != ""`이 거짓이라 **그대로 통과하고** 다음 줄에
# `동일 () — 시크릿 보존됨`을 찍은 뒤 재빌드 명령을 안내했다. 이 검사가 존재하는 유일한
# 이유가 정확히 그 경우다(2026-08-10 심층검사). 길이를 먼저 본다.
if [ ${#before} -ne 12 ] || [ ${#after} -ne 12 ]; then
  echo "❌ .env 지문을 읽지 못했습니다(before='$before' after='$after')." >&2
  echo "   서버에 /home/ec2-user/blog/.env 가 없거나 sudo가 막힌 상태입니다." >&2
  echo "   시크릿 보존을 확인할 수 없으므로 재빌드하지 마세요." >&2
  exit 1
fi
if [ "$before" != "$after" ]; then
  echo "❌ .env가 바뀌었습니다($before → $after). 재빌드하지 마세요." >&2
  exit 1
fi
echo "  동일 ($after) — 시크릿 보존됨"

# ── 4. 보낸 것과 서버에 있는 것이 같은가 ───────────────────────────────────
# 위 교체가 **실제로 먹었는지**를 여기서 잰다. 규칙을 쓴 다음에는 몇 개가 걸리는지
# 세어본다는 이 저장소의 습관이 그대로 적용되는 자리다 — 삭제 전파는 "안 지워졌다"가
# 조용한 결함이라 특히 그렇다.
#
# verify_deploy.sh 와 **같은 방식**으로 잰다(파일 목록 + 내용의 해시). 다만 그쪽은
# 재빌드 뒤 **컨테이너 안**을 보고, 여기는 재빌드 전 **서버 디렉터리**를 본다.
# 그래서 여기서 어긋나면 원인은 전송이고, 여기가 맞는데 그쪽이 어긋나면 원인은 빌드다.
say "4/5 전송 대조 — 서버의 app/ 이 로컬과 같은가"
local_app=$(cd "$REPO_DIR/backend" && LC_ALL=C find app -name "*.py" | LC_ALL=C sort \
  | xargs sha256sum | sha256sum | cut -d' ' -f1)
remote_app=$(ssh -n -o StrictHostKeyChecking=accept-new -i "$SSH_KEY" "ec2-user@$DNS" \
  'cd /home/ec2-user/blog && LC_ALL=C find app -name "*.py" | LC_ALL=C sort | xargs sha256sum | sha256sum | cut -d" " -f1' \
  2>/dev/null | tr -d "\r")
if [ ${#remote_app} -ne 64 ]; then
  echo "❌ 서버의 app/ 해시를 못 읽었습니다(값: '$remote_app'). 재빌드하지 마세요." >&2
  exit 1
elif [ "$local_app" != "$remote_app" ]; then
  echo "❌ 서버의 app/ 이 로컬과 다릅니다 — 로컬 ${local_app:0:12} ≠ 서버 ${remote_app:0:12}" >&2
  echo "   교체가 안 먹었거나 전송이 부분적으로 끝났습니다. 재빌드하지 마세요." >&2
  echo "   차이를 보려면:" >&2
  echo "     ssh -i $SSH_KEY ec2-user@$DNS 'cd ~/blog && find app -name \"*.py\" | sort'" >&2
  exit 1
fi
echo "  동일 (${local_app:0:12}) — 지운 파일까지 반영됐다"


# ── 4. 방아쇠는 사용자에게 ──────────────────────────────────────────────────
say "5/5 재빌드는 직접 실행하세요 (규칙7)"
cat <<CMD
  ssh -i $SSH_KEY ec2-user@$DNS \\
    'cd ~/blog && sudo docker compose -f docker-compose.prod.yml up -d --build'

  끝나면 **반드시** 검증하세요 — 보낸 것과 도는 것은 다릅니다:
    scripts/verify_deploy.sh
CMD
echo
echo "⚠️  이번 재빌드부터 PAYMENTS_REQUIRE_LIVE=true 가 반영됩니다 —"
echo "    토스 라이브 키가 없으면 결제 승인이 503으로 거부됩니다(공짜 Pro 차단, 의도된 동작)."

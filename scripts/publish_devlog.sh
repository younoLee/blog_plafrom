#!/usr/bin/env bash
# 개발일지 한 편 발행 — payload 빌드 → 전송 → 컨테이너 안에서 발행 → 실측 확인까지 한 번에.
#
# 왜 스크립트인가: 이 절차는 여태 **publish_devlogs.py의 docstring 산문**으로만 있었다.
# 그래서 매번 사람이 네 단계를 손으로 이어 붙였고, 그때마다 같은 것을 기억해야 했다 —
# `-e PYTHONPATH=/app`(없으면 ModuleNotFoundError), 호스트 /tmp와 컨테이너 /tmp가 다른
# 파일시스템이라는 것, payload를 저장소가 아니라 밖에 뽑아야 root 소유 파일이 안 남는다는 것.
# 2026-08-17에 #32를 발행하며 그 넷을 또 손으로 이었다. 절차를 코드로 굳히면 한 곳만 고치면 된다.
#
# ⚠️ **`devlog_to_markdown.py`는 여기서 안 부른다.** 그건 32편을 전부 다시 쓰기 때문에
# 손으로 고친 옛 편이 되살아난다(2026-08-15에 실제로 겪었다). 발행에 필요한 건 payload뿐이고
# 마크다운은 이미 저장소에 있다.
#
# 사용:
#   scripts/publish_devlog.sh 2026-08-18
#   scripts/publish_devlog.sh 2026-08-18 2026-08-19    # 여러 편 한 번에

set -euo pipefail

if [[ $# -eq 0 ]]; then
  echo "사용: $(basename "$0") <날짜> [날짜…]   (예: $(basename "$0") 2026-08-18)" >&2
  exit 2
fi

. "$(dirname "${BASH_SOURCE[0]}")/lib/ec2.sh"
INSTANCE_ID=$(resolve_instance_id)
SSH_KEY=~/.ssh/blog-key.pem
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REMOTE_USER=ec2-user # ubuntu 아니다 — 2026-08-17에 여기서 한 번 막혔다

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

# payload는 **저장소 밖**에 만든다. 저장소 안에 두면 git status가 더러워지고,
# 예전엔 컨테이너가 만든 root 소유 파일을 지우려다 docx를 날린 적도 있다(2026-08-12).
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
PAYLOAD="$STAGE/devlog_posts.json"

say "1/4 payload 만들기 ($*)"
# 의존성 없이 로컬 파이썬으로 돈다(2026-08-15부터 — POSTS를 devlog_posts.py로 떼면서).
python3 "$SCRIPT_DIR/build_devlog_payload.py" -o "$PAYLOAD" "$@"

say "2/4 전송"
scp -q -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new \
  "$PAYLOAD" "$SCRIPT_DIR/publish_devlogs.py" "$REMOTE_USER@$DNS:/tmp/"

say "3/4 컨테이너 안에서 발행"
# 호스트 /tmp와 컨테이너 /tmp는 다른 파일시스템이라 scp만으로는 안 들어간다 → compose cp.
# PYTHONPATH=/app이 없으면 sys.path[0]이 /tmp라 app 모듈을 못 찾는다(2026-07-22에 걸렸다).
ssh -n -i "$SSH_KEY" "$REMOTE_USER@$DNS" '
  set -euo pipefail
  cd ~/blog
  sudo docker compose -f docker-compose.prod.yml cp /tmp/publish_devlogs.py backend:/tmp/publish_devlogs.py
  sudo docker compose -f docker-compose.prod.yml cp /tmp/devlog_posts.json  backend:/tmp/devlog_posts.json
  sudo docker compose -f docker-compose.prod.yml exec -T -e PYTHONPATH=/app backend \
    python /tmp/publish_devlogs.py /tmp/devlog_posts.json
'

say "4/4 실측 — DB의 연재 편수 vs 저장소의 마크다운 편수"
local_count=$(find "$REPO_DIR/content/devlog" -name '*.md' | wc -l | tr -d ' ')
db_count=$(ssh -n -i "$SSH_KEY" "$REMOTE_USER@$DNS" '
  cd ~/blog && sudo docker compose -f docker-compose.prod.yml exec -T db \
    psql -U postgres -d postgres -tAc "select count(*) from posts where series = '"'"'블로그 만들기'"'"';"
' | tr -d '[:space:]')

echo "   마크다운 $local_count편 · DB 연재 $db_count편"
if [[ "$local_count" != "$db_count" ]]; then
  echo "   ⚠️  숫자가 다릅니다 — 아직 발행 안 된 편이 있거나 DB에 여분이 있습니다." >&2
  echo "      (마크다운은 있는데 DB에 없으면: 그 날짜로 이 스크립트를 다시 돌리세요)" >&2
  exit 1
fi

say "발행 완료 — 연재 $db_count편"
echo "  남은 것: 프론트 Actions에서 'Deploy Frontend' → Run workflow"
echo "  (안 누르면 정적 아카이브·RSS·sitemap이 옛 편수로 남습니다)"

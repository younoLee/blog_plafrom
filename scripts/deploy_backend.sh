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
#   scripts/deploy_backend.sh --skip-backup   # 백업 건너뜀(DB 무변경이 확실할 때만)
#
# ⚠️ 재빌드는 마이그레이션을 돈다 — 그래서 **재빌드 안내 전에 백업을 뜬다**(5/6).
# 실패하면 안내를 내지 않고 멈춘다(fail closed). 아래 5/6 절 주석에 근거가 있다.

set -euo pipefail

# 오타(--skip_backup 등)를 조용히 무시하면 의도와 다른 절차가 돈다(정지 절차와 같은 규칙).
SKIP_BACKUP=false
case "${1:-}" in
  "")            ;;
  --skip-backup) SKIP_BACKUP=true ;;
  *) echo "알 수 없는 인자: $1" >&2; echo "사용법: $0 [--skip-backup]" >&2; exit 64 ;;
esac

# 인스턴스 ID는 태그로 찾는다 — 재건할 때마다 손으로 고치던 자리다(DR 결함 F5, lib/ec2.sh).
. "$(dirname "${BASH_SOURCE[0]}")/lib/ec2.sh"
INSTANCE_ID=$(resolve_instance_id)

SSH_KEY=~/.ssh/blog-key.pem
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# 5/6 백업이 올라간 것을 이름으로 다시 확인할 버킷. 정지 절차·감시·백업 스크립트가
# 쓰는 것과 같은 값이다(scripts/blog-db-backup.sh 가 실제로 올리는 곳).
BACKUP_BUCKET=blog-db-backups-181568979775

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
say "1/6 코드 묶기"
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
say "2/6 전송·추출"
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

say "3/6 .env 보존 확인"
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
say "4/6 전송 대조 — 서버의 app/ 이 로컬과 같은가"
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


# ── 5. 재빌드 직전 백업 ─────────────────────────────────────────────────────
# 2026-09-02: 이 파일에 백업 호출이 **0건**이었다. 그런데 아래가 안내하는 재빌드는
# docker-compose.prod.yml:117 의 `alembic upgrade head` 를 돌린다. 즉 이 스크립트의
# 마지막 줄이 **스키마를 바꾸는 명령**을 사람 손에 쥐여 주면서, 그 직전 사본은
# 아무도 안 뜨고 있었다.
#
# 왜 지금 필요한가 (둘 다 실측) —
#   · 2026-08-28 배포에는 **테이블을 지우는 마이그레이션**이 있었다
#     (alembic/versions/e7f8a9b0c1d2_drop_subscribers.py). 되돌리려면 사본이 있어야 한다.
#   · 2026-08-10 하루에 덤프가 4개 생겼다 = **세션 중 쓰기가 실재한다.** 즉 "마지막
#     정지 때 뜬 사본이면 충분하다"가 참이 아니다. 마지막 정지 이후의 글·댓글·결제는
#     그 사본에 없다.
#
# 왜 여기(안내 직전)인가 — 규칙7 때문에 재빌드는 이 스크립트가 안 돌린다. 그래서
# '재빌드 직전'으로 잡을 수 있는 유일한 자리가 안내를 내기 직전이다. 앞 단계들이
# 전부 통과한 뒤이기도 해서, 어차피 배포가 중단될 상황에 백업만 뜨는 낭비도 없다.
#
# **백업이 실패하면 멈춘다(fail closed).** 안내를 안 내는 것으로 멈춘다 — 사본 없이
# 마이그레이션을 돌리지 않기 위해서다. 정지 절차 2/6이 "사본 없이 끄지 않는다"로
# 멈추는 것과 같은 판단이다.
#
# **절차는 재사용한다.** 여기서 백업 절차를 새로 쓰지 않고 정지 절차와 **같은 파일**
# (scripts/blog-db-backup.sh)을 같은 방식으로 올려서 돌린다. 두 벌로 갈라지면 갈라진
# 걸 아무도 모른다 — 이 저장소가 D3(런북 드리프트)로 반복해 배운 것이다.
# 검증 3종(gzip -t · 최소 크기 · pg_dump 완료 표식)은 그 파일 안에 있어서 **올리기 전에**
# 돈다. 그래서 여기 호출자 쪽에는 정지 절차의 '직전 대비 크기 급감' 비교를 옮겨오지
# 않는다 — 그 휴리스틱을 두 곳에 복사하는 것이야말로 위에서 경계한 그 갈라짐이고,
# 잘린 덤프는 이미 서버 쪽 3종이 업로드 전에 막는다. 여기서는 '스크립트가 성공했다'와
# '그 객체가 S3에 있다'가 다르다는 것만 이름으로 확인한다(정지 절차와 같은 이유).
if $SKIP_BACKUP; then
  say "5/6 재빌드 직전 백업 — 건너뜀(--skip-backup)"
  echo "  ⚠️  사본 없이 마이그레이션을 돌리게 됩니다. DB 무변경이 확실한 경우에만 쓰세요."
else
  say "5/6 재빌드 직전 백업 — pg_dump → 검증 → S3"
  # 파일을 미리 만들어 둔다. scp가 실패하면 `||`가 단락돼 ssh가 안 돌고, 그러면 이 파일이
  # 없어서 아래 sed가 죽는다(정지 절차가 2026-07-22에 겪은 그 자리와 같다).
  : > "$STAGE/backup.out"
  if ! scp -q -o StrictHostKeyChecking=accept-new -i "$SSH_KEY" \
        "$SCRIPT_DIR/blog-db-backup.sh" "ec2-user@$DNS:/tmp/blog-db-backup.sh" \
     || ! ssh -n -o StrictHostKeyChecking=accept-new -i "$SSH_KEY" "ec2-user@$DNS" \
        'sudo install -m 755 /tmp/blog-db-backup.sh /usr/local/bin/blog-db-backup.sh \
         && sudo /usr/local/bin/blog-db-backup.sh' > "$STAGE/backup.out" 2>&1; then
    cat "$STAGE/backup.out"
    echo "❌ 백업 실패 — 재빌드 안내를 내지 않고 멈춥니다." >&2
    echo "   코드는 이미 서버에 올라가 있지만 재빌드 전이라 도는 것은 아직 옛 이미지입니다." >&2
    echo "   사본 없이 alembic upgrade 를 돌리지 않으려는 의도적 중단입니다:" >&2
    echo "     - 다시 시도: $0" >&2
    echo "     - 백업 없이 강행: $0 --skip-backup" >&2
    exit 1
  fi
  cat "$STAGE/backup.out"

  BACKUP_KEY=$(sed -n 's/^BACKUP_KEY=//p' "$STAGE/backup.out" | tail -1)
  if [ -z "$BACKUP_KEY" ]; then
    echo "❌ 백업 스크립트가 키 이름을 알려주지 않았습니다 — 재빌드하지 마세요." >&2
    exit 1
  fi
  # `2>/dev/null` 로 뭉개지 않는다 — 권한 실패와 '객체가 없다'를 가르려면 사유가 필요하다.
  if ! head_out=$(aws s3api head-object --bucket "$BACKUP_BUCKET" --key "$BACKUP_KEY" \
                    --query 'ContentLength' --output text 2>&1); then
    echo "❌ 스크립트는 성공했는데 s3://$BACKUP_BUCKET/$BACKUP_KEY 를 확인하지 못했습니다." >&2
    printf '%s\n' "$head_out" | sed 's/^/   /' >&2
    echo "   '없다'인지 '못 봤다'인지는 위 사유로 판단하세요. 어느 쪽이든 재빌드하지 마세요." >&2
    exit 1
  fi
  echo "  s3://$BACKUP_BUCKET/$BACKUP_KEY ($head_out 바이트) — 사본 확인됨"
fi

# ── 6. 방아쇠는 사용자에게 ──────────────────────────────────────────────────
say "6/6 재빌드는 직접 실행하세요 (규칙7)"
cat <<CMD
  ssh -i $SSH_KEY ec2-user@$DNS \\
    'cd ~/blog && sudo docker compose -f docker-compose.prod.yml up -d --build'

  끝나면 **반드시** 검증하세요 — 보낸 것과 도는 것은 다릅니다:
    scripts/verify_deploy.sh
CMD
echo
echo "⚠️  이번 재빌드부터 PAYMENTS_REQUIRE_LIVE=true 가 반영됩니다 —"
echo "    토스 라이브 키가 없으면 결제 승인이 503으로 거부됩니다(공짜 Pro 차단, 의도된 동작)."

#!/usr/bin/env bash
# EC2 정지 절차: 주차 → 백업 → 사본 굳히기 → 정지 → 검증.
#
# 왜 스크립트인가 —
#   ① 순서가 안전에 직결된다. 주차(terraform apply)가 정지보다 '먼저' 와야 한다.
#      뒤집으면 IP가 반납된 뒤에도 오리진이 옛 ec2-<IP>...를 가리켜, 그 사이
#      /api/*가 그 IP를 새로 받은 제3자에게 간다(dangling origin).
#   ② 백업이 여기 있어야 실제로 돈다. 옛 cron(0 18 * * * = KST 03시)은 그 시각에
#      서버가 꺼져 있어 2026-07-20까지 단 한 번도 실행되지 않았다(그래서 제거했다).
#      DB가 바뀌는 건 EC2가 켜진 동안뿐이니, 백업의 올바른 자리는 '끄기 직전'이다.
#
# 왜 백업보다 주차가 먼저인가 (2026-07-22에 순서를 바꿨다) —
#   예전엔 백업 → 주차 순이었다. 그러면 pg_dump가 스냅샷을 뜬 뒤 주차까지의 몇 분
#   동안 들어온 글·댓글·결제가 **백업에 없는 채로** 서버가 꺼진다. 주차를 먼저 하면
#   /api/*가 fail closed가 되어 사용자 쓰기가 멈춘 뒤에 사본을 뜨게 된다.
#   (남는 쓰기는 1분마다 도는 자가점검 status_checks 정도 — 복원 훈련이 그 드리프트를
#    방향으로 분류해 보여준다.)
#   대가: 이 지점 이후 실패하면 사이트는 주차된 채(=/api 504) EC2만 켜져 있다.
#   그래서 실패 메시지에 주차를 푸는 명령을 같이 적어둔다.
#
# 사용:
#   scripts/stop_server.sh                # 주차 → 백업 → 정지
#   scripts/stop_server.sh --skip-backup  # 백업 건너뜀(DB 무변경이 확실할 때만)
#
# 백업이 실패하면 정지하지 않고 멈춘다 — 사본 없이 끄지 않기 위해서다.
# 이때 EC2는 켜진 채로 남으므로, 메시지를 보고 직접 판단해야 한다(크레딧 소모).

set -euo pipefail

# 인스턴스 ID는 태그로 찾는다 — 재건할 때마다 손으로 고치던 자리다(DR 결함 F5, lib/ec2.sh).
. "$(dirname "${BASH_SOURCE[0]}")/lib/ec2.sh"
INSTANCE_ID=$(resolve_instance_id)

BUCKET=blog-db-backups-181568979775
IMAGE_BUCKET=blogplafromops        # 업로드 이미지가 사는 곳(프론트와 같은 버킷)
SSH_KEY=~/.ssh/blog-key.pem
CF_URL=https://d2j66m9udyg9yq.cloudfront.net
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF_DIR="$(cd "$SCRIPT_DIR/../terraform" && pwd)"

STAGE=$(mktemp -d)
PARKED=false   # 주차를 이미 했는가 — 실패 안내를 낼지 판단한다

# 주차 이후 어느 단계에서 죽든 사이트는 /api 504인 채로 남는다. 예전엔 백업 분기에서만
# 안내했고, keep/ 복사·이미지 미러·stop-instances에서 죽으면 aws CLI 에러 한 줄만 보였다.
# (2026-07-22 코드검사에서 지적됨) 종료 훅에서 한 번만 안내한다.
cleanup() {
  rc=$?
  rm -rf "$STAGE"
  if [ "$rc" -ne 0 ] && [ "$PARKED" = true ]; then unpark_hint; fi
  exit "$rc"
}
trap cleanup EXIT

SKIP_BACKUP=false
case "${1:-}" in
  "")            ;;
  --skip-backup) SKIP_BACKUP=true ;;
  # 오타(--skip_backup 등)를 조용히 무시하면 의도와 다른 절차가 돈다.
  *) echo "알 수 없는 인자: $1" >&2; echo "사용법: $0 [--skip-backup]" >&2; exit 64 ;;
esac

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

# 주차한 뒤 실패했을 때 사용자가 되돌릴 수 있게 알려준다.
unpark_hint() {
  echo "   사이트는 지금 '주차' 상태입니다(/api/* 504). 계속 서비스하려면 주차를 푸세요:"
  echo "     terraform -chdir=$TF_DIR apply -var=\"backend_origin_dns=\$(aws ec2 describe-instances \\"
  echo "       --instance-ids $INSTANCE_ID \\"
  echo "       --query 'Reservations[0].Instances[0].PublicDnsName' --output text)\""
}

# terraform apply는 '그 시점의 전체 플랜'을 적용한다. 여기서 원하는 건 오리진 주차뿐인데,
# ec2.tf에 인스턴스를 교체(replace)하는 변경이 섞여 있으면 그것까지 실행된다. 루트 볼륨이
# delete_on_termination=true이고 pgdata가 그 위에 있으니 그건 곧 DB 소멸이고, 이 단계는
# 하필 백업보다 '먼저'다. 그래서 플랜을 먼저 뽑아 인스턴스 변경이 있으면 멈춘다.
park_origin() {
  local plan="$STAGE/park.tfplan"
  if ! terraform -chdir="$TF_DIR" plan -no-color -out="$plan" > "$STAGE/plan.txt" 2>&1; then
    cat "$STAGE/plan.txt"
    echo "❌ terraform plan 실패 — 아무것도 적용하지 않고 멈춥니다." >&2
    return 1
  fi
  # `terraform show | grep -q`로 받으면 grep이 첫 매치에서 파이프를 닫아 앞단이 EPIPE로
  # 죽고 pipefail이 그걸 실패로 잡는다. 파일로 받아서 검사한다.
  terraform -chdir="$TF_DIR" show -no-color "$plan" > "$STAGE/plan_show.txt"
  if grep -qE '^  # aws_instance\.' "$STAGE/plan_show.txt"; then
    echo "❌ 플랜에 EC2 인스턴스 변경이 들어 있습니다 — 정지 절차를 중단합니다." >&2
    grep -E '^  # aws_instance\.' "$STAGE/plan_show.txt" >&2
    echo "   인스턴스가 교체되면 루트 볼륨(pgdata)째 사라집니다. 직접 확인하세요:" >&2
    echo "     terraform -chdir=$TF_DIR plan" >&2
    return 1
  fi
  terraform -chdir="$TF_DIR" apply -no-color "$plan"
}

# ── 0. 상태 확인 ────────────────────────────────────────────────────────────
state=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].State.Name' --output text)
if [[ "$state" == "pending" ]]; then
  # 방금 켜는 중인 서버를 주차하면 올라오자마자 API가 죽는다. 정지 의도가 맞다면
  # running이 된 뒤에 다시 부르는 게 맞다.
  say "EC2가 'pending'(켜는 중)입니다. running이 된 뒤에 다시 실행하세요."
  exit 1
fi
if [[ "$state" != "running" ]]; then
  say "EC2가 이미 '$state' 상태입니다."
  # 켜져 있지 않아도 주차는 해둬야 한다(꺼진 채 오리진만 옛 주소인 경우 방지).
  say "오리진 주차만 확인합니다."
  park_origin
  exit 0
fi

DNS=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].PublicDnsName' --output text)

# ── 0. 끄기 전 검문 — 지금 아니면 못 재는 것 ────────────────────────────────
# 왜 여기인가: 저장소의 마크다운 편수와 DB의 연재 편수가 맞는지는 **서버가 켜져 있을 때만**
# 잴 수 있다. 어긋난 채로 끄면 "발행했다고 생각했는데 라이브는 옛 편수"가 며칠씩 간다 —
# 이 저장소는 실제로 그 상태를 여러 번 만들었고(#27은 마크다운이 아예 안 만들어진 채로
# 며칠, #30·#32는 발행이 다음 서버 켜는 날까지 밀렸다), 그때마다 다음 세션이 기록을 뒤져
# 알아냈다. 끄기 직전은 그걸 물어볼 마지막 순간이다.
#
# **막지는 않는다**(경고만). 일부러 안 발행하고 끄는 날이 있다 — 오늘 쓴 편을 내일 올리는
# 경우다. 정지를 못 하게 막으면 그게 더 나쁘다(서버가 켜진 채 밤을 넘긴다).
say "0/6 끄기 전 검문 — 마크다운 편수 vs DB 연재 편수"
# **저장소 쪽에도 '못 읽었다'를 둔다.** 예전에는 여기에 실패 가드가 없어서, 조회가 빈
# 출력을 내면 md_count 가 0이 되고 아래 검문이 "마크다운 0편인데 DB 연재는 N편입니다"라는
# 거짓 사실을 마지막 순간에 찍었다. 아래 DB 쪽은 같은 상황을 '못 읽었습니다'로 가르고
# 있었으므로, 한쪽만 정직한 상태였다(2026-08-31 검사).
# find 대신 셸 glob 을 쓴다 — 이 기계의 find 는 래퍼가 덮여 있고 실패해도 종료코드가 0이다.
shopt -s nullglob
md_files=("$(dirname "${BASH_SOURCE[0]}")/../content/devlog"/*.md)
shopt -u nullglob
md_count=${#md_files[@]}
db_count=$(ssh -n -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -i "$SSH_KEY" \
  "ec2-user@$DNS" 'cd ~/blog && sudo docker compose -f docker-compose.prod.yml exec -T db \
    psql -U postgres -d postgres -tAc "select count(*) from posts where series = '"'"'블로그 만들기'"'"';"' \
  2>/dev/null | tr -d '[:space:]' || true)
if [[ "$md_count" -eq 0 ]]; then
  echo "   --   저장소의 개발일지를 못 읽었습니다 — 검문을 건너뜁니다(정지는 계속합니다)."
elif [[ -z "$db_count" ]]; then
  echo "   --   DB를 못 읽었습니다 — 검문을 건너뜁니다(정지는 계속합니다)."
elif [[ "$md_count" == "$db_count" ]]; then
  echo "   OK   마크다운 $md_count편 = DB 연재 $db_count편"
else
  echo "   ⚠️   마크다운 ${md_count}편인데 DB 연재는 ${db_count}편입니다."
  echo "        미발행이 있으면 지금 올리세요: scripts/publish_devlog.sh <날짜>"
  echo "        (일부러 미룬 것이면 그대로 진행하면 됩니다)"
fi

# ── 1. 오리진 주차 (반드시 백업·정지보다 먼저) ──────────────────────────────
say "1/6 오리진 주차 — terraform apply (기본값 → S3 주차 주소)"
park_origin
PARKED=true
echo "   /api/*가 fail closed. 이제부터 들어오는 쓰기는 없습니다."

# ── 2. 백업 ─────────────────────────────────────────────────────────────────
NEW_KEY=""
if $SKIP_BACKUP; then
  say "2/6 백업 — 건너뜀(--skip-backup)"
else
  say "2/6 백업 — pg_dump → 검증 → S3"

  # 직전 백업의 크기를 미리 알아둔다. '올라갔다'만 보면 잘리거나 빈 덤프를 놓친다.
  # `2>/dev/null || echo None`으로 받으면 **AccessDenied·자격증명 만료까지 "None"이 되어**
  # 아래 급감 비교가 통째로 건너뛰어지고 "첫 백업 — 비교 대상 없음"이라는 정상 문구가 나간다.
  # 백업이 수십 개 쌓인 버킷에서 그 문구가 뜨는 게 그 상태다(2026-08-10 심층검사).
  # 호출 실패와 '정말 첫 백업'을 구분한다.
  if ! prev=$(aws s3api list-objects-v2 --bucket "$BUCKET" --prefix "blog-" \
      --query 'sort_by(Contents,&LastModified)[-1].Size' --output text 2>&1); then
    echo "   ⚠️  직전 백업 크기를 못 읽었습니다(권한·자격증명 확인) — 급감 검사를 건너뜁니다:"
    printf '%s\n' "$prev" | sed 's/^/       /'
    prev="UNREADABLE"
  fi

  # 저장소 판본을 매번 올려 덮어쓴다 — 서버에만 있던 시절엔 인스턴스를 새로
  # 만들면 백업 능력이 조용히 사라졌다(버전 관리도 안 됐다).
  # 파일을 미리 만들어 둔다. scp가 실패하면 `||`가 단락돼 ssh가 안 돌고, 그러면 이 파일이
  # 없어서 아래 cat이 죽는다 → set -e로 스크립트가 끝나 실패 안내가 한 줄도 안 나왔다
  # (2026-07-22 코드검사에서 발견). scp 실패는 흔하다(막 켠 인스턴스, sshd 준비 전 등).
  : > "$STAGE/backup.out"
  if ! scp -o StrictHostKeyChecking=no -i "$SSH_KEY" \
        "$SCRIPT_DIR/blog-db-backup.sh" "ec2-user@$DNS:/tmp/blog-db-backup.sh" \
     || ! ssh -n -o StrictHostKeyChecking=no -i "$SSH_KEY" "ec2-user@$DNS" \
        'sudo install -m 755 /tmp/blog-db-backup.sh /usr/local/bin/blog-db-backup.sh \
         && sudo /usr/local/bin/blog-db-backup.sh' > "$STAGE/backup.out" 2>&1; then
    cat "$STAGE/backup.out"
    say "❌ 백업 실패 — 정지하지 않고 멈춥니다. EC2는 아직 켜져 있습니다."
    echo "   사본 없이 끄지 않으려는 의도적 중단입니다. 원인을 보고 판단하세요:"
    echo "     - 다시 시도: $0"
    echo "     - 백업 없이 강행: $0 --skip-backup"
    exit 1
  fi
  cat "$STAGE/backup.out"

  # '스크립트가 성공했다'와 '그 객체가 S3에 있다'는 다르다 — 이름으로 직접 확인한다.
  # (예전엔 목록 줄 수가 늘었는지만 봤는데, 그건 다른 키가 늘어도 통과한다.)
  NEW_KEY=$(sed -n 's/^BACKUP_KEY=//p' "$STAGE/backup.out" | tail -1)
  if [ -z "$NEW_KEY" ]; then
    say "❌ 백업 스크립트가 키 이름을 알려주지 않았습니다 — 정지하지 않습니다."
    exit 1
  fi

  if ! size=$(aws s3api head-object --bucket "$BUCKET" --key "$NEW_KEY" \
                --query 'ContentLength' --output text 2>/dev/null); then
    say "❌ 스크립트는 성공했는데 S3에 $NEW_KEY 가 없습니다 — 정지하지 않습니다."
    echo "   버킷을 직접 확인하세요: aws s3 ls s3://$BUCKET/"
    exit 1
  fi

  # 크기 급감은 '성공했지만 내용이 빠진' 덤프의 신호다. 절반 밑이면 사람이 봐야 한다.
  # (서버 쪽은 절대 하한만 본다 — 목록 읽기 권한이 일부러 없어서 비교를 못 한다.)
  if [ "$prev" != "None" ] && [ "$prev" -gt 0 ] 2>/dev/null; then
    if [ $((size * 2)) -lt "$prev" ]; then
      say "❌ 새 백업이 직전보다 크게 작습니다($prev → $size 바이트) — 정지하지 않습니다."
      echo "   글을 대량 삭제한 게 아니라면 덤프가 잘렸을 수 있습니다. 직접 확인하세요."
      echo "   확인 후 강행: $0 --skip-backup"
      exit 1
    fi
    echo "   크기 $size 바이트 (직전 $prev — 정상 범위)"
  else
    if [ "$prev" = "UNREADABLE" ]; then
      echo "   크기 $size 바이트 (직전과 비교하지 못했습니다 — 위 경고 참고)"
    else
      echo "   크기 $size 바이트 (첫 백업 — 비교 대상 없음)"
    fi
  fi
fi

# ── 3. 마지막 보루 굳히기 ───────────────────────────────────────────────────
# 왜 이게 따로 필요한가: 날짜별 덤프는 180일이 지나면 lifecycle이 지운다. 백업이
# 도는 시점이 '서버를 끌 때'뿐이라, 한동안 서버를 안 켜면 마지막 백업만 남아 있다가
# 그것마저 만료돼 **백업이 0개가 되는** 구간이 생긴다(옛 30일 설정에선 더 짧았다).
# keep/ 접두사는 만료 규칙 대상이 아니다 → 여기에 최신 덤프를 복사해 두면 얼마나
# 오래 손을 놓든 최소 한 벌은 항상 남는다. 버저닝이 켜져 있어 덮어써도 이력이 남는다.
# 서버가 아니라 여기서 하는 이유: EC2 역할은 `blog-*`에만 쓸 수 있다(탈취 대비).
# 3·4단계는 '있으면 좋은 사본'이지 안전한 종료의 전제조건이 아니다 — 이 시점엔 백업이
# 이미 S3에 올라가 검증까지 끝났다. 그런데 처음엔 여기서 실패하면 set -e로 스크립트가
# 끝나 **인스턴스가 안 꺼지고 계속 과금**됐다(2026-07-22 코드검사에서 내가 만든 결함).
# 자리를 비운 사이라면 더 나쁘다. 그래서 경고만 하고 정지는 진행한다.
if [ -n "$NEW_KEY" ]; then
  say "3/6 마지막 보루 — keep/latest.sql.gz 갱신 (만료되지 않는 자리)"
  if aws s3 cp "s3://$BUCKET/$NEW_KEY" "s3://$BUCKET/keep/latest.sql.gz" --only-show-errors; then
    echo "   $NEW_KEY → keep/latest.sql.gz"
  else
    echo "   ⚠️  승격 실패 — 정지는 계속합니다. 나중에 직접:"
    echo "      aws s3 cp s3://$BUCKET/$NEW_KEY s3://$BUCKET/keep/latest.sql.gz"
  fi
else
  say "3/6 마지막 보루 — 새 덤프가 없어 건너뜀"
fi

# ── 4. 이미지 사본 + 시크릿 사본 확인 ───────────────────────────────────────
# 이미지는 DB 덤프에 안 들어간다. 2026-06-26에 S3로 옮긴 뒤로 인스턴스 교체에는
# 안전해졌지만, 프론트 배포와 같은 버킷이라 `s3 sync --delete`의 사정권 안에 있다
# (지금은 deploy.yml의 `--exclude "uploads/*"` 한 줄이 유일한 방어선이다).
# 백업 버킷으로 미러해 두면 그 실수와 무관한 두 번째 사본이 생긴다.
# --delete를 쓰지 않는 게 핵심: 원본에서 지워진 이미지도 사본에는 남는다.
say "4/6 이미지 사본 + 시크릿 사본"
if ! aws s3 sync "s3://$IMAGE_BUCKET/uploads/" "s3://$BUCKET/uploads/" --only-show-errors; then
  echo "   ⚠️  이미지 미러 실패 — 정지는 계속합니다. 나중에 직접:"
  echo "      aws s3 sync s3://$IMAGE_BUCKET/uploads/ s3://$BUCKET/uploads/"
fi
# `aws s3 ls`는 객체가 하나도 없으면 종료코드 1이다 — pipefail에 걸려 죽지 않게 감싼다.
mirrored=$( { aws s3 ls "s3://$BUCKET/uploads/" --recursive || true; } | wc -l)
echo "   이미지 사본 $mirrored 개 (s3://$BUCKET/uploads/)"

# .env는 서버에만 있고 백업 대상이 아니다. 특히 LLM_ENCRYPTION_KEY를 잃으면
# DB를 완벽히 복원해도 BYOK 암호문을 영원히 못 푼다 → 사본 유무만 확인하고 알린다.
# 여기서 정지를 막지는 않는다(사람이 손으로 해결해야 하는 일이라 막아도 못 고친다).
"$SCRIPT_DIR/env_escrow.sh" check || true

# ── 4-B. 디스크 회수 + 잔량 보고 ────────────────────────────────────────────
# 왜 배포가 아니라 여기인가 — **배포는 가끔 하고 정지는 매번 한다.** '매일 03시 cron'이
# 서버가 꺼져 있어 4개월간 0건이던 것과 같은 이유로, 청소를 배포 경로에만 두면 배포를
# 안 한 달에는 한 번도 안 돈다. 게다가 로그는 배포와 무관하게 쌓인다. 그리고
# deploy_backend.sh는 규칙7 때문에 `up -d --build` **앞에서** 끝나므로, 그 시점엔 이번에
# 버려질 이미지가 아직 존재하지도 않는다 — 거기서 지우면 항상 한 배포 뒤처진다.
#
# 백업이 S3에 올라가 검증까지 끝난 뒤다. 청소가 백업을 방해할 수 있는 순서는 안 만든다.
# 태그 없는(dangling) 이미지만 지운다 — `-a`는 안 쓴다(다음 재빌드가 t2.micro에서 느려진다).
# 3·4단계와 같은 등급이다: **실패해도 정지는 계속한다.** 여기서 죽으면 인스턴스가 안 꺼지고
# 계속 과금된다(2026-07-22에 실제로 그랬다).
#
# `df`를 같이 찍는 이유: pgdata가 이 볼륨 위에 살고 루트 볼륨 크기가 terraform에 없다.
# 매번 사람 눈앞에 숫자를 남겨 추세를 볼 수 있게 한다. (2026-08-10 심층검사)
say "4-B/6 디스크 회수 + 잔량"
if out=$(ssh -n -o StrictHostKeyChecking=no -o ConnectTimeout=15 \
           -o ServerAliveInterval=15 -o ServerAliveCountMax=4 \
           -i "$SSH_KEY" "ec2-user@$DNS" \
           'sudo docker image prune -f && sudo docker builder prune -f; df -h --output=pcent,avail / | tail -1' 2>&1); then
  printf '%s\n' "$out" | sed 's/^/   /'
else
  echo "   ⚠️  정리 실패 — 정지는 계속합니다: $out"
fi

# ── 5. 정지 ─────────────────────────────────────────────────────────────────
say "5/6 EC2 정지"
aws ec2 stop-instances --instance-ids "$INSTANCE_ID" \
  --query 'StoppingInstances[0].CurrentState.Name' --output text
aws ec2 wait instance-stopped --instance-ids "$INSTANCE_ID"

# ── 6. 검증 ─────────────────────────────────────────────────────────────────
say "6/6 검증"
# 예전엔 세 값을 echo로 **출력만** 하고 비교가 없었다. 그래서 `/api/status (504 기대): 200`
# 바로 다음 줄에 "완료 — …(정상)"이라는 고정 문구가 찍혔고, EIP가 1개 남아 과금돼도
# 종료코드는 0이었다(2026-08-10 심층검사). 검사인 척하는 검사였다. 실제로 판정하게 한다.
# 여기서 실패해도 인스턴스는 이미 멈췄으므로 **정지를 되돌리지 않는다** — 사람에게 알리는 게
# 목적이라 종료코드로만 표시한다.
verify_rc=0
aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].{State:State.Name,PublicIp:PublicIpAddress}' --output json

eips=$(aws ec2 describe-addresses --query 'length(Addresses)' --output text)
if [ "$eips" = "0" ]; then
  echo "   OK   EIP 0개 (정지 중 과금 없음)"
else
  echo "   ❌   EIP가 ${eips}개 남아 있습니다 — 인스턴스가 꺼져도 과금됩니다."
  verify_rc=1
fi

# `|| echo 000` 을 쓰지 않는다 — curl 은 실패해도 -w 로 이미 000 을 찍으므로 그 관용구는
# 출력을 `000000` 으로 만들고, '못 봤다' 판정을 도달 불가능하게 한다(2026-08-31 검사).
front=$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 "$CF_URL/" || true)
if [ "$front" = "200" ]; then
  echo "   OK   프론트 홈 200 (정적 사이트는 서버와 무관하게 살아 있다)"
else
  echo "   ❌   프론트 홈이 $front 입니다 (200 기대). 000이면 curl 자체가 실패한 것입니다."
  verify_rc=1
fi

api=$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$CF_URL/api/status" || true)
if [ "$api" = "504" ]; then
  echo "   OK   /api/status 504 — 주차가 fail closed로 동작합니다(정상)"
else
  echo "   ❌   /api/status가 $api 입니다 (504 기대)."
  echo "        200이면 주차가 안 걸렸거나 다른 오리진이 응답하는 것이고,"
  echo "        403이면 오리진 시크릿 불일치입니다(RECOVERY.md 참고)."
  verify_rc=1
fi

if [ "$verify_rc" -eq 0 ]; then
  say "완료 — 정지·주차·과금 검증 전부 통과."
else
  say "⚠️  정지는 됐지만 위 ❌를 확인하세요."
fi
echo "다음에 복원까지 확인하려면: scripts/restore_drill.sh (EC2를 다시 켠 뒤)"
exit "$verify_rc"

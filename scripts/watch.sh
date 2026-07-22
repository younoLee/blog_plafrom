#!/usr/bin/env bash
# 감시 — "사람이 안 했다"와 "조용히 깨졌다"를 잡는다.
#
# 왜 필요한가 (이 저장소가 같은 병으로 세 번 당했다) —
#   · 2026-07-20: cron 백업이 서버 꺼진 시각에 걸려 **4개월간 0건** 실행. 우연히 발견.
#   · 2026-07-22: 이미지 업로드가 IAM 프로파일 교체로 AccessDenied. 우연히 발견.
#   · 2026-07-22: SES 프로덕션 액세스가 **거부**된 지 4주. 아무도 몰랐고,
#     그동안 제3자는 가입해도 인증 메일을 못 받았다.
#   셋 다 "알려주는 장치가 없다"는 같은 원인이다. 계정에 CloudWatch 알람·SNS·
#   CloudTrail이 전부 0개이고, 살아 있는 감시는 월 예산 알림 하나뿐이었다.
#
# 왜 서버 안이 아니라 밖에서 도는가 —
#   앱의 자가점검(`services/status.py`)은 `backend_ok`가 하드코딩 `True`다("이 코드가
#   도는 것 자체가 백엔드 동작"). 27,506번 중 실패 0건인 게 그 증거다. 프로세스 안에서
#   도니 죽으면 기록 자체가 없고(회색), CloudFront·오리진은 아예 못 본다.
#   그래서 이 스크립트는 **바깥에서** 공개 주소를 찌른다.
#
# 사용:
#   scripts/watch.sh          # 로컬에서 수동 실행
#   .github/workflows/watch.yml 이 매시 자동 실행 (실패하면 GitHub이 메일로 알림)
#
# 종료코드: 문제가 하나라도 있으면 1. Actions가 빨간불이 되고 알림이 간다.
#
# **경고도 종료코드에 넣는다.** 알림 경로가 'Actions 실패 메일' 하나뿐이라,
# 종료코드에 안 들어가는 경고는 아무에게도 도달하지 않는다 — 초록으로 끝나고
# 신호가 0건이다. 그러면 "6시간째 켜둔 채 과금 중"이나 "감시가 SES를 못 읽는 중"
# 같은, 정확히 조용히 방치되는 유형이 다시 조용해진다.
# 메일 보낼 가치가 없는 항목이면 애초에 경고가 아니라 정보(`--`)여야 한다.
#
# `set -e`를 쓰지 않는다 — 첫 실패에서 멈추면 나머지 점검 결과를 못 본다.
# 문제를 모아서 한 번에 보여주는 게 이 스크립트의 목적이다.
set -uo pipefail

INSTANCE_ID=i-06da19f44d1f38eff
BUCKET=blog-db-backups-181568979775
IMAGE_BUCKET=blogplafromops
CF_URL=https://d2j66m9udyg9yq.cloudfront.net
REGION=ap-northeast-2

# 켠 직후에는 아직 오리진을 안 풀었을 수 있다. 그 창을 오탐으로 세지 않는다.
GRACE_MIN=20
# 이만큼 켜져 있으면 '끄는 걸 잊었다'로 본다(꺼야 과금이 멈춘다).
MAX_UPTIME_H=6
# 백업이 이만큼 오래되면 본다. 서버를 안 켰으면 정상일 수 있지만 확인은 필요하다.
MAX_BACKUP_AGE_D=30

FAIL=0
WARN=0
fail() { printf '❌ %s\n' "$*"; FAIL=$((FAIL + 1)); }
warn() { printf '⚠️  %s\n' "$*"; WARN=$((WARN + 1)); }
ok()   { printf '✅ %s\n' "$*"; }

now=$(date -u +%s)

# ── 1. EC2가 켜져 있는가, 켜져 있다면 공개 API가 실제로 살아 있는가 ──────────
# 이 조합이 핵심이다. '꺼져 있음'은 정상이고 '켜져 있는데 API가 죽음'이 이상이다.
# 지금까지 이 상태(EC2 running + 오리진 주차)가 몇 시간씩 방치돼도 아무도 몰랐다.
read -r state launch <<EOF
$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --region "$REGION" \
   --query 'Reservations[0].Instances[0].[State.Name,LaunchTime]' --output text 2>/dev/null)
EOF

if [ -z "${state:-}" ]; then
  fail "EC2 상태를 못 읽었다 (권한이나 인스턴스 ID 확인: $INSTANCE_ID)"
elif [ "$state" = "terminated" ] || [ "$state" = "shutting-down" ]; then
  # 이건 '꺼짐'이 아니라 '사라짐'이다. 루트 볼륨이 delete_on_termination이라 DB도 같이 간다.
  fail "EC2가 '$state' — 인스턴스가 삭제되고 있거나 삭제됐다. RECOVERY.md 시나리오 B."
elif [ "$state" != "running" ]; then
  ok "EC2 '$state' — 꺼져 있는 건 정상(필요할 때만 켜는 서버)"
else
  # date가 실패하면 산술식이 문법 오류가 되어 변수가 대입조차 안 되고,
  # 그 뒤 `set -u`가 스크립트를 즉시 끝내 나머지 검사(이미지·SES)가 통째로 날아간다.
  # 종료코드는 1이라 알림은 가지만 진단이 엉뚱해지므로 먼저 파싱을 검증한다.
  if ! launch_s=$(date -u -d "${launch:-}" +%s 2>/dev/null) || [ -z "${launch:-}" ]; then
    fail "LaunchTime을 해석하지 못했다(값: '${launch:-비어있음}')"
    launch_s=$now
  fi
  up_s=$(( now - launch_s ))
  up_h=$(( up_s / 3600 ))
  body=$(curl -s --max-time 45 -w $'\n%{http_code}' "$CF_URL/api/status" || true)
  code=${body##*$'\n'}
  body=${body%$'\n'*}

  if [ "$code" = "200" ]; then
    # 200만 보면 안 된다 — 앱은 떠 있는데 DB나 메일이 죽은 경우를 놓친다.
    # status.py의 mail 점검을 STARTTLS+AUTH로 제대로 고쳐놨는데 바깥에서 그 결과를
    # 안 읽으면 두 장치가 이어지지 않는다.
    down=""
    for svc in backend database mail; do
      case "$body" in
        *"\"$svc\":\"ok\""*) ;;
        *) down="$down $svc" ;;
      esac
    done
    if [ -n "$down" ]; then
      fail "공개 API는 200인데 내부 상태가 비정상:$down"
      echo "     응답: $body"
    else
      ok "EC2 running ${up_h}시간 · 공개 /api/status 200 (backend·database·mail 전부 ok)"
    fi
  elif [ "$up_s" -lt $(( GRACE_MIN * 60 )) ]; then
    ok "EC2 running (막 켬, ${GRACE_MIN}분 유예 중) · /api/status $code"
  else
    fail "EC2는 running인데 공개 /api/status가 $code — 오리진이 주차돼 있거나 백엔드가 죽었다."
    echo "     서버 안에서는 정상으로 보일 수 있다(자가점검은 CloudFront를 못 본다)."
    echo "     주차 해제: terraform -chdir=terraform apply -var=\"backend_origin_dns=\$(aws ec2 describe-instances \\"
    echo "       --instance-ids $INSTANCE_ID --query 'Reservations[0].Instances[0].PublicDnsName' --output text)\""
  fi

  if [ "$up_h" -ge "$MAX_UPTIME_H" ]; then
    warn "EC2가 ${up_h}시간째 켜져 있다 — 끄는 걸 잊었는지 확인(scripts/stop_server.sh)."
  fi
fi

# ── 2. 백업이 실제로 쌓이고 있는가 ──────────────────────────────────────────
latest=$(aws s3api list-objects-v2 --bucket "$BUCKET" --prefix "blog-" --region "$REGION" \
  --query 'sort_by(Contents,&LastModified)[-1].[Key,LastModified]' --output text 2>/dev/null)
if [ -z "$latest" ] || [ "$latest" = "None" ]; then
  fail "백업이 하나도 없다: s3://$BUCKET/"
else
  key=${latest%%$'\t'*}
  mod=${latest##*$'\t'}
  if ! mod_s=$(date -u -d "$mod" +%s 2>/dev/null); then
    fail "백업 시각을 해석하지 못했다(값: '$mod')"
    mod_s=$now
  fi
  age_d=$(( (now - mod_s) / 86400 ))
  if [ "$age_d" -ge "$MAX_BACKUP_AGE_D" ]; then
    fail "최신 백업이 ${age_d}일 전이다($key). 백업은 정지 절차 때만 도니, 그동안 서버를 안 껐거나 백업이 깨졌다."
  else
    ok "최신 백업 ${age_d}일 전 — $key"
  fi
fi

# 만료되지 않는 마지막 보루. 날짜별 덤프는 180일에 지워지므로 이게 없으면
# 오래 손을 놓았을 때 백업이 0개가 되는 구간이 생긴다.
if aws s3api head-object --bucket "$BUCKET" --key "keep/latest.sql.gz" --region "$REGION" >/dev/null 2>&1; then
  ok "만료 안 되는 사본 있음 — keep/latest.sql.gz"
else
  fail "keep/latest.sql.gz 가 없다. 정지 절차가 만들지만, 없으면 장기 방치 시 백업이 전멸할 수 있다."
fi

# ── 3. 이미지 사본 ──────────────────────────────────────────────────────────
# 이미지는 DB 덤프에 안 들어가고, 프론트 배포(`s3 sync --delete`)와 같은 버킷에 산다.
# `aws s3 ls`는 결과가 0건이면 종료코드 1이라 감싸야 한다.
# `aws s3 ls ... || true`로 받으면 안 된다 — 그건 '0건이면 exit 1'만 삼키는 게 아니라
# AccessDenied·NoSuchBucket·자격증명 만료까지 전부 삼킨다. 그러면 개수가 0이 되어
# **"권한이 없어서 못 봤다"가 "볼 게 없다"로 보고**된다(초록). 이 저장소가 07-22에
# 당한 IAM 드리프트와 같은 계열이라, 호출 실패와 0건을 구분한다.
count_objects() {  # $1=버킷 $2=접두사 → 개수를 출력, 호출 실패면 non-zero
  aws s3api list-objects-v2 --bucket "$1" --prefix "$2" \
    --query 'length(Contents || `[]`)' --output text
}
if ! src_n=$(count_objects "$IMAGE_BUCKET" "uploads/"); then
  fail "원본 이미지 버킷을 읽지 못했다(s3://$IMAGE_BUCKET/uploads/) — 권한이나 자격증명 확인"
  src_n=-1
fi
if ! dst_n=$(count_objects "$BUCKET" "uploads/"); then
  fail "이미지 사본 버킷을 읽지 못했다(s3://$BUCKET/uploads/) — 권한이나 자격증명 확인"
  dst_n=-1
fi
if [ "$src_n" -lt 0 ] || [ "$dst_n" -lt 0 ]; then
  : # 위에서 이미 fail 처리
elif [ "$src_n" -eq 0 ]; then
  ok "업로드 이미지 없음(확인할 것 없음)"
elif [ "$dst_n" -ge "$src_n" ]; then
  ok "이미지 사본 $dst_n개 (원본 $src_n개)"
else
  warn "이미지 사본이 부족하다(원본 $src_n / 사본 $dst_n). 정지 절차가 미러하지만 수동으로도 가능:"
  echo "     aws s3 sync s3://$IMAGE_BUCKET/uploads/ s3://$BUCKET/uploads/"
fi

# ── 4. 메일이 실제로 나갈 수 있는 상태인가 ──────────────────────────────────
# 앱의 `mail_ok`는 SMTP 포트에 TCP 연결만 해봐서, 샌드박스 때문에 제3자에게 메일이
# 한 통도 안 가는 4주 동안 25,826번 "정상"이라고 답했다. 그 구멍이 여기다.
prod_access=$(aws sesv2 get-account --region "$REGION" --query 'ProductionAccessEnabled' --output text 2>/dev/null)
if [ "$prod_access" = "True" ]; then
  ok "SES 프로덕션 액세스 활성 — 누구에게나 발송 가능"
elif [ -z "$prod_access" ]; then
  # '못 읽었다'를 경고로 두면 안 된다 — 감시가 눈이 먼 상태를 초록으로 보고하게 된다.
  # ses:GetAccount 권한이 사라지면 SES 샌드박스를 4주간 아무도 몰랐던 그 상태로
  # 정확히 되돌아가면서 알림은 한 통도 안 간다. EC2 읽기 실패도 이미 fail이다.
  fail "SES 상태를 못 읽었다 — 감시가 눈이 먼 상태다(권한 확인: ses:GetAccount)"
else
  fail "SES가 아직 샌드박스다 → 검증된 주소 외에는 인증·비번재설정 메일이 안 간다."
  echo "     가입자는 성공 응답만 받고 메일을 못 받으며, 24시간 뒤 계정이 삭제된다."
  echo "     조치: docs/ses-production-access.md (콘솔에서 재신청해야 한다)"
fi

# ── 요약 ────────────────────────────────────────────────────────────────────
echo
if [ "$FAIL" -eq 0 ] && [ "$WARN" -eq 0 ]; then
  echo "== 이상 없음 =="
else
  echo "== 실패 $FAIL건 / 경고 $WARN건 =="
fi
[ "$FAIL" -eq 0 ] && [ "$WARN" -eq 0 ]

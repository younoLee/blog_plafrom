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
#   .github/workflows/watch.yml 이 예약 실행 (실패하면 GitHub이 메일로 알림)
#   ⚠️ **매시가 아니다.** cron 은 '17 * * * *' 이지만 GitHub 이 지연·누락시켜서
#      실측은 기대치의 24~37%다(2026-09-04, 간격 중앙값 1.4~4.4시간·최대 13.3시간).
#      숫자와 근거는 watch.yml 의 schedule 주석에. 이 파일이 "매시 초록"이라고
#      쓴 자리들도 같은 뜻으로 읽을 것 — 실제로는 그보다 드물게 본다.
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

# 인스턴스 ID는 태그로 찾는다 — 재건할 때마다 손으로 고치던 자리다(DR 결함 F5, lib/ec2.sh).
# 여기서 죽지 않는다(`|| INSTANCE_ID=""`). 조회가 실패해도 나머지 점검(백업·이미지·SES·
# 예산·알람)은 인스턴스와 무관하게 볼 수 있고, 이 스크립트의 목적은 문제를 모아 보여주는 것이다.
# 빈 값은 아래 1번 점검이 실패로 잡는다.
. "$(dirname "${BASH_SOURCE[0]}")/lib/ec2.sh"
INSTANCE_ID=$(resolve_instance_id) || INSTANCE_ID=""

ACCOUNT_ID=181568979775
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

# SES 샌드박스를 '정상 기대치'로 볼 것인가.
#
# true = 샌드박스인 게 의도다. **2026-08-04에 확정됐다** — 프로덕션 액세스를 두 번
#        신청해 두 번 거절당했고(사유 비공개), 더 신청하지 않기로 종결했다.
#        (docs/ses-production-access.md) 초대제라 수신자가 유한하고 그 주소들이 전부
#        검증돼 있어 샌드박스로 정상 동작한다. **이 값은 이제 바꿀 일이 없다.**
#        원래 근거(2026-07-22): 봇 가입을 막을 장치(캡차)가 없다. 그 상태를 매시간
#        실패로 알리면 영구 빨간불이 되고, 영구 빨간불은 아무도 안 보는 신호가 된다.
#        대신 **상태가 바뀌면** 알린다 — 승인됐거나 누가 설정을 건드렸다는 뜻이니
#        그것도 알아야 할 변화다.
# false = 프로덕션이 정상 기대치. 캡차를 붙여 가입을 열기로 하면 이걸 false로 바꾼다.
#
# ⚠️ 봇 위험을 다시 판단할 때 참고: 인증을 마쳐도 role은 pending에 머물고
#    글쓰기·업로드·AI 초안은 전부 require_writer로 잠겨 있다. 댓글은 애초에
#    비로그인도 가능하다(IP당 20/시간). 즉 봇이 계정을 만들어 얻는 건 users 테이블의
#    행뿐이고, 미인증이면 24시간 뒤 cleanup이 지운다.
SES_SANDBOX_EXPECTED=true

FAIL=0
WARN=0
# curl 의 상태코드를 안전하게 받는다.
#
# **`curl … -w '%{http_code}' || echo 000` 은 틀린 관용구다.** curl 은 연결에 실패해도
# -w 로 이미 `000` 을 찍고 종료코드만 0이 아니다. 거기에 `|| echo 000` 을 붙이면 출력이
# `000000` 이 되어 `[ "$code" = "000" ]` 이 영원히 거짓이 된다. 그러면 '못 봤다'로 가려던
# 분기가 도달 불가능해지고, 네트워크 실패가 '사이트가 깨졌다'는 **거짓 사실**로 나간다.
# 2026-08-31에 1-B 절을 만들면서 그 관용구를 그대로 썼고, 같은 날 검사에서 재현됐다.
# 못 본 것과 죽은 것을 가르려고 만든 자리가 정확히 그 구분을 못 하고 있었다.
http_code() {
  local out
  out=$(curl -s -o /dev/null -w '%{http_code}' --max-time "${2:-20}" "$1" || true)
  printf '%s' "${out:-000}"
}

fail() { printf '❌ %s\n' "$*"; FAIL=$((FAIL + 1)); }
warn() { printf '⚠️  %s\n' "$*"; WARN=$((WARN + 1)); }
ok()   { printf '✅ %s\n' "$*"; }

now=$(date -u +%s)

# ── 1. EC2가 켜져 있는가, 켜져 있다면 공개 API가 실제로 살아 있는가 ──────────
# 이 조합이 핵심이다. '꺼져 있음'은 정상이고 '켜져 있는데 API가 죽음'이 이상이다.
# 지금까지 이 상태(EC2 running + 오리진 주차)가 몇 시간씩 방치돼도 아무도 몰랐다.
read -r state launch <<EOF
$(aws ec2 describe-instances --instance-ids "${INSTANCE_ID:-none}" --region "$REGION" \
   --query 'Reservations[0].Instances[0].[State.Name,LaunchTime]' --output text 2>/dev/null)
EOF

if [ -z "$INSTANCE_ID" ]; then
  # 태그 조회가 실패했다. 위 stderr에 이유가 이미 찍혔다(권한 / 0건 / 여러 건).
  fail "Name=$INSTANCE_NAME_TAG 태그로 인스턴스를 못 찾았다 — 위 조회 실패 메시지 참고."
elif [ -z "${state:-}" ]; then
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
    # disk 추가(2026-08-10): pgdata가 루트 볼륨에 사는데 남은 용량을 보는 장치가
    # 저장소 전체에 없었다. 감시는 AWS 밖에서 도니 EC2에 닿을 수 없고, 이 응답이
    # 서버 안을 보는 유일한 창이다. 앱은 퍼센트가 아니라 임계 초과 1비트만 낸다.
    for svc in backend database mail disk; do
      case "$body" in
        *"\"$svc\":\"ok\""*) ;;
        *) down="$down $svc" ;;
      esac
    done
    # stale 추가(2026-08-27): 위 네 값이 전부 ok 인데 **그 값이 언제 잰 것인지**를
    # 여기서 안 봤다. 08-27 카오스 훈련이 DB를 얼렸을 때 /api/status 가 884초 동안
    # database=ok 를 내보냈다 — 레코더 스레드가 같이 얼어 값이 나이를 안 먹었다.
    # 그 상태에서 이 검사는 "전부 ok"로 초록을 냈을 것이다. 초록으로 끝나는 감시는
    # 없는 것과 같다(2026-07-22 "경고가 아무에게도 안 갔다").
    #
    # **임계는 여기서 정하지 않는다.** 서버가 판정해서 stale 로 실어 보낸다
    # (backend services/status.py 의 STALE_AFTER). 화면과 감시가 각자 정하면 같은
    # 순간에 다른 답을 내는데, 이 저장소는 디스크 임계에서 이미 그 모양을 겪었다.
    #
    # 옛 백엔드는 이 키를 안 보낸다. 없으면 판정하지 않는다 — 배포 순서 때문에
    # 거짓 빨간불이 뜨는 창을 만들지 않는다(프론트의 disk 카드와 같은 규약).
    case "$body" in
      *'"stale":true'*)
        age=$(printf '%s' "$body" | sed -n 's/.*"checked_age_seconds":\([0-9]*\).*/\1/p')
        fail "공개 /api/status 는 200인데 그 값이 ${age:-?}초 전 것이고 갱신이 멈췄다 (stale=true)."
        echo "     레코더 스레드가 멈췄거나 얼었다. 지금 초록인 값은 얼기 직전 값일 수 있다."
        ;;
    esac

    if [ -n "$down" ]; then
      fail "공개 API는 200인데 내부 상태가 비정상:$down"
      echo "     응답: $body"
    else
      ok "EC2 running ${up_h}시간 · 공개 /api/status 200 (backend·database·mail·disk 전부 ok)"
    fi
  elif [ "$up_s" -lt $(( GRACE_MIN * 60 )) ]; then
    ok "EC2 running (막 켬, ${GRACE_MIN}분 유예 중) · /api/status $code"
  else
    fail "EC2는 running인데 공개 /api/status가 $code — 오리진 주차·백엔드 사망·시크릿 불일치 중 하나다."
    echo "     서버 안에서는 정상으로 보일 수 있다(자가점검은 CloudFront를 못 본다)."
    if [ "$code" = "403" ]; then
      # 2026-07-28에 오리진 공유 시크릿을 넣으면서 생긴 세 번째 원인. 이걸 안 적어두면
      # 주차 해제부터 시도하게 되는데, 이미 풀려 있어서 아무것도 안 바뀐다.
      echo "     403이면 **오리진 공유 시크릿 불일치**가 가장 유력하다 —"
      echo "       CloudFront가 붙이는 X-Origin-Secret 과 서버 .env 의 ORIGIN_SECRET 이 다르다."
      echo "       가장 흔한 원인: terraform.tfvars 없이 apply 해서 헤더가 빠진 것."
      echo "       확인: aws cloudfront get-distribution-config --id E1438IL9CSVBS4 \\"
      echo "               --query 'DistributionConfig.Origins.Items[?Id==\`api-backend\`].CustomHeaders'"
      echo "       자세한 절차는 RECOVERY.md 의 origin_secret 항목."
    fi
    echo "     주차 해제: terraform -chdir=terraform apply -var=\"backend_origin_dns=\$(aws ec2 describe-instances \\"
    echo "       --instance-ids $INSTANCE_ID --query 'Reservations[0].Instances[0].PublicDnsName' --output text)\""
  fi

  if [ "$up_h" -ge "$MAX_UPTIME_H" ]; then
    warn "EC2가 ${up_h}시간째 켜져 있다 — 끄는 걸 잊었는지 확인(scripts/stop_server.sh)."
  fi
fi

# ── 1-B. 공개 사이트가 서버와 무관하게 열리는가 ─────────────────────────────
# 이 서버는 대부분 꺼져 있다. 그런데 위 1번 검사의 curl 은 `running` 분기 안에만 있어서,
# **가장 긴 시간대인 절전 중에는 공개 주소를 아무도 안 찔렀다.** 이 사이트가 가장 자랑하는
# 성질이 '서버가 꺼져 있어도 글이 읽힌다'인데 그 성질을 지키는 검사가 0개였던 셈이다.
#
# 그 자리에는 CloudFront Function 두 개(SPA 라우팅·CSP 주입)와 S3 정적 호스팅이 걸려 있고,
# 하나만 깨져도 화면이 통째로 죽는다. 그리고 하필 그 주소가 이력서에 적히는 주소다.
# `/api/*` 는 다른 오리진·다른 동작이라 1번 검사가 이 경로를 대신 봐주지 못한다.
#
# 상태와 무관하게 본다. 켜져 있든 꺼져 있든 이 경로는 **항상 200이어야 하는 곳**이라
# 오탐이 구조적으로 안 난다. 요청은 매시 한 번뿐이고 캐시된 응답이라 요금도 무시할 수준이다.
# 캐시 우회 쿼리를 붙이지 않는 이유가 그것이다 — 여기서 보려는 것은 '엣지가 사람에게
# 무언가를 돌려주는가'이지 오리진까지의 왕복이 아니다(오리진은 1번이 본다).
static_code=$(http_code "$CF_URL/")
# 못 본 것과 죽은 것을 가른다. 이 구분이 이 저장소가 반복해서 고친 자리다.
case "$static_code" in
  200)
    ok "공개 사이트 200 — 정적 쪽은 서버와 무관하게 살아 있다"
    ;;
  "" | 000)
    fail "공개 사이트를 못 봤다(네트워크·타임아웃) — '죽었다'는 뜻이 아니다. 다음 실행에서 다시 본다."
    ;;
  *)
    fail "공개 사이트가 $static_code 다 — S3 정적 호스팅이나 CloudFront Function이 깨졌다."
    echo "     서버 상태와 무관한 경로다. 배포 산출물·버킷 정책·엣지 함수를 확인할 것."
    ;;
esac

# ── 2. 백업이 실제로 쌓이고 있는가 ──────────────────────────────────────────
# `2>/dev/null` + 빈 문자열 검사로 받으면 안 된다 — AccessDenied·자격증명 만료가
# **"백업이 하나도 없다"는 사실 주장**으로 나간다. 아래 3·4·5·6절이 이미 호출 실패와
# 0건을 가르는데 이 절만 안 쓸려 있었다(2026-08-11 공백검사).
if ! latest=$(aws s3api list-objects-v2 --bucket "$BUCKET" --prefix "blog-" --region "$REGION" \
  --query 'sort_by(Contents,&LastModified)[-1].[Key,LastModified]' --output text 2>&1); then
  fail "백업 목록을 읽지 못했다(s3://$BUCKET/) — 권한이나 자격증명 확인. '백업 없음'과 다르다."
  echo "     $latest"
elif [ -z "$latest" ] || [ "$latest" = "None" ]; then
  fail "백업이 하나도 없다: s3://$BUCKET/"
else
  key=${latest%%$'\t'*}
  mod=${latest##*$'\t'}
  # 파싱에 실패하면 **비워 둔다.** 예전에는 여기서 `mod_s=$now` 로 채웠는데, 그러면 아래
  # keep/ 비교가 '지금'을 최신 덤프 시각으로 알고 돌아 keep 이 항상 더 오래된 것으로 나온다
  # (읽기 실패가 '승격이 실패했다'는 거짓 사실이 된다). 비워 두면 그 블록이 '대조 못 함'을
  # 말하는 분기로 정확히 떨어진다.
  if ! mod_s=$(date -u -d "$mod" +%s 2>/dev/null); then
    fail "백업 시각을 해석하지 못했다(값: '$mod')"
    mod_s=""
  fi
  age_d=$(( (now - ${mod_s:-now}) / 86400 ))
  if [ -z "$mod_s" ]; then
    : # 시각을 못 읽었다. 위에서 이미 실패로 셌고, 나이 판정은 건너뛴다.
  elif [ "$age_d" -ge "$MAX_BACKUP_AGE_D" ]; then
    fail "최신 백업이 ${age_d}일 전이다($key). 백업은 정지 절차 때만 도니, 그동안 서버를 안 껐거나 백업이 깨졌다."
  else
    ok "최신 백업 ${age_d}일 전 — $key"
  fi
fi

# 만료되지 않는 마지막 보루. 날짜별 덤프는 180일에 지워지므로 이게 없으면
# 오래 손을 놓았을 때 백업이 0개가 되는 구간이 생긴다.
# 여기도 `>/dev/null 2>&1`로 뭉치면 404(없다)와 403(못 봤다)이 같은 메시지가 된다.
# head-object는 없으면 254, 권한이 없으면 254지만 stderr 문구가 다르다 — 그걸 본다.
#
# **2026-08-31: '있다'만 보던 것을 '언제 것인가'까지 본다.** 이 검사는 존재만 확인했고
# 그래서 keep/ 이 몇 달 전에 얼어붙어도 매시 초록이었다. 그런데 이 파일을 갱신하는 자리는
# 정지 절차 3/6 단계 하나뿐이고, 거기서 승격이 실패해도 일부러 경고만 찍고 넘어간다
# (끄는 것을 막으면 과금이 계속되므로 그 선택은 옳다). 즉 실패가 조용히 남는 구조인데
# 그 뒤로 다시 보는 눈이 없었다. 이 저장소가 이름 붙인 병 그대로다 — 검사가 자기 대상의
# 핵심 속성을 안 본다.
#
# 임계를 '며칠 이상 낡음'이 아니라 **최신 blog-* 덤프와의 선후**로 잡는 이유: 이 서버는
# 몇 주씩 안 켜지는 게 정상이라 절대 나이로 재면 정상 상태가 영구 빨간불이 된다.
# 정지 절차는 덤프를 뜬 **직후** 그것을 keep/ 으로 승격하므로, 정상이면 keep 이 최신
# 덤프보다 같거나 새롭다. keep 이 더 오래면 승격만 실패한 것이고 그게 정확히 이 신호다.
if keep_out=$(aws s3api head-object --bucket "$BUCKET" --key "keep/latest.sql.gz" \
  --region "$REGION" --query 'LastModified' --output text 2>&1); then
  if ! keep_s=$(date -u -d "$keep_out" +%s 2>/dev/null); then
    fail "keep/latest.sql.gz 의 시각을 해석하지 못했다(값: '$keep_out')."
  elif [ -z "${mod_s:-}" ]; then
    # 위 목록 조회가 실패한 경우다. 비교 대상이 없으니 사실만 말한다.
    ok "만료 안 되는 사본 있음 — keep/latest.sql.gz ($(( (now - keep_s) / 86400 ))일 전). 최신 덤프와는 대조 못 함"
  elif [ "$keep_s" -lt "$mod_s" ]; then
    fail "keep/latest.sql.gz 가 최신 덤프보다 오래됐다 — 정지 절차의 승격이 실패한 채 남아 있다."
    echo "     keep/latest.sql.gz : $keep_out"
    echo "     최신 덤프          : $mod ($key)"
    echo "     조치: aws s3 cp s3://$BUCKET/$key s3://$BUCKET/keep/latest.sql.gz"
  else
    ok "만료 안 되는 사본 최신 — keep/latest.sql.gz ($(( (now - keep_s) / 86400 ))일 전, 최신 덤프 이후)"
  fi
elif printf '%s' "$keep_out" | grep -qi '404\|Not Found'; then
  fail "keep/latest.sql.gz 가 없다. 정지 절차가 만들지만, 없으면 장기 방치 시 백업이 전멸할 수 있다."
else
  fail "keep/latest.sql.gz 를 확인하지 못했다 — 권한이나 자격증명 확인. '없다'와 다르다."
  echo "     $keep_out"
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
elif [ "$src_n" -eq 0 ] && [ "$dst_n" -gt 0 ]; then
  # ⚠️ **판정 근거는 개수가 아니라 삭제 표식이다.** 개수 비교만 쓰면 오탐이 영구화된다:
  #    사본을 만드는 stop_server.sh의 `aws s3 sync`에는 `--delete`가 없어서 **사본은
  #    절대 줄지 않는다.** 그래서 사용자가 이미지를 정상적으로 전부 지우면
  #    영구히 `원본 0 / 사본 N`이 되고, fail은 종료코드에 들어가므로 **매시 실패 메일**이
  #    나간다. 해제 방법이 '사람이 백업 사본을 손으로 지우기'뿐인 알람은
  #    이 파일이 스스로 경계하는 '영구 빨간불'이다. (2026-08-11 동료 리뷰)
  #    삭제 표식이 있으면 진짜 삭제, 없으면 정상적으로 비운 것이다.
  if dm=$(aws s3api list-object-versions --bucket "$IMAGE_BUCKET" --prefix uploads/ \
      --query "length(DeleteMarkers[?IsLatest==\`true\`] || \`[]\`)" --output text 2>&1); then
    if [ "$dm" = "0" ]; then
      ok "업로드 이미지 없음(정상적으로 비움 — 삭제 표식 0건, 사본 $dst_n개는 과거분)"
      dm=""
    fi
  else
    warn "삭제 표식을 못 읽었다 — 권한 확인. 개수만으로 판정한다."
    echo "     $dm"
    dm="unknown"
  fi
  if [ -n "$dm" ]; then
  # **사본이 원본보다 많다는 것 자체가 원본 삭제의 신호다.** 예전엔 이 자리가
  # `src_n -eq 0 → ok "확인할 것 없음"`이었는데, 그건 RECOVERY.md의 시나리오 C
  # (업로드 이미지를 잃었다)와 **글자 그대로 같은 상태**를 초록으로 찍는 것이었다.
  # 실제로 2026-07-30에 이미지 2개가 지워졌고 08-11까지 12일, 약 280회 실행이
  # 전부 초록이었다(복구는 버저닝으로 했다). 위 20줄이 '못 봤음'과 '없음'을
  # 가르라고 적어둔 교훈이, 정작 바로 아래 이 분기에는 안 쓸려 있었다.
  fail "원본 이미지가 사라졌다(원본 0 / 사본 $dst_n). 사본이 더 많다 = 원본이 지워졌다는 뜻이다."
  echo "     버저닝으로 복구한다 — 삭제 표식을 지운다:"
  echo "     aws s3api list-object-versions --bucket $IMAGE_BUCKET --prefix uploads/ \\"
  echo "       --query \"DeleteMarkers[?IsLatest==\\\`true\\\`].[Key,VersionId]\" --output text"
  echo "     aws s3api delete-object --bucket $IMAGE_BUCKET --key <KEY> --version-id <DELETE_MARKER_ID>"
  echo "     원인은 대개 --exclude \"uploads/*\" 없이 돌린 수동 aws s3 sync --delete 다."
  fi
elif [ "$src_n" -eq 0 ]; then
  ok "업로드 이미지 없음(원본·사본 모두 0)"
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
  if [ "$SES_SANDBOX_EXPECTED" = "true" ]; then
    warn "SES가 프로덕션으로 바뀌었다 — 샌드박스를 기대하고 있었다."
    echo "     의도한 변경이면 watch.sh의 SES_SANDBOX_EXPECTED를 false로 바꾸세요."
  else
    ok "SES 프로덕션 액세스 활성 — 누구에게나 발송 가능"
  fi
elif [ -z "$prod_access" ]; then
  # '못 읽었다'를 경고로 두면 안 된다 — 감시가 눈이 먼 상태를 초록으로 보고하게 된다.
  # ses:GetAccount 권한이 사라지면 SES 샌드박스를 4주간 아무도 몰랐던 그 상태로
  # 정확히 되돌아가면서 알림은 한 통도 안 간다. EC2 읽기 실패도 이미 fail이다.
  fail "SES 상태를 못 읽었다 — 감시가 눈이 먼 상태다(권한 확인: ses:GetAccount)"
elif [ "$SES_SANDBOX_EXPECTED" = "true" ]; then
  echo "--   SES 샌드박스 (확정 상태) — 제3자 가입은 막혀 있다."
  echo "     2026-08-04 종결: 두 번 신청·두 번 거절 → 샌드박스로 계속 운영한다."
  echo "     새 수신자는 scripts/ses_verify_recipients.sh로 등록. docs/ses-production-access.md"
else
  fail "SES가 아직 샌드박스다 → 검증된 주소 외에는 인증·비번재설정 메일이 안 간다."
  echo "     가입자는 성공 응답만 받고 메일을 못 받으며, 24시간 뒤 계정이 삭제된다."
  echo "     조치: docs/ses-production-access.md (콘솔에서 재신청해야 한다)"
fi

# ── 5. 자격증명·감사기록이 온전한가 ─────────────────────────────────────────
# 2026-07-27 IR 훈련에서 나온 구멍: CloudTrail은 모든 걸 기록하는데 **그걸 보는 게
# 아무것도 없었다**(GuardDuty 없음, CloudWatch 알람 0개). 관리자 액세스키가 유출되면
# 탐지 수단이 사실상 월말 청구서와 $10 예산 알림뿐이었다.
#
# 여기서 IP 화이트리스트 같은 걸 하지 않는 이유: 집 IP가 바뀌면 영구 빨간불이 되고,
# 영구 빨간불은 아무도 안 보는 신호와 같다(이 저장소가 반복해서 배운 것). 대신
# **오탐이 구조적으로 불가능한 것만** 본다 — 사실이거나 아니거나인 항목들이다.

# (a) 감사기록이 살아 있는가. 침해자의 첫 수는 보통 로깅 정지다.
#
# **2026-08-31: 배달 실패를 같이 본다.** 로깅을 끄는 것은 API 호출이라 그 자체로 흔적이
# 남는다. 더 조용한 경로는 버킷 정책이나 버킷 삭제로 **배달만 끊는 것**이고, 그때
# `IsLogging` 은 True 로 남는다. 즉 이 검사는 자기가 선언한 위협모델의 조용한 쪽을
# 안 보고 있었다. 같은 응답에 이미 오는 필드라 호출도 권한도 안 늘어난다.
#
# `LatestDeliveryTime` 의 나이로는 판정하지 않는다 — 조용한 계정은 배달할 이벤트가 없어
# 시각이 안 움직이는 게 정상이고, 그걸 신호로 잡으면 영구 빨간불이 된다.
# 반면 `LatestDeliveryError` 는 있거나 없거나라 오탐이 구조적으로 불가능하다.
# (2026-08-31 라이브 실측: IsLogging=True · LatestDeliveryError=None)
read -r trail_logging trail_err <<EOF
$(aws cloudtrail get-trail-status --region "$REGION" --name blog-audit \
  --query '[IsLogging,LatestDeliveryError]' --output text 2>/dev/null)
EOF
if [ -z "${trail_logging:-}" ]; then
  fail "CloudTrail 상태를 못 읽었다 — 감사기록이 있는지조차 모르는 상태다."
elif [ "$trail_logging" != "True" ]; then
  fail "CloudTrail 로깅이 꺼져 있다 — 침해 시 '누가 뭘 했나'에 답할 수 없다."
  echo "     조치: aws cloudtrail start-logging --name blog-audit --region $REGION"
elif [ -n "${trail_err:-}" ] && [ "$trail_err" != "None" ]; then
  fail "CloudTrail 이 로깅 중이지만 S3로 배달하지 못하고 있다 — 기록이 안 쌓인다."
  echo "     사유: $trail_err"
  echo "     버킷 정책·버킷 존재·암호화 키를 확인할 것(terraform/cloudtrail.tf)."
else
  ok "CloudTrail 기록 중 · 배달 정상 (blog-audit)"
fi

# (b) 액세스키가 예상보다 많은가. 공격자가 지속성을 확보하는 전형적 수법이 키 추가다.
#     사용자별 기대치는 각 1개. 늘어나면 내가 만든 것인지 즉시 따져야 한다.
#     사용자 목록을 **열거해서** 돈다. 2026-08-10 보안검사 전까지는 두 명이 하드코딩돼
#     있었는데, 라이브 계정에는 AdministratorAccess 사용자가 하나 더 있었고(`youno`)
#     그 계정이 감시 밖이었다 — **키를 만들 가치가 가장 큰 계정**이 루프 밖이었다는 뜻이다.
#     하드코딩은 새로 만든 사용자도 못 본다. 목록을 코드에 박지 않으면 목록이 낡지 않는다.
if ! users=$(aws iam list-users --query 'Users[].UserName' --output text 2>/dev/null) \
   || [ -z "$users" ]; then
  fail "IAM 사용자 목록을 못 읽었다 — 감시가 눈이 먼 상태다(iam:ListUsers 권한 확인)."
  users=""
fi
for u in $users; do
  n=$(aws iam list-access-keys --user-name "$u" --query 'length(AccessKeyMetadata)' --output text 2>/dev/null)
  if [ -z "$n" ]; then
    fail "액세스키 목록을 못 읽었다 ($u) — 감시가 눈이 먼 상태다."
  elif [ "$n" -eq 0 ]; then
    # 키가 0개인 건 **정상이고 오히려 좋다**(콘솔 전용 계정). 여기서 나이를 읽으려 들면
    # AccessKeyMetadata[0]이 비어 "생성일을 못 읽었다"는 가짜 실패가 난다 — 열거로
    # 바꾸면서 새로 생긴 경로라 명시적으로 처리한다.
    ok "$u 액세스키 0개 (콘솔 전용 — 장기 키 없음)"
  elif [ "$n" -gt 1 ]; then
    # 로테이션 중에는 새 키와 옛 키가 잠깐 함께 산다(docs/incident-response.md 3장).
    # 그때 이게 빨간불이 되는 건 **의도한 동작**이다 — 로테이션이 끝나면 저절로 꺼진다.
    fail "$u 에 액세스키가 $n 개다(기대 1개). 로테이션 중이 아니면 침해를 의심할 것."
    echo "     확인: aws iam list-access-keys --user-name $u"
  else
    # (c) 키 나이. 오래된 키는 유출돼도 모른 채 쌓인다. 90일이면 교체 신호.
    created=$(aws iam list-access-keys --user-name "$u" \
      --query 'AccessKeyMetadata[0].CreateDate' --output text 2>/dev/null)
    # 못 읽었으면 **초록으로 넘기지 않는다.** 빈 값을 그냥 계산에 넣으면 date가 '지금'으로
    # 해석해 나이가 0일이 되고, 눈이 먼 상태가 "✅ 키 1개 · 0일"로 보고된다(가짜 초록).
    # 이 저장소가 SES에서 4주간 당한 게 정확히 그 형태였다.
    if [ -z "$created" ] || [ "$created" = "None" ]; then
      fail "$u 액세스키 생성일을 못 읽었다 — 감시가 눈이 먼 상태다."
      continue
    fi
    created_epoch=$(date -u -d "$created" +%s 2>/dev/null)
    if [ -z "$created_epoch" ]; then
      fail "$u 액세스키 생성일을 해석 못 했다 ($created)."
      continue
    fi
    age=$(( (now - created_epoch) / 86400 ))
    if [ "$age" -ge 90 ]; then
      warn "$u 액세스키가 ${age}일 됐다 — 교체를 검토할 것(docs/incident-response.md)."
    else
      ok "$u 액세스키 1개 · ${age}일"
    fi
  fi
done

# ── 5-B. 계정에 EBS 스냅샷이 남아 있는가 ────────────────────────────────────
# **이 운영의 정상 상태는 '자기 소유 스냅샷 0건'이다.** 근거를 다 확인하고 적는다
# (2026-09-02):
#   · terraform/ 전체에 스냅샷을 만드는 자원이 없다 — aws_ebs_snapshot·aws_dlm_lifecycle_policy·
#     aws_backup_plan/vault/selection 전부 0건. 루트 볼륨은 관리 자원조차 아니고
#     ec2.tf 의 인라인 root_block_device 다.
#   · RECOVERY.md 388줄에 '스냅샷'이라는 낱말이 **한 번도 안 나온다.** :56-63 자산 표의
#     '사본' 칸은 전부 S3·GitHub·SSM·버저닝이고, 시나리오 B는 맨 AMI에서 다시 세운 뒤
#     S3 덤프(keep/latest.sql.gz)로 복원한다. 스냅샷을 쓰는 복구 경로가 아예 없다.
#   · terraform/rds.tf:54 는 오히려 skip_final_snapshot=true 로 스냅샷을 **끈다**
#     (그 RDS 블록 자체가 enable_ecs=false 로 꺼져 있어 실물도 없다).
#   즉 스냅샷은 백업 수단이 아니다. 여기 남아 있는 것은 예외 없이 '치우다 만 것'이다.
#
# 왜 그게 위험한가 — 게임데이의 break-glass 스냅샷은 **옛 루트 볼륨 통째**라 pgdata와
# `.env` 21개 키가 전부 들어 있다. 그런데 그 사본은 에스크로의 "셋"(서버·이 PC·SSM)에도,
# docs/incident-response.md:13-27 유출 자산 표에도, 이 파일 어디에도 없었다.
# 계정 기본 EBS 암호화가 꺼져 있어 **비암호화**로 누워 있기까지 하다. 08-11에 ecs.tf 가
# 겪은 '넷째 사본이 어느 문서에도 어느 점검에도 없었다'와 글자 그대로 같은 모양이다.
#
# 왜 사람 기억에 맡기면 안 되는가 — 뜨는 절차(게임데이 문서)는 있는데 지우는 절차가 없다.
# 07-27 것은 지웠지만 **그 기록조차 없다.** 07-27은 지워졌고 08-27은 남아 있다는 사실이
# 곧 '기억은 두 번 중 한 번 샌다'는 실측이다.
#
# 왜 warn 이 아니라 fail 인가 — 스냅샷 하나하나가 시크릿 사본이다. 그리고 이건 영구
# 빨간불이 아니다: 지우면 꺼진다. 게임데이 중에는 몇 시간 빨간불인데, 그게 정확히
# "끝나면 지워라"는 알림이다.
#
# 예외 목록. **지금은 비어 있다** — 위 근거대로 정상적으로 존재해야 하는 스냅샷이
# 하나도 없기 때문이다. 나중에 정말 상시로 둘 것이 생기면 여기에 ID를 적고 **왜**
# 예외인지 한 줄 남긴다. 검사를 통째로 끄지 말고 여기 한 줄로 적으라는 뜻이다
# (check_publish_secrets.py 의 ALLOW 와 같은 규칙).
SNAPSHOT_ALLOW=""

# 조회 실패를 '0건'으로 읽지 않는다. `--output text` 는 0건이면 빈 문자열에 종료코드 0,
# 권한 없음·자격증명 만료면 종료코드가 0이 아니다 — 그 둘을 가른다. 이 파일이 2·3절에서
# 이미 같은 실수를 했다(AccessDenied 가 "백업 0건"이라는 사실 주장으로 나갔다).
if ! snaps=$(aws ec2 describe-snapshots --owner-ids self --region "$REGION" \
    --query 'Snapshots[].[SnapshotId,StartTime,VolumeId,VolumeSize,Encrypted]' \
    --output text 2>&1); then
  fail "EBS 스냅샷 목록을 못 읽었다 — 권한이나 자격증명 확인. '0건'과 다르다."
  sed 's/^/       /' <<< "$snaps"
else
  snap_n=0      # 예외를 뺀 '치워야 할' 개수
  snap_total=0  # 실제로 존재하는 개수
  # 파이프가 아니라 here-string 을 쓴다 — 파이프면 while 이 서브셸에서 돌아
  # snap_n 증가가 밖으로 안 나오고, 그러면 아래 판정이 항상 '0건'이 된다.
  # 0건일 때 here-string 은 빈 줄 하나를 주므로 그 줄은 건너뛴다.
  while IFS=$'\t' read -r sid start vol size enc; do
    [ -n "${sid:-}" ] || continue
    snap_total=$((snap_total + 1))
    case " $SNAPSHOT_ALLOW " in
      *" $sid "*)
        ok "스냅샷 $sid 는 예외 목록에 있다 (근거는 watch.sh 5-B 주석)"
        continue
        ;;
    esac
    snap_n=$((snap_n + 1))
    # 나이도 같이 찍는다. '어제 뜬 것'과 '두 달째 누워 있는 것'은 다른 이야기다.
    if age_s=$(date -u -d "${start:-}" +%s 2>/dev/null); then
      age="$(( (now - age_s) / 86400 ))일 전"
    else
      # 시각을 못 읽었다고 나이를 0으로 채우지 않는다 — 그건 '방금 떴다'는 거짓 사실이 된다.
      age="나이 미상(StartTime='${start:-비어있음}')"
    fi
    # `--output text` 의 불리언은 파이썬 표기라 True/False 다(2026-09-02 라이브 실측).
    # 소문자로만 비교하면 **항상 '미상'**으로 떨어져 비암호화 사실이 묻힌다.
    case "${enc:-}" in
      True | true)   encnote="암호화됨" ;;
      False | false) encnote="**비암호화**" ;;
      *)             encnote="암호화 여부 미상('${enc:-비어있음}')" ;;
    esac
    fail "EBS 스냅샷이 남아 있다: $sid ($age · 볼륨 ${vol:-?} ${size:-?}GB · $encnote)"
    echo "       루트 볼륨 스냅샷은 pgdata 와 .env 를 통째로 담은 **시크릿 사본**이다."
    echo "       게임데이가 끝났으면 지운다(사용자가 직접 — 규칙상 이 스크립트는 안 지운다):"
    echo "         aws ec2 delete-snapshot --snapshot-id $sid --region $REGION"
    echo "       상시로 둘 것이면 watch.sh 5-B 의 SNAPSHOT_ALLOW 에 이유와 함께 적을 것."
  done <<< "$snaps"

  # 전부 예외였을 때 "0건 (정상 상태)"라고 찍으면 **없는 것과 있는 것이 같은 문구**가
  # 된다. 이 파일이 내내 가르는 그 구분이라 여기서도 가른다.
  if [ "$snap_total" -eq 0 ]; then
    ok "자기 소유 EBS 스냅샷 0건 (이 운영의 정상 상태)"
  elif [ "$snap_n" -eq 0 ]; then
    ok "EBS 스냅샷 ${snap_total}건 — 전부 예외 목록에 있다"
  fi
fi

# ── 6. 비용 가드레일이 살아 있는가 ──────────────────────────────────────────
# 2026-07-30 비용 가드레일 훈련에서 나온 것(docs/cost-guardrail-drill-20260730.md).
# 이 파일 머리말이 "살아 있는 감시는 월 예산 알림 하나뿐이었다"고 적어둔 그 알림을,
# 이제 여기서 되짚어 본다 — **감시를 감시하는 자리**다.
#
# 무엇을 신호로 삼을지가 이 절의 전부다.
#   총지출($10 예산)은 지금 178%다. 크레딧이 전액 상계하고 있어서 실제 청구는 $0이고,
#   크레딧을 태우는 건 의도다. 그걸 실패로 잡으면 **월말까지 영구 빨간불**이 되고,
#   영구 빨간불은 아무도 안 보는 신호가 된다(이 저장소가 세 번 배운 것).
#   그래서 총지출은 정보로만 찍는다.
#
#   신호는 **크레딧이 덮지 못하는 순지출**이다. Zero-Spend 예산이 그걸 본다
#   (IncludeCredit=true라 크레딧 상계 후 금액을 읽는다). 평소엔 $0이라 조용하고,
#   크레딧이 마르거나 예상 못 한 청구가 생기는 순간에만 켜진다 — 오탐이 구조적으로
#   드문 자리다. 크레딧 만료는 2027-06-24로 확정돼 있으니 그날 이후 이게 이 계정의
#   1차 경보가 된다.
NET_BUDGET="My Zero-Spend Budget"
GROSS_BUDGET="My Monthly Cost Budget"

# **읽기 실패와 사실 주장을 절대 섞지 않는다.** 이 절을 처음 쓸 때 JSON을 python3으로
# 세게 했다가, 2026-07-30 검사에서 python3이 깨진 상태를 주입해보니 그 실패가
# **"예산이 0개다 — 청구서 폭주를 알려줄 장치가 없다"는 거짓 사실**로 보고됐다
# (예산은 그때도 2개 있었다). 07-22의 SES 건, 07-28의 심층검사 건과 같은 병이다.
# 그래서 python3을 경로에서 빼고 CLI의 --query와 awk만 쓴다. 셋 다 없으면 aws 호출
# 자체가 안 되므로 '못 읽었다'로 정직하게 떨어진다.
if ! budget_rows=$(aws budgets describe-budgets --account-id "$ACCOUNT_ID" \
      --query 'Budgets[].[BudgetName,BudgetLimit.Amount,CalculatedSpend.ActualSpend.Amount]' \
      --output text 2>/dev/null); then
  # 못 읽은 걸 초록으로 넘기지 않는다 — SES에서 4주간 당한 게 정확히 그 형태였다.
  fail "예산을 못 읽었다 — 비용 가드레일이 있는지조차 모르는 상태다."
  echo "     확인: aws budgets describe-budgets --account-id $ACCOUNT_ID"
  echo "     CI에서 이게 뜨면 watch-readonly 정책에 budgets:ViewBudget이 빠진 것이다."
elif [ -z "$budget_rows" ]; then
  # 여기까지 왔으면 '읽었고, 진짜로 0개'다. 위와 메시지가 달라야 하는 이유가 이것이다.
  fail "예산이 0개다 — 청구서 폭주를 알려줄 장치가 없다."
else
    # 총지출: 정보로만. 크레딧이 덮고 있는 동안은 이게 상한을 넘는 게 정상 상태다.
    printf '%s\n' "$budget_rows" | awk -F'\t' '{
      pct = ($2 > 0) ? sprintf("%.0f%%", $3 / $2 * 100) : "?"
      printf "  --   예산 %s: $%.2f / $%.2f (%s)\n", $1, $3, $2, pct
    }'

    # 순지출 예산이 아직 존재하는가. 사라지면 크레딧 만료 후 눈이 먼다.
    # 이름은 **줄 전체 일치**로 본다(-qxF). 부분 일치로 받으면 "…Budget 2" 같은 다른
    # 예산이 이 검사를 통과시키는데, 정작 아래 describe는 정확한 이름으로 부른다.
    if printf '%s\n' "$budget_rows" | cut -f1 | grep -qxF "$NET_BUDGET"; then
      # 그 예산의 ACTUAL 알림 상태 — ALARM이면 크레딧이 더 이상 덮지 못한다는 뜻이다.
      # 알림 **객체 전체**를 받는다. 아래에서 구독자를 물을 때 그 객체를 그대로 넘겨야
      # 하기 때문이다(손으로 조립하면 임계나 연산자가 어긋나 '없는 알림'이 되고, 그러면
      # 읽기 실패가 '아무도 안 받는다'는 사실 주장으로 나간다 — 이 스크립트가 2번 검사에서
      # 이미 한 번 고친 병이다).
      if ! notif=$(aws budgets describe-notifications-for-budget --account-id "$ACCOUNT_ID" \
            --budget-name "$NET_BUDGET" \
            --query 'Notifications[?NotificationType==`ACTUAL`]|[0]' \
            --output json 2>/dev/null); then
        # 예산 목록은 읽혔는데 알림은 못 읽은 경우다. "알림이 없다"고 단정하면
        # 없는 사실을 말하는 것이 된다 — 위와 같은 이유로 갈라놓는다.
        fail "'$NET_BUDGET'의 알림 상태를 못 읽었다 — 예산은 보이는데 알림은 모르는 상태다."
      elif [ -z "$notif" ] || [ "$notif" = "null" ]; then
        fail "'$NET_BUDGET'에 ACTUAL 알림이 없다 — 예산은 있는데 아무도 안 부르는 상태다."
      elif printf '%s' "$notif" | grep -q '"NotificationState": *"ALARM"'; then
        fail "순지출(크레딧 상계 후)이 '$NET_BUDGET' 상한을 넘었다 — 실제 청구가 시작됐다는 뜻이다."
        echo "     확인: aws ce get-cost-and-usage --time-period Start=\$(date -u +%Y-%m-01),End=\$(date -u -d '+1 month' +%Y-%m-01) \\"
        echo "             --granularity MONTHLY --metrics UnblendedCost --group-by Type=DIMENSION,Key=RECORD_TYPE"
      else
        ok "순지출 감시 정상 ('$NET_BUDGET' 알림 OK — 크레딧이 아직 덮고 있다)"
      fi

      # 그 알림이 **사람에게 닿는가.**
      #
      # ⚠️ 이 블록은 위 사슬이 알림을 **읽어낸 경우에만** 돈다. 처음엔 조건 없이 이어
      # 붙였는데, 그러면 notif 가 비어 있거나 null 일 때도 --notification "" 로 호출이
      # 나가고 aws 가 ParamValidation(rc=252)으로 떨어진다. 그 문구에는 NotFound 가 없어
      # 마지막 갈래로 흘러 **"수신자를 못 읽었다 … budgets:ViewBudget 범위를 확인할 것"**을
      # 찍는다. 원인 하나에 실패가 둘 나가고, 두 번째가 사람을 IAM 으로 잘못 보낸다
      # (2026-08-31 검사). 클라이언트 측 오류라 AWS 호출은 나가지도 않는다. 6-B 절 전체가 "발동했다와 닿았다는 다르다"는
      # 07-30 비용 훈련의 결론으로 만들어졌는데, 정작 그 훈련의 대상이었던 예산 알림에는
      # 같은 질문이 안 붙어 있었다(2026-08-31). 구독자가 0명이면 크레딧이 마르는 순간
      # 예산은 정상적으로 ALARM이 되고 정상적으로 아무에게도 안 간다. 크레딧 만료가
      # 2027-06-24로 확정돼 있어 그때 이게 1차 경보가 되는 자리다.
      #
      # 주소는 찍지 않는다 — 이 출력은 공개 저장소의 Actions 로그로 남는다. 개수와
      # 종류만으로 '닿는가'에는 답이 된다.
      #
      # 구독자가 하나도 없으면 AWS는 빈 목록이 아니라 NotFoundException을 준다.
      # 그래서 호출 실패를 뭉뚱그리면 '못 읽었다'가 '0명이다'로 둔갑한다. 문구로 가른다.
      if [ -z "${notif:-}" ] || [ "$notif" = "null" ]; then
        : # 위에서 이미 '알림이 없다'거나 '못 읽었다'로 실패를 셌다. 같은 원인으로 두 번 울지 않는다.
      elif subs_out=$(aws budgets describe-subscribers-for-notification --account-id "$ACCOUNT_ID" \
            --budget-name "$NET_BUDGET" --notification "$notif" \
            --query 'length(Subscribers)' --output text 2>&1); then
        if ! printf '%s' "$subs_out" | grep -qE '^[0-9]+$'; then
          # 호출은 됐는데 숫자가 아닌 것이 왔다. 이걸 0으로 접으면 **읽기 이상이
          # '아무도 안 받는다'는 사실 주장으로** 나간다. 이 스크립트가 여러 번 고친 병이다.
          fail "'$NET_BUDGET' 알림의 수신자 수를 해석하지 못했다(값: '$subs_out')."
        elif [ "$subs_out" -gt 0 ]; then
          ok "'$NET_BUDGET' 알림 수신자 ${subs_out}명 — 울리면 사람에게 간다"
        else
          fail "'$NET_BUDGET' 알림에 수신자가 0명이다 — 울려도 아무에게도 안 간다."
        fi
      elif printf '%s' "$subs_out" | grep -qi 'NotFound'; then
        fail "'$NET_BUDGET' 알림에 수신자가 0명이다 — 울려도 아무에게도 안 간다."
        echo "     AWS 콘솔의 예산 알림에 이메일 수신자를 추가할 것."
      else
        fail "'$NET_BUDGET' 알림의 수신자를 못 읽었다 — 닿는지 모르는 상태다. '0명'과 다르다."
        echo "     $subs_out"
        echo "     CI에서 이게 뜨면 watch-readonly 정책의 budgets:ViewBudget 범위를 확인할 것."
      fi
    else
      fail "'$NET_BUDGET' 예산이 없다 — 크레딧이 마르는 순간을 알려줄 장치가 없다."
    fi

    # 총지출 예산도 존재는 확인한다(둘 다 사라지면 위 정보 줄이 그냥 안 찍힐 뿐이라 조용하다).
    printf '%s\n' "$budget_rows" | cut -f1 | grep -qxF "$GROSS_BUDGET" \
      || warn "'$GROSS_BUDGET' 예산이 없다 — 크레딧 소모 속도를 보는 눈이 사라졌다."
fi

# ── 6-B. 상태검사 알람이 '사람에게 닿을 수 있는' 상태인가 ────────────────────
# 2026-08-09에 EC2 상태검사 알람을 붙였다(terraform/alerts.tf). 이 절은 그 알람이
# 존재하는지가 아니라 **울렸을 때 실제로 누군가에게 가는지**를 본다.
#
# 왜 그 구분이 중요한가 — SNS 이메일 구독은 받는 사람이 확인 메일의 링크를 눌러야
# 활성화된다. 안 누른 동안 상태는 PendingConfirmation이고, 알람은 정상적으로 울리며
# 정상적으로 아무에게도 안 간다. 콘솔에서는 구독이 '있는' 것으로 보인다.
# 2026-07-22에 `WARN`이 종료코드에 안 들어가 알림이 0건이던 것과 같은 모양이다.
# **"발동했다"와 "사람에게 닿았다"는 다르다**(07-30 비용 훈련의 결론).
ALARM_NAME="blog-ec2-status-check-failed"

# 알람의 상태와 **알림 대상 토픽을 함께** 읽는다. 토픽 ARN을 손으로 조립하지 않는
# 이유가 이 검사의 목적 그 자체다 — 알람이 다른 토픽을 가리키도록 바뀌어도(이름 변경,
# 토픽 추가, apply 실수) 조립한 ARN에는 확인된 구독이 그대로 있어서 매시 초록이 난다.
# 알람이 **실제로 부르는 곳**을 봐야 '울렸을 때 닿는가'에 답이 된다.
if ! alarm=$(aws cloudwatch describe-alarms --alarm-names "$ALARM_NAME" --region "$REGION" \
      --query 'MetricAlarms[0].[StateValue,AlarmActions[0]]' --output text 2>/dev/null); then
  fail "상태검사 알람을 못 읽었다 — 알람이 있는지조차 모르는 상태다."
  echo "     CI에서 이게 뜨면 watch-readonly 정책에 cloudwatch:DescribeAlarms가 빠진 것이다."
else
  alarm_state=$(printf '%s\n' "$alarm" | awk '{print $1}')
  alarm_topic=$(printf '%s\n' "$alarm" | awk '{print $2}')
  if [ "$alarm_state" = "None" ] || [ -z "$alarm_state" ]; then
    # "최대 1시간"이라고 쓰여 있었는데 틀린 값이었다(2026-09-04). 이 감시는 매시
    # 돌지 않는다 — 08-31 이후 실측 간격이 중앙값 4.4시간, 최대 8.3시간이다.
    # 알람이 없을 때의 공백을 1시간으로 말하면 그 위험을 실제보다 작게 알린다.
    fail "'$ALARM_NAME' 알람이 없다 — 인스턴스가 통째로 죽으면 이 감시가 알 때까지 몇 시간이다(예약이 매시를 보장하지 않는다. watch.yml 참고)."
    echo "     복구: terraform -chdir=terraform apply (alerts.tf)"
  elif [ "$alarm_topic" = "None" ] || [ -z "$alarm_topic" ]; then
    fail "'$ALARM_NAME'에 알림 대상이 없다 — 상태는 바뀌지만 아무도 안 부른다."
    echo "     alerts.tf의 alarm_actions 를 확인하세요."
  # ALARM 상태 자체는 여기서 실패로 세지 않는다 — 그때는 SNS가 이미 알렸고,
  # 이 스크립트 1번 검사가 'EC2 running인데 API 죽음'으로 따로 잡는다. 중복 신호를
  # 만들면 둘 다 무뎌진다. 여기서는 '전달 경로'만 본다.
  elif ! subs=$(aws sns list-subscriptions-by-topic --topic-arn "$alarm_topic" --region "$REGION" \
        --query 'Subscriptions[].SubscriptionArn' --output text 2>/dev/null); then
    fail "알림 토픽의 구독을 못 읽었다 — 알람이 어디로 가는지 모르는 상태다."
  else
    # **확인된 구독은 ARN처럼 생긴 것만 센다.** SubscriptionArn 자리에는 진짜 ARN 말고
    # 의사값이 둘 온다: 아직 확인 안 누른 것은 `PendingConfirmation`, 최근에 지운 것은
    # `Deleted`다. 전에는 'PendingConfirmation이 아니면 확인된 것'으로 갈랐는데, 그러면
    # **구독을 전부 지운 직후가 초록**이 된다 — 이 검사가 잡겠다고 만든 바로 그 상태다.
    subs_n=$(printf '%s\n' "$subs" | tr '\t' '\n' | sed '/^$/d')
    confirmed=$(printf '%s\n' "$subs_n" | grep -c '^arn:aws:sns:' || true)
    pending=$(printf '%s\n' "$subs_n" | grep -cx 'PendingConfirmation' || true)
    if [ "$confirmed" -eq 0 ] && [ "$pending" -gt 0 ]; then
      fail "구독이 전부 확인 대기(PendingConfirmation) 상태다 — 알람이 울려도 메일이 안 간다."
      echo "     받는 편지함에서 AWS 확인 메일의 링크를 누르세요(스팸함도 확인)."
    elif [ "$confirmed" -eq 0 ]; then
      fail "알람은 있는데 확인된 구독이 0개다 — 울려도 아무에게도 안 간다."
      echo "     terraform.tfvars에 alert_email 을 넣고 apply 하세요. (토픽: $alarm_topic)"
    else
      # 확인된 구독이 하나라도 있으면 **전달은 된다.** 남은 pending은 경고가 아니라
      # 정보다 — SNS는 확인 안 된 구독을 최대 3일 들고 있고, alert_email을 바꾸면
      # 그동안 pending 하나가 남는다. 그걸 WARN으로 잡으면 종료코드에 들어가
      # **매시 빨간불이 사흘**이고, 그건 이 저장소가 반복해 경계한 '아무도 안 보는 신호'다.
      [ "$pending" -gt 0 ] && echo "  --   확인 대기 구독 ${pending}개 (전달은 되고 있음 — 만료되거나 확인되면 사라진다)"
      # 상태값을 '정상' 옆에 그대로 찍지 않는다. 전에는 ALARM일 때도
      # `✅ 상태검사 알람 정상 (ALARM …)`이 나왔다 — 초록 표시와 ALARM이 한 줄에 있었다.
      ok "알람 전달 경로 정상 (확인된 구독 ${confirmed}개 · 현재 알람 상태 $alarm_state)"

      # ── 최근에 ALARM이 있었나 (복구를 '확인된 뒤에' 드러내는 자리) ──
      # 알람에는 `ok_actions`를 안 붙였다. 복구를 전이 순간에 메일로 알리면 거짓이
      # 될 수 있어서다 — 끄면 지표가 끊기고 그 구간이 '정상'으로 평가돼 죽은 채로
      # "복구됨"이 나간다(alerts.tf에 첫날 이력과 함께 적어뒀다).
      #
      # 그래서 복구는 여기서 말한다. 이 줄은 **위 1번 검사와 같이 읽어야** 뜻이 산다:
      #   여기 '지난 24시간에 ALARM' + 1번 '공개 API 200' = 고장났었고 지금은 진짜 돌아왔다
      #   여기 '지난 24시간에 ALARM' + 1번 실패            = 아직 안 돌아왔다
      # 전이 순간에 추측으로 말하는 대신, 잴 수 있게 된 다음에 말한다.
      #
      # **정보로만 찍는다.** 지난 사건을 WARN으로 잡으면 종료코드에 들어가 24시간 동안
      # 매시 빨간불이고, 그건 이 저장소가 반복해 경계한 '아무도 안 보는 신호'다.
      since=$(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)
      if [ -n "$since" ] && hist=$(aws cloudwatch describe-alarm-history \
            --alarm-name "$ALARM_NAME" --history-item-type StateUpdate \
            --start-date "$since" --region "$REGION" \
            --query 'AlarmHistoryItems[?contains(HistorySummary, `to ALARM`)].Timestamp' \
            --output text 2>/dev/null); then
        n=$(printf '%s\n' "$hist" | tr '\t' '\n' | sed '/^$/d' | wc -l)
        if [ "$n" -gt 0 ]; then
          last=$(printf '%s\n' "$hist" | tr '\t' '\n' | sed '/^$/d' | sort | tail -1)
          echo "  --   지난 24시간에 상태검사 ALARM ${n}회 (마지막 $last)"
          echo "       위 1번 검사가 통과했다면 복구된 것이다. 실패했다면 아직이다."
        fi
      fi
    fi
  fi
fi

# ── 6-C. 인스턴스 알람이 '지금 살아 있는 인스턴스'를 보고 있는가 ─────────────
# 2026-08-27 DR 게임데이 결함 D2. 재건으로 인스턴스가 바뀌었는데
# `blog-ec2-status-check-failed`·`blog-cpu-credit-low` 둘은 dimensions에 **파괴된**
# 인스턴스 ID를 들고 OK 상태로 남아 있었다. 런북의 terraform 호출이 전부 `-target`이라
# 알람이 범위 밖이기 때문이다 — 알람이 인스턴스에 **의존하는** 쪽이라 끌려오지 않는다.
#
# 왜 조용한가 — 둘 다 `treat_missing_data = "notBreaching"`이다. 필요할 때만 켜는
# 서버라 그게 맞는 선택인데(꺼져 있으면 지표가 없다), **가리키는 대상이 틀렸을 때도
# 똑같이 지표가 없다.** 그래서 눈이 먼 상태가 초록과 구분되지 않는다. 6-B가 '울리면
# 사람에게 닿는가'를 통과시켜도, 애초에 아무것도 안 보고 있으면 울릴 일이 없다.
#
# 게임데이는 이걸 런북 8-B 단계(범위를 알람 둘로 좁힌 apply)로 막았다. 절차는 사람이
# 건너뛸 수 있으니 여기서 기계가 다시 본다 — 07-27 결함 F5에서 스크립트에 박혀 있던
# 인스턴스 ID를 태그 조회로 바꾼 것의 terraform 판이다.
if [ -z "$INSTANCE_ID" ]; then
  echo "  --   인스턴스 알람 대조는 건너뛴다 — 인스턴스 ID를 못 찾았다(1번 검사 참고)."
else
  for alarm_name in blog-ec2-status-check-failed blog-cpu-credit-low; do
    if ! dim=$(aws cloudwatch describe-alarms --alarm-names "$alarm_name" --region "$REGION" \
          --query 'MetricAlarms[0].Dimensions[?Name==`InstanceId`]|[0].Value' \
          --output text 2>/dev/null); then
      fail "'$alarm_name'의 dimension을 못 읽었다 — 알람이 무엇을 보는지 모르는 상태다."
      continue
    fi
    case "$dim" in
      "$INSTANCE_ID")
        ok "'$alarm_name' 가 지금 도는 인스턴스를 본다 ($INSTANCE_ID)"
        ;;
      None | "")
        fail "'$alarm_name' 이 없거나 InstanceId dimension이 비어 있다 — 이 인스턴스를 보는 눈이 아니다."
        echo "     복구: terraform -chdir=terraform apply -target=aws_cloudwatch_metric_alarm.ec2_status_check -target=aws_cloudwatch_metric_alarm.cpu_credit_low"
        ;;
      *)
        fail "'$alarm_name' 이 다른 인스턴스($dim)를 본다 — 지금 도는 것은 $INSTANCE_ID 다. 재건 뒤 알람을 안 옮겼다(DR 결함 D2)."
        echo "     복구: 위와 같은 -target 호출 (RECOVERY.md 8-B). 범위를 안 좁힌 것은 금지 — 오리진이 주차된다(D1)."
        ;;
    esac
  done
fi

# ── 7. 프론트가 최신 커밋으로 나가 있는가 ───────────────────────────────────
# 2026-08-11에 푸시 자동배포를 폐지했다(백엔드 동시변경 게이트가 fail-open이라
# 무의미했다). 그래서 프론트는 이제 **사람이 Actions에서 Run workflow를 눌러야**
# 나간다. 그런데 안 눌렀다는 걸 알려줄 장치가 저장소에 **하나도 없었다** —
# 백엔드·백업·이미지·메일·자격증명·비용·알람은 전부 이 스크립트가 보는데
# 프론트만 사각이었다. 실제로 같은 날 "정적 아카이브가 아직 28편이 아니다"를
# 사람이 눈으로 발견했다. 그게 이 절이 막으려는 모양이다.
#
# **왜 파일 갱신시각이 아니라 커밋 SHA인가.** LastModified 비교는 `s3 sync`가
# 내용이 같은 파일을 안 올린다는 이유로 늘 어긋난다 — 테스트만 고친 커밋처럼
# dist가 안 바뀌는 변경이 영구 경고가 된다. 영구 경고는 무시하게 되고, 그러면
# 감시가 있으나 없으나 같아진다. 스탬프는 '무엇이 나갔는가'를 정확히 말한다.
if ! stamp=$(aws s3 cp "s3://$IMAGE_BUCKET/deploy-stamp.txt" - --region "$REGION" 2>&1); then
  case "$stamp" in
    *NoSuchKey*|*"Not Found"*|*404*|*"does not exist"*)
      warn "프론트 배포 스탬프가 없다 — 스탬프를 넣은 뒤로 프론트를 한 번도 배포하지 않았다."
      echo "       Actions → '배포' → Run workflow. (푸시로는 안 나간다 — 2026-08-11에 폐지)"
      ;;
    *)
      # 읽기 실패를 '배포된 적 없음'으로 읽으면 안 된다 — 이 스크립트가 2·3절에서
      # 이미 같은 실수를 했다(AccessDenied가 "백업 0건"이라는 사실 주장으로 나갔다).
      fail "배포 스탬프를 읽지 못했다(s3://$IMAGE_BUCKET/deploy-stamp.txt) — 권한이나 자격증명 확인"
      sed 's/^/       /' <<< "$stamp"
      ;;
  esac
elif ! deployed=$(sed -n 's/^sha=//p' <<< "$stamp") || [ -z "$deployed" ]; then
  fail "배포 스탬프에 sha 줄이 없다 — deploy.yml의 '배포 스탬프 기록' 스텝이 바뀌었는지 확인."
elif [ "$(git rev-parse --is-shallow-repository 2>/dev/null)" = "true" ]; then
  # 얕은 체크아웃이면 아래 비교가 **항상 통과**한다(비교할 히스토리가 없으니까).
  # 조용히 통과하는 대신 그 사실을 말한다. watch.yml은 fetch-depth: 0으로 받는다.
  warn "히스토리가 얕아서 프론트 배포 시점을 비교할 수 없다(체크아웃에 fetch-depth: 0 필요)."
elif ! git cat-file -e "${deployed}^{commit}" 2>/dev/null; then
  warn "배포된 커밋 $deployed 을 이 저장소에서 못 찾는다 — 히스토리가 바뀌었거나 다른 브랜치에서 배포됐다."
else
  # dist에 영향을 주는 경로만 본다. 프론트 테스트·마크다운은 산출물에 안 들어가므로
  # 빼지 않으면 "테스트만 고쳤는데 배포하라"는 오탐이 상시로 뜬다.
  #
  # ⚠️ **2026-09-05까지 `content/devlog/` 만 봤다.** 그런데 gen-static.mjs 는 그 밖에도
  # `content/about.md`(소개 페이지 + /about.md 원문)와 `content/infra.json`(인프라 페이지)을
  # 읽는다. 둘 중 하나만 고친 커밋이 실제로 히스토리에 있고, 그 상태에서 이 검사는
  # "✅ 프론트 최신"이라는 **거짓 사실**을 찍었다(2026-09-04 검사 OPS-3).
  #
  # 그래서 목록을 `content/` 전체로 넓힌다. 하위 파일을 하나씩 적는 한 새 파일이
  # 생길 때마다 같은 구멍이 다시 열린다 — 이 저장소가 watch.yml 의 bash -n 에서
  # 두 번 겪고 "대상을 디렉터리 목록으로 두는 한 반복된다"고 적어둔 그 모양이다.
  # 지금 content/ 아래는 about.md · infra.json · devlog/ 셋뿐이고 셋 다 생성기가 읽는다.
  behind=$(git rev-list --count "$deployed..HEAD" -- \
    frontend/ content/ \
    ':!frontend/**/*.test.ts' ':!frontend/**/*.test.tsx' ':!frontend/*.md' 2>/dev/null || echo "?")
  if [ "$behind" = "?" ]; then
    warn "프론트 변경분을 세지 못했다(git rev-list 실패)."
  elif [ "$behind" -eq 0 ]; then
    ok "프론트 최신 (배포 ${deployed:0:7} · 그 뒤 프론트 변경 없음)"
  else
    warn "프론트가 $behind 커밋 뒤처져 있다 (배포 ${deployed:0:7} → HEAD $(git rev-parse --short HEAD))."
    echo "       Actions → '배포' → Run workflow 를 눌러야 나간다. 안 누르면 영원히 옛것이 뜬다."
    git log --oneline "$deployed..HEAD" -- \
      frontend/ content/ \
      ':!frontend/**/*.test.ts' ':!frontend/**/*.test.tsx' ':!frontend/*.md' 2>/dev/null \
      | head -10 | sed 's/^/       /'
  fi
fi

# ── 하트비트 ────────────────────────────────────────────────────────────────
# "감시가 돌았다"는 사실을 AWS에 남긴다. 3시간 안 오면 알람이 운다
# (terraform/alerts.tf의 blog-watch-heartbeat-missing, treat_missing_data="breaching").
#
# **검사 결과와 무관하게 보낸다.** FAIL이 나도 감시 자체는 살아 있는 것이고,
# 그 실패는 Actions 실패 메일이 따로 알린다. 여기서 조건을 걸면 "고장났는데 조용한"
# 상태와 "감시가 죽어서 조용한" 상태가 다시 뒤섞인다.
#
# 실패해도 전체를 죽이지 않는다 — 하트비트를 못 보내는 것은 그 자체로 알람이 울릴
# 일이지(12시간 뒤), 이번 실행의 검사 결과를 뒤집을 이유가 아니다. 다만 **조용히
# 넘기지는 않는다**: 못 보냈으면 그 사실을 출력한다(이 저장소가 반복해 배운 것).
if aws cloudwatch put-metric-data --namespace "blog/watch" \
  --metric-name HeartBeat --value 1 --unit Count --region "$REGION" 2>/tmp/hb.err; then
  echo
  echo "  --   하트비트 발행됨 (blog/watch HeartBeat=1)"
else
  echo
  # **`warn()`을 써야 한다.** 맨 echo로 ⚠️만 찍으면 WARN 카운터가 안 올라가고,
  # 마지막 줄(`[ "$FAIL" -eq 0 ] && [ "$WARN" -eq 0 ]`)이 exit 0을 내서
  # "== 이상 없음 ==" + Actions 초록 + 메일 없음이 된다 — 이 파일 상단이
  # "경고도 종료코드에 넣는다"고 적어둔 것과 정면으로 어긋난다.
  # 하트비트를 못 보내는 건 감시의 눈이 하나 감기는 일이라 조용하면 안 된다.
  # (2026-08-11 교차검증 — 오늘 내가 이 블록을 쓰면서 만든 자리다)
  warn "하트비트를 못 보냈다 — 12시간 뒤 blog-watch-heartbeat-missing 알람이 운다."
  sed 's/^/       /' /tmp/hb.err
fi

# ── 요약 ────────────────────────────────────────────────────────────────────
echo
if [ "$FAIL" -eq 0 ] && [ "$WARN" -eq 0 ]; then
  echo "== 이상 없음 =="
else
  echo "== 실패 $FAIL건 / 경고 $WARN건 =="
fi
[ "$FAIL" -eq 0 ] && [ "$WARN" -eq 0 ]

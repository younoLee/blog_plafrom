#!/usr/bin/env bash
# 배포 검증: **나간 것이 실제로 서빙되고 있는가**를 잰다.
#
# 왜 이 파일이 생겼는가 — 2026-08-12 개발일지 #30이 "아직 안 끝난 것"으로 이렇게 남겼다:
#   "배포 절차 어디에도 '나간 것이 실제로 서빙되는가'를 확인하는 줄이 없다.
#    오늘 만든 것 전체가 그 사각 위에 얹혔다."
# 실제로 이 저장소는 그 사각에서 두 번 헤맸다 —
#   ① 2026-08-10: `alembic current`가 "기동하면 자동 적용된다"고 적혀 있었는데 몇 번을
#      켜도 안 붙었다. 그 마이그레이션 파일이 **이미지에 없었다**. 즉 코드는 보냈는데
#      재빌드가 안 된 상태를 아무도 못 봤다.
#   ② 2026-08-11: 메모의 '미배포 8커밋'이 실은 **이미 배포돼 있었다**. 기록이 낡은 걸
#      해시를 떠보고서야 알았다. 교훈이 "목록을 믿지 말고 해시를 떠라"였는데,
#      그 해시 뜨기가 절차가 아니라 **그날의 기지**로만 있었다.
#
# 그래서 deploy_backend.sh(보내기)의 짝으로 이걸 둔다. 절차는 이렇게 완성된다:
#   deploy_backend.sh  → 사용자 재빌드(규칙7) → **verify_deploy.sh**
#
# 왜 재빌드 스크립트 안에 넣지 않는가: 재빌드는 규칙7이라 사용자가 자기 셸에서 돌린다.
# 그 명령의 뒤에 붙일 자리가 없다. 그리고 검증은 재빌드와 **다른 시점**에도 값이 있다 —
# "지금 운영에 뭐가 떠 있나"를 아무 때나 물을 수 있어야 한다.
#
# 사용:
#   scripts/verify_deploy.sh
#
# 종료코드: 0 = 전부 통과 / 1 = 하나라도 실패. Actions에 걸 수는 없다(SSH 키가 필요하다).

set -uo pipefail   # -e 는 쓰지 않는다 — 검사 하나가 실패해도 나머지를 계속 재야 한다.

. "$(dirname "${BASH_SOURCE[0]}")/lib/ec2.sh"
INSTANCE_ID=$(resolve_instance_id) || exit 1

SSH_KEY=~/.ssh/blog-key.pem
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CF_URL=https://d2j66m9udyg9yq.cloudfront.net
CF_DIST_ID=E1438IL9CSVBS4   # 주차 여부를 '추측' 대신 '조회'하는 데 쓴다(7절)
# 주차 자리는 정해진 한 값이다 — terraform/variables.tf:121의
# `backend_origin_parked = aws_s3_bucket.frontend.bucket_regional_domain_name`.
# 이 값과 '다르다'를 전부 주차로 읽으면 옛 인스턴스 주소가 남은 상태를 정상으로 보고한다.
PARKED_ORIGIN=blogplafromops.s3.ap-northeast-2.amazonaws.com
COMPOSE='sudo docker compose -f /home/ec2-user/blog/docker-compose.prod.yml'

FAIL=0
fail() { printf '❌ %s\n' "$*"; FAIL=$((FAIL + 1)); }
ok()   { printf '✅ %s\n' "$*"; }
info() { printf '  --   %s\n' "$*"; }

state=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].State.Name' --output text 2>/dev/null)
if [[ "$state" != "running" ]]; then
  echo "EC2가 '$state' 상태입니다 — 검증할 대상이 없습니다." >&2
  echo "  aws ec2 start-instances --instance-ids $INSTANCE_ID" >&2
  exit 1
fi
DNS=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].PublicDnsName' --output text)

# ssh를 검사마다 새로 붙이면 6번을 붙는다. 한 번에 받아 와서 로컬에서 쪼갠다.
# (구분자는 원격 출력에 나올 수 없는 문자열로 둔다)
remote=$(ssh -n -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -i "$SSH_KEY" \
  "ec2-user@$DNS" "
    # healthy가 될 때까지 **기다린다**(최대 200초). 이 대기는 원래 deploy_backend.sh에
    # 있었고, 재빌드 직후엔 starting이 정상이라 안 기다리면 이 검증이 상시 빨간불이 된다.
    # 상시 빨간불은 아무도 안 보는 신호가 된다 — 이 저장소가 반복해서 적어둔 결론이다.
    echo '@@HEALTH'
    for _ in \$(seq 1 40); do
      s=\$(sudo docker inspect -f '{{.State.Health.Status}}' blog-backend-1 2>/dev/null)
      [ \"\$s\" = healthy ] && break
      [ \"\$s\" = unhealthy ] && break
      [ -z \"\$s\" ] && break
      sleep 5
    done
    echo \"\$s\"
    echo '@@HASH';   $COMPOSE exec -T backend sh -c 'LC_ALL=C find app -name \"*.py\" | LC_ALL=C sort | xargs sha256sum | sha256sum' 2>/dev/null | cut -d' ' -f1
    echo '@@ALEMBIC'; $COMPOSE exec -T backend alembic current 2>/dev/null | grep -oE '^[0-9a-f]+' | head -1
    echo '@@UID';    $COMPOSE exec -T backend id -u 2>/dev/null
    # ⚠️ curl의 -w '%{http_code}'는 **줄바꿈을 안 붙인다.** 그냥 두면 다음 구분자가 같은
    # 줄에 붙어 '403@@ERRORS'가 되고, @@ERRORS 구간을 못 찾아 로그 검사까지 같이 죽는다
    # (2026-08-14 첫 실행에서 실측). 구분자 방식은 출력이 줄 단위라는 걸 전제한다.
    # ⚠️ 이 블록은 큰따옴표 안이라 **백틱을 쓰면 로컬 셸이 명령으로 실행한다.**
    # 위 주석에 백틱을 썼다가 'line 79: -w: command not found'를 봤다(같은 날, 두 번째 실측).
    echo '@@GUARD';  curl -s -o /dev/null -w '%{http_code}\n' --max-time 10 http://localhost:8000/api/status
    echo '@@ERRORS'; $COMPOSE logs backend --since 10m 2>&1 | grep -ciE 'error|traceback|exception'
    echo '@@END'
  " 2>/dev/null)

if [ -z "$remote" ]; then
  fail "SSH로 아무것도 못 받았습니다 — 키·보안그룹(ssh_cidr)·인스턴스 상태를 확인하세요."
  echo "== 실패 $FAIL건 =="
  exit 1
fi
sect() { sed -n "/^@@$1$/,/^@@/p" <<< "$remote" | sed '1d;$d' | tr -d '\r' | head -1; }

# ── 1. 앱 코드가 로컬 HEAD와 같은가 (이 스크립트의 존재 이유) ────────────────
# 파일 목록 해시라 파일이 늘거나 준 것도 잡는다. 컨테이너 WORKDIR이 /app이고
# 로컬은 backend/ 라서, 양쪽 다 'app' 상대경로로 재야 같은 값이 나온다.
# LC_ALL=C: 정렬 순서가 로케일 따라 달라지면 같은 코드가 다른 해시로 보인다.
local_hash=$(cd "$REPO_DIR/backend" && LC_ALL=C find app -name "*.py" | LC_ALL=C sort | xargs sha256sum | sha256sum | cut -d' ' -f1)
remote_hash=$(sect HASH)
if [ -z "$remote_hash" ]; then
  fail "운영 앱 해시를 못 읽었습니다(컨테이너가 안 떠 있거나 exec이 막혔습니다)."
elif [ "$local_hash" = "$remote_hash" ]; then
  ok "앱 코드 일치 (${local_hash:0:12}) — 로컬 HEAD가 실제로 서빙되고 있다"
else
  fail "앱 코드 불일치 — 운영 ${remote_hash:0:12} ≠ 로컬 ${local_hash:0:12}"
  echo "       보냈지만 재빌드가 안 됐거나(가장 흔함), 다른 커밋이 떠 있습니다."
  echo "       ssh -i $SSH_KEY ec2-user@$DNS 'cd ~/blog && sudo docker compose -f docker-compose.prod.yml up -d --build'"
fi
# 커밋과 대조는 워킹트리가 깨끗할 때만 뜻이 있다(더러우면 해시는 HEAD가 아니라 지금 파일이다).
if [ -n "$(cd "$REPO_DIR" && git status --porcelain -- backend/app 2>/dev/null)" ]; then
  info "backend/app 에 커밋 안 된 변경이 있습니다 — 위 '로컬'은 HEAD가 아니라 워킹트리입니다."
fi

# ── 2. 마이그레이션이 실제로 붙었는가 ───────────────────────────────────────
# 2026-08-10에 '기동하면 자동 적용'이 거짓이던 자리. 로컬 head는 alembic 없이 구한다
# (이 개발환경엔 파이썬 패키지가 없다 — down_revision으로 지목되지 않는 revision이 head다).
local_head=$(cd "$REPO_DIR/backend/alembic/versions" && python3 - <<'PY'
import re, pathlib
revs, downs = {}, set()
for f in pathlib.Path('.').glob('*.py'):
    t = f.read_text(encoding='utf-8')
    r = re.search(r'^revision(?::\s*str)?\s*=\s*["\']([0-9a-f]+)["\']', t, re.M)
    # 타입 주석은 **같은 줄**에만 있다. `[^=]*`로 두면 개행까지 먹어서, 파일 위쪽
    # 주석에 `down_revision:` 같은 글자가 있으면 거기서 시작해 저 아래 `revision =`
    # 까지 한 덩어리로 매칭된다 — 그러면 그 파일이 **자기 자신을 down으로 가리키는**
    # 것으로 세어져 head가 사라지고 "MULTI:"(빈 목록)가 뜬다. 2026-08-19에 실제로
    # 겪었고, 증상이 '병합이 필요합니다'라 원인과 전혀 안 닮았다.
    d = re.findall(r'^down_revision(?::[^=\n]*)?\s*=\s*["\']([0-9a-f]+)["\']', t, re.M)
    if r: revs[r.group(1)] = f.name
    downs.update(d)
heads = sorted(set(revs) - downs)
print(heads[0] if len(heads) == 1 else "MULTI:" + ",".join(heads))
PY
)
remote_head=$(sect ALEMBIC)
if [ -z "$remote_head" ]; then
  fail "운영 alembic 리비전을 못 읽었습니다."
elif [[ "$local_head" == MULTI:* ]]; then
  fail "로컬 마이그레이션 head가 여러 개입니다($local_head) — 병합이 필요합니다."
elif [ "$local_head" = "$remote_head" ]; then
  ok "마이그레이션 최신 ($remote_head)"
else
  fail "마이그레이션 불일치 — 운영 $remote_head ≠ 로컬 head $local_head"
  echo "       이미지에 그 리비전 파일이 없으면 몇 번을 켜도 안 붙습니다(2026-08-10에 겪음). 재빌드가 답입니다."
fi

# ── 3. 컨테이너가 비-root로 도는가 ──────────────────────────────────────────
uid=$(sect UID)
[ "$uid" = "10001" ] && ok "비-root 실행 (uid=$uid)" || fail "uid가 10001이 아닙니다: '${uid:-못 읽음}'"

# ── 4. 헬스체크 ─────────────────────────────────────────────────────────────
health=$(sect HEALTH)
[ "$health" = "healthy" ] && ok "컨테이너 healthy" || fail "컨테이너 상태 '${health:-못 읽음}'"

# ── 5. 오리진 가드 (헤더 없는 직접 요청은 403이어야 한다) ────────────────────
# **서버 안에서 잰다.** 밖에서 재면 보안그룹이 8000을 CloudFront 프리픽스에만 열어둬서
# 타임아웃(000)이 나고, 그걸 보고 "가드가 깨졌나"를 판단할 수 없다(2026-08-14에 헷갈렸다).
guard=$(sect GUARD)
[ "$guard" = "403" ] && ok "오리진 시크릿 가드 정상 (헤더 없이 403)" \
  || fail "오리진 직접 요청이 403이 아닙니다: '${guard:-못 읽음}' — 우회 경로가 열렸을 수 있습니다."

# ── 6. 최근 오류 로그 ───────────────────────────────────────────────────────
errors=$(sect ERRORS)
if [ -z "$errors" ]; then
  fail "로그를 못 읽었습니다."
elif [ "$errors" -eq 0 ]; then
  ok "최근 10분 오류 로그 0건"
else
  fail "최근 10분 오류 로그 $errors 줄 — 눈으로 확인하세요: $COMPOSE logs backend --since 10m"
fi

# ── 7. 공개 경로가 실제로 그 코드를 태우는가 ────────────────────────────────
# 여기까지는 전부 '서버 안'에서 잰 것이다. 사용자가 닿는 길(CloudFront)이 막혀 있으면
# 위가 다 초록이어도 아무도 그 코드를 못 쓴다.
cf=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$CF_URL/api/status")
if [ "$cf" = "200" ]; then
  ok "공개 /api/status 200 (CloudFront → 오리진 경로 살아 있음)"
else
  # 200이 아닐 때 **주차인지 고장인지**를 추측하지 않는다. CloudFront에 실제로 뭐가
  # 꽂혀 있는지 물어본다. 주차(오리진이 S3로 바뀐 상태)에서는 504가 오기도 하고
  # 타임아웃(000)이 오기도 한다 — 같은 날 둘 다 봤다. 코드로 구분할 수 없는 걸
  # 코드가 아는 척하면, 진짜 장애가 "정상입니다"로 지나간다.
  origin=$(aws cloudfront get-distribution-config --id "$CF_DIST_ID" \
    --query "DistributionConfig.Origins.Items[?Id=='api-backend'].DomainName | [0]" \
    --output text 2>/dev/null)
  if [ -z "$origin" ] || [ "$origin" = "None" ]; then
    fail "공개 /api/status 가 $cf 이고, CloudFront 오리진 설정도 못 읽었습니다."
  elif [ "$origin" = "$PARKED_ORIGIN" ]; then
    info "공개 /api/status $cf — 오리진이 **주차**돼 있습니다(정지 절차의 정상 상태)."
    info "  공개 사이트를 봐야 하면: terraform apply -var=\"backend_origin_dns=$DNS\""
  elif [ "$origin" != "$DNS" ]; then
    # ⚠️ '이 서버가 아니다'를 주차로 읽으면 안 된다. 주차 자리는 **정해진 한 값**이고,
    # 그 밖의 값은 옛 인스턴스 주소가 남은 것이다(콘솔에서 껐다 켜면 이렇게 된다).
    # 그건 정상이 아니라 /api 전체가 죽은 상태이고, 게다가 stop_server.sh 머리말이
    # 경고하는 dangling origin — 그 주소를 제3자가 새로 받았을 수 있다.
    fail "오리진이 이 서버도 주차 자리도 아닙니다: $origin"
    echo "       옛 인스턴스 주소가 남아 있습니다(dangling origin). 즉시 고치세요:"
    echo "       terraform -chdir=terraform apply -var=\"backend_origin_dns=$DNS\""
  elif [ "$cf" = "403" ]; then
    # 403은 '못 닿았다'가 아니다 — 닿았는데 거절당한 것이다. 원인을 안 적어두면
    # 주차 해제부터 시도하게 되는데 이미 풀려 있어서 아무것도 안 바뀐다(watch.sh와 같은 함정).
    fail "공개 /api/status 403 — 오리진에는 닿았는데 거절당했습니다."
    echo "       **오리진 공유 시크릿 불일치**가 가장 유력합니다 — CloudFront의 X-Origin-Secret과"
    echo "       서버 .env의 ORIGIN_SECRET이 다릅니다. 가장 흔한 원인: terraform.tfvars 없이 apply."
    echo "       자세한 절차는 RECOVERY.md의 origin_secret 항목."
  else
    fail "공개 /api/status 가 $cf 입니다 — 오리진은 이 서버($DNS)를 가리키는데 안 닿습니다."
  fi
fi

echo
if [ "$FAIL" -eq 0 ]; then
  echo "== 배포 검증 통과 =="
else
  echo "== 실패 $FAIL건 =="
  exit 1
fi

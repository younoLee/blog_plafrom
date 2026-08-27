#!/usr/bin/env bash
# 복구 런북(RECOVERY.md)이 코드와 어긋났는지 검사한다. 자격증명 없이, 정적으로.
#
# 왜 필요한가 — 2026-07-27 DR 게임데이의 첫 블로커(F1):
#
#   Error: No value for required variable
#     on ecs.tf line 9: variable "backend_image_tag"
#
# 07-24 ECS 이전이 기본값 없는 필수 변수를 추가했다. ECS는 그날 tear down했지만 변수는
# 남았고, **아무도 DR 경로를 다시 밟지 않아서** 재해 복구의 첫 명령이 죽는 상태로 3일이
# 지났다. 진짜 재해 때 처음 발견했다면 그 3일치 당황이 복구 시간에 그대로 붙는다.
#
# 왜 `terraform plan`이 아닌가 — plan은 이 부류를 확실히 잡지만 AWS 자격증명과 **상태
# 읽기**가 필요하다. 그런데 이 저장소의 tfstate에는 시크릿이 들어 있다(origin_secret,
# ssh_cidr 등). CI에 state 읽기 권한을 주는 것은 "GitHub이 침해되면 운영 시크릿도 같이
# 나간다"는 뜻이라, 잡으려는 문제보다 비싼 거래다. 그래서 같은 부류를 정적으로 잡는다.
# (`terraform validate`는 이걸 못 잡는다 — 변수 '값'을 평가하지 않기 때문이다.)
#
# 검사 다섯:
#   A. 기본값 없는 변수가 런북의 tfvars 블록에 있는가   ← F1 그 자체
#   B. 런북이 부르는 스크립트가 실제로 있는가
#   C. 런북의 `-target=` 주소가 실제 리소스인가
#   D. 스크립트·terraform·런북에 INSTANCE_ID가 **박혀 있지 않은가**  ← 태그 조회 강제
#   E. 로컬 .env 템플릿이 compose 치환 변수를 전부 담는가  ← 조용히 꺼지는 기능 방지
#   F. 런북의 tar 목록이 배포 스크립트의 것을 담는가        ← 재건 이미지에 파일 누락 방지
#   G. 런북이 재조립 시 필수 키를 전부 나열하는가           ← .env 한 줄 누락 방지
#
# ⚠️ **이 검사가 안 보는 것** (초록이 "런북이 맞다"를 뜻하지 않는다):
#   · 절차의 **순서**가 옳은지. B는 스크립트 존재만, C는 주소 유효성만 본다.
#   · 런북에 **아예 없는 것**. 없는 것은 어긋날 수 없다 — 2026-08-26까지 VAPID가
#     RECOVERY.md에 0건이었는데 이 검사는 4주 내내 초록이었다. 새 시크릿·새 절차가
#     생겼을 때 그것이 런북에 들어갔는지는 **사람이 훈련에서** 확인해야 한다.
#   · 명령이 실제로 도는지. 정적 검사라 실행하지 않는다.
#
# ⚠️ 여기 있던 D 설명은 2026-08-11까지 **폐기된 절차를 현재 규칙으로** 서술하고 있었다:
#   "스크립트들의 INSTANCE_ID가 전부 같은가 / 재건하면 5곳을 손으로 고쳐야 한다".
# 그건 08-10 이전 이야기다. 지금 D는 **정반대**를 검사한다 — 박아뒀으면 실패시키고,
# 5개 스크립트가 전부 `INSTANCE_ID=$(resolve_instance_id)`를 쓰는지 본다(:139~:174).
# 손으로 고칠 자리가 아예 없어졌다(RECOVERY.md:149-151도 그렇게 적는다).
# 재해 복구 중 이 헤더를 먼저 읽으면 **있지도 않은 '5곳 손수정'을 찾아 헤맨다** —
# 07-27 게임데이가 "RTO 42분 중 20분이 문서가 틀린 자리"라고 결론 낸 그 부류다.
#
# D를 애초에 넣은 이유(그대로 유효): 잘못된 인스턴스를 보는 건 **조용한 실패**라
# 정지도 훈련도 감시도 아무 말 없이 엉뚱한 대상을 본다 — 사고 날 때까지 안 보인다.
#
# 사용:
#   scripts/check_runbook_drift.sh     # 실패하면 exit 1 (CI 게이트)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNBOOK="$ROOT/RECOVERY.md"
TF_DIR="$ROOT/terraform"

fail=0
say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
bad() { printf '  ❌ %s\n' "$*"; fail=1; }
ok() { printf '  ✅ %s\n' "$*"; }

[ -f "$RUNBOOK" ] || { echo "RECOVERY.md가 없습니다: $RUNBOOK" >&2; exit 1; }

# ── A. 기본값 없는 변수 ⇒ 런북의 tfvars 블록에 있어야 한다 ──────────────────
# 둘 중 하나면 된다: 기본값을 주거나(그럼 여기 안 걸림), 런북에 적거나.
# F1의 수정은 전자였고, ssh_cidr은 후자다(일부러 기본값을 안 준다 — 값이 없으면
# apply가 실패하는 게 SSH 대역이 0.0.0.0/0으로 조용히 넓어지는 것보다 낫다).
say "A. 기본값 없는 terraform 변수가 런북에 적혀 있는가"

# HCL을 손으로 파싱한다. 그래서 **파서가 전부 봤는지 스스로 검증**한다(아래 decl 대조) —
# 2026-07-28 심층검사에서 예전 awk가 한 줄짜리 블록(`variable "x" { type = string }`)을
# 통째로 놓치는 게 드러났다. `next`가 여는 줄을 건너뛰고 닫는 중괄호를 `^}`로만 찾아서,
# 여는 줄에서 이미 닫히는 블록은 영영 안 나왔다. 하필 그게 F1(기본값 없는 필수 변수)
# 그 자체라, 재발 방지용 검사가 재발을 못 잡는 상태였다.
# 지금은 중괄호 깊이로 블록 끝을 찾고, default는 줄 어디에 있든 잡는다.
parse_vars() {
  awk '
    !inblk && /^[[:space:]]*variable[[:space:]]+"/ {
      name = $0
      sub(/^[[:space:]]*variable[[:space:]]+"/, "", name)
      sub(/".*/, "", name)
      has = 0; depth = 0; inblk = 1
    }
    inblk {
      line = $0
      # `{` 바로 뒤나 줄 앞에 오는 default 만 인정한다(문자열 안의 단어에 안 걸리게)
      if (line ~ /(^[[:space:]]*|\{[[:space:]]*)default[[:space:]]*=/) has = 1
      o = gsub(/\{/, "{", line)
      c = gsub(/\}/, "}", line)
      depth += o - c
      if (depth <= 0) { print (has ? "H" : "R") " " name; inblk = 0 }
    }
  ' "$TF_DIR"/*.tf
}

parsed_vars=$(parse_vars)
required_vars=$(printf '%s\n' "$parsed_vars" | awk '$1=="R" {print $2}' | sort)

# 파서가 선언을 하나라도 놓쳤으면 이 검사 결과를 믿을 수 없다. 조용히 적게 검사하고
# 통과하는 것이 이 스크립트가 막으려는 실패 그 자체이므로, 세어서 대조한다.
decl_count=$(grep -chE '^[[:space:]]*variable[[:space:]]+"' "$TF_DIR"/*.tf | awk '{s+=$1} END{print s+0}')
seen_count=$(printf '%s\n' "$parsed_vars" | grep -c . || true)
if [ "$decl_count" -ne "$seen_count" ]; then
  bad "terraform 변수 파서가 선언 ${decl_count}개 중 ${seen_count}개만 읽었습니다 — 이 검사 결과를 믿을 수 없습니다."
fi

# 런북의 tfvars 히어독 안쪽만 본다(문서 다른 곳의 언급은 근거로 안 친다 —
# "어딘가 적혀 있다"가 아니라 "복사해 붙이면 되는 자리에 있다"가 필요하다).
tfvars_block=$(awk '/<<.?TFVARS.?$/{f=1;next} /^TFVARS$/{f=0} f' "$RUNBOOK")
[ -n "$tfvars_block" ] || bad "런북에서 tfvars 히어독 블록(<<'TFVARS' … TFVARS)을 못 찾았습니다"

n=0
while IFS= read -r v; do
  [ -n "$v" ] || continue
  n=$((n + 1))
  # ${v} 로 감싸야 한다 — "$v[[:space:]]" 는 셸이 배열 확장으로 읽는다(SC1087).
  if grep -qE "^[[:space:]]*${v}[[:space:]]*=" <<<"$tfvars_block"; then
    ok "$v — 런북 tfvars 블록에 있음"
  else
    bad "$v — 기본값도 없고 런북 tfvars 블록에도 없음. 재해 복구 1단계가 'No value for required variable'로 죽습니다. 기본값을 주거나 RECOVERY.md의 tfvars 블록에 추가하세요."
  fi
done <<<"$required_vars"
echo "     (기본값 없는 변수 $n개 검사)"

# ── B. 런북이 부르는 스크립트가 실제로 있는가 ───────────────────────────────
say "B. 런북이 부르는 스크립트가 실제로 있는가"
n=0
while IFS= read -r s; do
  [ -n "$s" ] || continue
  n=$((n + 1))
  if [ -f "$ROOT/$s" ]; then ok "$s"; else bad "$s — 런북이 부르는데 파일이 없습니다"; fi
done < <(grep -oE 'scripts/[A-Za-z0-9_-]+\.sh' "$RUNBOOK" | sort -u)
# 0개면 통과가 아니라 이상 신호다. 런북이 스크립트를 하나도 안 부른다는 건 문서가
# 통째로 바뀌었다는 뜻이고, 그걸 초록으로 넘기면 검사가 있으나 마나다.
[ "$n" -gt 0 ] || bad "런북이 부르는 스크립트가 0개입니다 — 문서가 바뀌었거나 패턴이 어긋났습니다."
echo "     (참조 $n개 검사)"

# ── C. 런북의 -target= 주소가 실제 리소스인가 ───────────────────────────────
# `-target=aws_instance.backend` 같은 것. 리소스 이름이 바뀌면 복구 1단계가
# "no matching resources"로 아무것도 안 하고 성공한 척한다.
say "C. 런북의 -target= 주소가 실제 리소스인가"
n=0
while IFS= read -r addr; do
  [ -n "$addr" ] || continue
  n=$((n + 1))
  type=${addr%%.*}
  name=${addr#*.}
  if grep -qE "^resource \"$type\" \"$name\"" "$TF_DIR"/*.tf; then
    ok "$addr"
  else
    bad "$addr — 런북이 -target으로 쓰는데 terraform에 그런 리소스가 없습니다"
  fi
done < <(grep -oE '\-target=[a-z0-9_]+\.[a-z0-9_]+' "$RUNBOOK" | sed 's/-target=//' | sort -u)
[ "$n" -gt 0 ] || bad "런북에 -target 주소가 0개입니다 — 복구 절차의 범위 좁히기가 사라졌거나 표기가 바뀌었습니다."
echo "     (-target 주소 $n개 검사)"

# ── D. 스크립트가 인스턴스 ID를 박아두지 않았는가 ───────────────────────────
say "D. 스크립트가 인스턴스 ID를 박아두지 않았는가"
# 2026-08-10 이전의 이 검사는 **"5개 파일의 INSTANCE_ID가 전부 같은가"**였다.
# 그건 재건할 때마다 5곳을 손으로 고치는 절차를 **전제한** 검사다 — 즉 DR 결함 F5를
# 없애는 게 아니라 F5를 반만 지키는지 감시하고 있었다. 태그 조회(scripts/lib/ec2.sh)로
# 바꿔 절차 자체를 없앴으므로, 이제 볼 것은 '같은가'가 아니라 **'박혀 있는가'**다.
hard=$(grep -nE '^[[:space:]]*INSTANCE_ID=[[:space:]]*["'"'"']?i-' \
  "$ROOT"/scripts/*.sh "$ROOT"/scripts/lib/*.sh 2>/dev/null || true)
if [ -n "$hard" ]; then
  bad "스크립트에 인스턴스 ID가 박혀 있습니다 — 재건하면 이 줄들이 전부 거짓이 됩니다:"
  printf '%s\n' "$hard" | sed 's/^/       /'
else
  ok "박힌 인스턴스 ID 없음 (태그로 찾는다)"
fi

# 박힌 게 없다는 것만으로는 부족하다 — 조회를 **쓰는지**도 봐야 한다.
# 그러지 않으면 누가 INSTANCE_ID 줄을 지우기만 해도 이 검사가 초록이 된다.
if [ ! -f "$ROOT/scripts/lib/ec2.sh" ]; then
  bad "scripts/lib/ec2.sh가 없습니다 — 태그 조회의 단일 출처가 사라졌습니다."
else
  miss=""
  for s in stop_server restore_drill env_escrow watch deploy_backend; do
    if [ ! -f "$ROOT/scripts/$s.sh" ]; then
      miss="$miss $s.sh(파일없음)"
    # **호출**을 본다. 예전엔 `grep -q 'resolve_instance_id'`였는데 그건 주석에도 매치해서,
    # 누가 호출을 지우고 "resolve_instance_id를 쓴다"는 주석만 남겨도 초록이었다
    # (2026-08-10 심층검사). 대입 형태까지 요구하면 그 통로가 닫힌다.
    elif ! grep -qE '^[[:space:]]*INSTANCE_ID=\$\(resolve_instance_id\)' "$ROOT/scripts/$s.sh"; then
      miss="$miss $s.sh"
    fi
  done
  if [ -n "$miss" ]; then
    bad "인스턴스를 다루는데 태그 조회를 안 쓰는 스크립트:$miss"
  else
    ok "스크립트 5개가 전부 resolve_instance_id로 찾는다"
  fi
fi

# 2026-08-27 DR 게임데이: 위 둘을 통과하는데도 **박힌 ID가 살아 있었다.**
# terraform/variables.tf:14 가 "EC2 켤 때" 절차의 명령으로 i-06da19f44d1f38eff 를
# 들고 있었고, 그 인스턴스는 이미 존재하지 않았다(InvalidInstanceID.NotFound).
# 위 검사가 `scripts/` 만 보기 때문이다 — **검사가 대상을 안 보면 그 자리는 없는 것과
# 같다.** 07-27 이 F5 로 스크립트를 고칠 때 절차를 적어둔 주석은 아무도 안 봤다.
# 그대로 따르면 조회가 실패해 DNS 가 비고, 그러면 오리진 주차 해제가 주차로 뒤집힌다.
#
# 대상은 terraform/ 과 RECOVERY.md 다. 코드가 아니라 **주석과 문서**를 보는 검사다.
# 개발일지(content/)와 docs/ 의 훈련 기록은 뺀다 — 그건 그날의 사실을 적은 것이라
# 낡는 게 정상이고, 절차로 읽히지 않는다.
# 앞에 글자가 붙은 것은 인스턴스 ID가 아니다 — `ami-0436b3a61a7a7e22a` 안의
# `i-0436b3a61a7a7e22a` 가 그대로 매치돼서 ec2.tf 의 AMI 를 오탐했다(만들자마자 걸렸다).
stale=$(grep -rnE '(^|[^[:alnum:]-])i-0[0-9a-f]{16}' "$ROOT"/terraform/ "$ROOT"/RECOVERY.md 2>/dev/null || true)
if [ -n "$stale" ]; then
  bad "terraform/ 또는 런북에 인스턴스 ID가 박혀 있습니다 — 재건하면 거짓이 됩니다:"
  printf '%s\n' "$stale" | sed 's/^/       /'
  echo "       → 태그 조회로 바꾸세요: --filters \"Name=tag:Name,Values=blog-backend\"" >&2
else
  ok "terraform/ 과 런북에도 박힌 인스턴스 ID 없음"
fi

# ── E. 로컬 .env 템플릿이 compose가 치환하는 변수를 전부 담고 있는가 ────────
# 왜 — 2026-08-10 복원훈련이 **운영** 템플릿의 VAPID 누락을 잡아 고쳤는데,
# **로컬 템플릿(.env.example)은 안 쓸렸다.** 거기엔 "여기 넣을 건 딱 두 개다"라고
# 적혀 있었고 실제 치환 변수는 다섯이었다 — 누락이 아니라 **오정보**라, 읽은 사람은
# 더 찾지 않고 푸시가 조용히 꺼진 채로 개발한다. (2026-08-11 동료 리뷰)
# 운영 쪽은 env_escrow.sh가 감시하지만 로컬 쪽은 보는 장치가 0개였다.
say "E. 로컬 .env 템플릿이 compose 치환 변수를 전부 담는가"
compose_vars=$(grep -oP '\$\{\K[A-Z_]+' "$ROOT/docker-compose.yml" | sort -u)
tmpl_vars=$(grep -oP '^\K[A-Z_]+(?==)' "$ROOT/.env.example" | sort -u)
missing=$(comm -23 <(printf '%s\n' "$compose_vars") <(printf '%s\n' "$tmpl_vars"))
if [ -n "$missing" ]; then
  bad "compose가 치환하는데 .env.example에 없는 변수: $(printf '%s' "$missing" | tr '\n' ' ')"
  echo "     안 적으면 그 기능이 로컬에서 조용히 꺼진 채로 개발하게 됩니다."
else
  ok "치환 변수 $(printf '%s\n' "$compose_vars" | wc -l)개가 전부 템플릿에 있음"
fi

# ── F. 런북의 tar 목록 ⊇ 배포 스크립트의 tar 목록 ──────────────────────────
# 왜 — 2026-08-26에 실제로 어긋나 있었다. deploy_backend.sh는 `scripts`를 tar에 넣고
# 그 이유까지 적어놨는데(가입이 초대제라 계정은 scripts/create_user.py로만 만든다),
# RECOVERY.md의 재건 절차는 그 인자가 빠져 있었다. 재건하면 **서버는 뜨고 /api/status도
# 200인데 첫 계정을 만들 수단이 이미지에 없다.** 07-27 게임데이는 초대제(08-07) 이전이라
# 이 자리를 밟을 수 없었다 — 즉 훈련으로는 못 잡고 이 검사만 잡을 수 있는 종류다.
say "F. 런북의 tar 목록이 배포 스크립트의 것을 담는가"
# `tar czf ... -C <경로> \` 로 줄이 끊기고 다음 줄에 항목이 오는 형태를 둘 다 처리한다.
# 역슬래시 줄바꿈을 먼저 이어 붙인 뒤 `-C <경로>` 뒤쪽만 남긴다.
# grep 실패가 이 스크립트를 죽이면 안 된다(set -e) — 못 찾은 것도 판정 대상이다.
tar_items() {  # $1=파일
  sed -e ':a' -e '/\\$/{N;s/\\\n//;ba' -e '}' "$1" \
    | grep -m1 -oE 'tar czf .*-C [^ ]+ .*' \
    | sed -E 's/.*-C [^ ]+ //; s/"//g' \
    | tr ' ' '\n' | grep -v '^$' | LC_ALL=C sort -u || true
}
dep_items=$(tar_items "$ROOT/scripts/deploy_backend.sh")
run_items=$(tar_items "$ROOT/RECOVERY.md")
if [ -z "$dep_items" ] || [ -z "$run_items" ]; then
  bad "tar 목록을 못 찾았습니다 (배포 항목수=$(printf '%s' "$dep_items" | grep -c . || true) / 런북=$(printf '%s' "$run_items" | grep -c . || true))."
  echo "     둘 중 하나의 형태가 바뀌었으면 이 검사의 tar_items()를 같이 고쳐야 합니다."
else
  lack=$(LC_ALL=C comm -23 <(printf '%s\n' "$dep_items") <(printf '%s\n' "$run_items") | tr '\n' ' ')
  if [ -n "$lack" ]; then
    bad "배포는 tar에 넣는데 런북은 빠뜨린 것: $lack"
    echo "     재건된 이미지에 그 파일이 없습니다. 프로드는 코드 볼륨 마운트가 없어"
    echo "     이미지에 구워진 것만 있습니다 — 재해 한복판에서야 알게 됩니다."
  else
    ok "런북 tar 목록이 배포의 것을 전부 담음"
  fi
fi

# ── G. 런북이 재조립 시 필수 키를 전부 나열하는가 ──────────────────────────
# 왜 — 시나리오 B 4단계는 .env를 에스크로에서 되살린다. 거기서 한 줄이 빠지는 것이
# 이 절차의 주된 실패 모양인데, 빠져도 **앱이 정상 기동하는** 키가 여럿이다
# (VAPID를 빠뜨리면 푸시만 조용히 꺼진다 — 경보 없음). 그래서 목록이 런북에 있어야 한다.
# 이 목록은 검사 G 와 H-4 가 함께 쓴다 — 이 저장소의 **운영 키 목록**이다.
# 두 곳에 복붙하면 갈라진다(2026-08-27 카오스 훈련에서 그 병을 세 파일에서 봤다).
say "G. 런북이 재조립 필수 키를 나열하는가"
# 2026-08-27 훈련에서 운영 .env 를 실제로 세어(키 21개) 넷을 더했다 — 전부 실재하는데
# 이 목록에 없었고, 그래서 RECOVERY.md 에 없어도 검사가 초록이었다.
# SMTP 자격증명과 DATABASE_URL 이 표에서 통째로 빠져 있던 게 그렇게 4주를 갔다.
need_keys="SECRET_KEY ORIGIN_SECRET S3_BUCKET PAYMENTS_REQUIRE_LIVE DB_PASSWORD LLM_ENCRYPTION_KEY VAPID_PUBLIC_KEY VAPID_PRIVATE_KEY VAPID_SUBJECT ANTHROPIC_API_KEY DATABASE_URL SMTP_USER SMTP_PASSWORD"
miss_keys=""
for k in $need_keys; do
  grep -q "$k" "$ROOT/RECOVERY.md" || miss_keys="$miss_keys $k"
done
if [ -n "$miss_keys" ]; then
  bad "RECOVERY.md가 언급하지 않는 필수 키:$miss_keys"
  echo "     없는 것은 어긋날 수 없습니다 — 재조립에서 통째로 빠집니다."
else
  ok "필수 키 $(printf '%s' "$need_keys" | wc -w)개가 전부 런북에 있음"
fi

# ── H. 사고 대응 런북(docs/incident-response.md)이 운영에서 실제로 도는가 ────
# **왜 이 검사가 생겼나 (2026-08-27).** 이 파일은 지금까지 RECOVERY.md 하나만 봤다.
# 08-26에 IR 런북에 로테이션 절차 넷(3-5~3-8)을 새로 썼는데, 그 문서가 검사 대상이
# 아니라서 넷 다 깨진 채로 CI 가 초록이었다. 훈련에서 밟아보니 3-5 한 절에서만 셋이
# 나왔다 — 파일 위 :31 주석이 RECOVERY.md 에 대해 적어둔 것과 **글자 그대로 같은 모양**이다.
# 검사 대상을 목록으로 들고 있으면 새로 생긴 것이 조용히 빠진다. 그래서 목록을 늘린다.
#
# 여기서 보는 것은 '문장이 맞나'가 아니라 **'그대로 쳤을 때 돌아가나'** 다.
#
# ⚠️ 이 절의 모든 파이프라인에 `|| true` 를 붙인다. 이 파일은 `set -euo pipefail` 이라
#    grep 이 0건이면 **스크립트가 그 자리에서 조용히 죽는다** — 처음 쓸 때 실제로
#    그래서 H-3·H-4 가 안 돌고 출력만 끊겼다. 검사기가 조용히 멈추는 건 통과처럼 읽힌다.
# **아직 실재하지 않는 키.** 절차는 미리 써두되 사고 중에 쫓지는 않는다.
# 산문으로 판별하지 않는다 — 문장을 조금만 고쳐도 면제가 조용히 풀리거나 조용히 걸린다.
# 목록으로 두면 지우는 순간 검사가 바로 말한다.
#   TOSS_SECRET_KEY — 결제가 라이브가 아니라 코드 기본값(테스트키)으로 돈다.
#                     PAYMENTS_REQUIRE_LIVE=true 가 결제 자체를 503으로 막는다.
#                     라이브 전환 시 이 줄에서 지우고 need_keys 로 옮긴다(IR 3-7 참고).
not_yet="TOSS_SECRET_KEY"
IR="$ROOT/docs/incident-response.md"
say "H. 사고 대응 런북이 운영에서 그대로 도는가"
if [ ! -f "$IR" ]; then
  bad "docs/incident-response.md 가 없습니다"
else
  # H-1. 부르는 스크립트가 **그 명령이 도는 자리에** 실재하는가.
  #      경로 하나가 문맥에 따라 두 곳을 가리킨다:
  #        · `docker compose exec backend python scripts/X.py` → 컨테이너 /app/scripts
  #          = 저장소의 backend/scripts/ (이미지에 구워지는 것)
  #        · 그냥 `scripts/X.sh`                                → 워크스테이션의 저장소 scripts/
  #      08-27 훈련이 잡은 3-6 이 정확히 이 틈이다 — reencrypt_llm_keys.py 는 저장소
  #      scripts/ 에 있는데 런북은 컨테이너 안에서 부르라고 적었고, 이미지에는 없다.
  #      "파일이 있다"와 "거기서 부를 수 있다"는 다른 명제다.
  n=0
  # **전체 줄**을 읽는다. 예전엔 `grep -o` 로 매치만 뽑아서 같은 줄의 `docker compose`
  # 여부를 볼 수 없었고, 그래서 컨테이너 문맥 판별이 한 번도 발동하지 않았다
  # (backend/scripts/ 에 멀쩡히 있는 파일 둘을 "저장소에 없다"고 오탐했다).
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    for ref in $(printf '%s' "$line" | grep -oE '(scripts|backend/scripts)/[A-Za-z0-9_-]+\.(sh|py)' || true); do
      n=$((n + 1))
      if printf '%s' "$line" | grep -q 'docker compose.*exec'; then
        # 컨테이너 안에서 도는 명령 → 이미지에 구워지는 backend/scripts/ 를 본다
        base=${ref##*/}
        if [ -f "$ROOT/backend/scripts/$base" ]; then
          :
        elif [ -f "$ROOT/$ref" ]; then
          bad "$ref — 컨테이너 안에서 부르는데 **이미지에 없습니다**(저장소 $ref 에만 있고 backend/scripts/ 엔 없음)"
          echo "     08-27 훈련이 3-6 에서 실제로 밟은 자리입니다. '파일이 있다'와 '거기서 부를 수 있다'는 다릅니다."
        else
          bad "$ref — IR 런북이 부르는데 어디에도 없습니다"
        fi
      else
        [ -f "$ROOT/$ref" ] || bad "$ref — IR 런북이 부르는데 저장소에 없습니다"
      fi
    done
  # 백슬래시로 이어진 명령을 **한 줄로 합쳐서** 본다. 안 합치면 두 번째 줄에 있는
  # 스크립트 이름이 같은 줄의 `docker compose exec` 를 못 보고 워크스테이션 경로로
  # 오독된다(이 검사를 처음 쓸 때 실제로 그랬다 — 멀쩡한 3-5 를 빨간불로 만들었다).
  done < <(sed -e ':a' -e '/\\$/{N;s/\\\n//;ta' -e '}' "$IR" \
           | grep -nE '(scripts|backend/scripts)/[A-Za-z0-9_-]+\.(sh|py)' || true)
  if [ "$n" -gt 0 ]; then
    ok "부르는 스크립트 참조 $n건 검사"
  else
    bad "IR 런북이 부르는 스크립트가 0개입니다 — 패턴이 어긋났습니다"
  fi

  # H-2. docker compose 명령이 **운영 compose 파일을 지정하는가**
  #      운영 ~/blog 에는 docker-compose.yml 이 없고 docker-compose.prod.yml 만 있다.
  #      맨 `docker compose exec ...` 는 "no configuration file provided" 로 죽는다.
  #      08-27 훈련에서 3-5 의 세 명령이 전부 이 상태였다.
  bare=$(grep -nE '^[[:space:]]*(sudo )?docker compose ' "$IR" | grep -v 'docker-compose.prod.yml' || true)
  if [ -n "$bare" ]; then
    bad "compose 파일을 안 준 docker 명령 $(printf '%s\n' "$bare" | wc -l)줄 — 운영엔 docker-compose.yml 이 없어 그대로 치면 죽습니다"
    printf '%s\n' "$bare" | sed 's/^/       /'
  else
    ok "docker 명령이 전부 -f docker-compose.prod.yml 을 지정함"
  fi

  # H-3. psql 이 **운영 DB 이름**을 쓰는가
  #      운영 DATABASE_URL 의 DB 는 `postgres` 다(로컬 개발만 `blog`). 08-27 훈련에서
  #      3-5 의 정리 명령이 `-d blog` 라 'database "blog" does not exist' 로 죽었다.
  #      운영 .env 는 못 읽으므로 기준값을 박아둔다 — 바뀌면 이 줄도 같이 고쳐야 한다.
  PROD_DB=postgres
  wrongdb=$(grep -nE 'psql .* -d [A-Za-z0-9_]+' "$IR" | grep -v -- "-d $PROD_DB" || true)
  if [ -n "$wrongdb" ]; then
    bad "운영 DB 이름($PROD_DB)이 아닌 psql 명령 $(printf '%s\n' "$wrongdb" | wc -l)줄"
    printf '%s\n' "$wrongdb" | sed 's/^/       /'
  else
    ok "psql 명령이 전부 운영 DB($PROD_DB)를 가리킴"
  fi

  # H-4. 로테이션 절차가 다루는 키가 **실재하는가** (검사 G 의 IR 판)
  #      08-27 훈련: 3-7 이 TOSS_SECRET_KEY 를 교체하라는데 운영 .env 에 그 키가 없다
  #      (일부러 없다 — 결제가 라이브가 아니라 코드 기본값인 테스트키로 돈다).
  #      그런데 0장은 그 키를 유출자산 1순위로 세서, 사고 중에 없는 걸 쫓게 만든다.
  #      기준은 검사 G 의 need_keys — 이 저장소가 스스로 관리하는 **운영 키 목록**이다.
  #      .env.example 은 못 쓴다. 그건 **로컬 개발 템플릿**이라 운영 전용 시크릿
  #      (SECRET_KEY·DB_PASSWORD·SMTP_PASSWORD…)이 없는 게 정상이고, 그걸 기준으로 삼으면
  #      멀쩡한 절차 다섯이 한꺼번에 빨간불이 된다(처음 쓸 때 실제로 그랬다).
  irkeys=$(grep -oE '`[A-Z][A-Z_0-9]{3,}`' "$IR" | tr -d '`' | sort -u \
           | grep -vE '^(FAIL|WARN|DRIFT|CHECK|TODO|NOTE|HTTP|JSON|POST|HEAD|MULTI|BYOK)$' || true)
  ghost=""
  while IFS= read -r k; do
    [ -n "$k" ] || continue
    printf '%s\n' $not_yet | grep -qx "$k" && continue
    printf '%s\n' $need_keys | grep -qx "$k" || ghost="$ghost $k"
  done < <(printf '%s\n' "$irkeys")
  if [ -n "$ghost" ]; then
    bad "IR 런북이 다루는데 운영 키 목록(need_keys)에 없는 키:$ghost"
    echo "     둘 중 하나입니다 — 실재하지 않는 키라 절차를 지워야 하거나(사고 중에 없는 걸"
    echo "     쫓게 된다), 실재하는데 need_keys 가 낡았거나. 어느 쪽인지 정하고 한쪽을 고치세요."
  else
    ok "IR 런북이 언급하는 키가 전부 운영 키 목록에 있음"
  fi
fi

say "결과"
if [ "$fail" -eq 0 ]; then
  echo "  런북과 코드가 어긋난 곳 없음."
else
  echo "  위 ❌를 고치세요. 지금 고치는 비용 < 재해 중에 발견하는 비용." >&2
fi
exit "$fail"

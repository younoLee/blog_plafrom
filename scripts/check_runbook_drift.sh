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
# 검사 넷:
#   A. 기본값 없는 변수가 런북의 tfvars 블록에 있는가   ← F1 그 자체
#   B. 런북이 부르는 스크립트가 실제로 있는가
#   C. 런북의 `-target=` 주소가 실제 리소스인가
#   D. 스크립트들의 INSTANCE_ID가 전부 같은가          ← 부분 갱신 방지
#
# D를 넣은 이유: 인스턴스를 재건하면 ID가 바뀌고 스크립트 5곳을 손으로 고쳐야 한다.
# 3곳만 고치면 나머지는 **죽은 인스턴스를 조용히 들여다본다**. 정지도 훈련도 감시도
# 아무 말 없이 잘못된 대상을 본다 — 조용한 실패라 사고 날 때까지 안 보인다.
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

# ── D. 스크립트들의 INSTANCE_ID가 전부 같은가 ───────────────────────────────
say "D. 스크립트들의 INSTANCE_ID가 전부 같은가"
# 값 추출과 개수 세기를 **한 번의 추출에서** 뽑는다. 예전엔 둘이 다른 정규식이었고,
# 값 쪽만 따옴표를 못 읽었다. 그래서 `INSTANCE_ID="i-다른값"` 한 줄이 비교에서 사라지는데
# 개수에는 남아, "5개가 전부 같다"고 초록을 내면서 실제로는 4개만 본 상태가 됐다
# (2026-07-28 심층검사에서 재현). 따옴표를 허용하고, 못 읽은 줄이 있으면 실패시킨다.
raw_ids=$(grep -hE '^INSTANCE_ID=' "$ROOT"/scripts/*.sh || true)
if [ -z "$raw_ids" ]; then
  bad "스크립트에서 INSTANCE_ID를 한 건도 못 찾았습니다 — 패턴이 코드와 어긋났거나 스크립트 구조가 바뀌었습니다."
else
  id_lines=$(printf '%s\n' "$raw_ids" | grep -c . || true)
  ids=$(printf '%s\n' "$raw_ids" \
    | sed -E 's/^INSTANCE_ID=[[:space:]]*["'"'"']?([A-Za-z0-9-]+).*/\1/' | sort -u)
  parsed_lines=$(printf '%s\n' "$raw_ids" \
    | grep -cE '^INSTANCE_ID=[[:space:]]*["'"'"']?[A-Za-z0-9-]+' || true)
  uniq_count=$(printf '%s\n' "$ids" | grep -c . || true)

  if [ "$parsed_lines" -ne "$id_lines" ]; then
    bad "INSTANCE_ID 줄 ${id_lines}개 중 ${parsed_lines}개만 값을 읽었습니다 — 비교가 성립하지 않습니다:"
    grep -nE '^INSTANCE_ID=' "$ROOT"/scripts/*.sh | sed 's/^/       /'
  elif [ "$uniq_count" -eq 1 ]; then
    ok "스크립트 ${id_lines}개가 전부 같은 ID ($ids)"
  else
    bad "INSTANCE_ID가 갈렸습니다 — 인스턴스를 재건하고 일부만 고친 상태로 보입니다:"
    grep -nE '^INSTANCE_ID=' "$ROOT"/scripts/*.sh | sed 's/^/       /'
  fi
fi

say "결과"
if [ "$fail" -eq 0 ]; then
  echo "  런북과 코드가 어긋난 곳 없음."
else
  echo "  위 ❌를 고치세요. 지금 고치는 비용 < 재해 중에 발견하는 비용." >&2
fi
exit "$fail"

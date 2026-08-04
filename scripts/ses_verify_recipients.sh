#!/usr/bin/env bash
# SES 샌드박스에서 '받는 사람' 주소를 검증 ID로 등록한다.
#
# 왜 이게 필요한가 — SES 샌드박스는 **검증된 주소로만** 발송을 허용한다. 이 블로그는
# 2026-07-31에 뉴스레터를 폐지해서(docs/deep-inspection-20260731.md) 임의의 주소로
# 메일이 나가는 경로가 0이 됐다. 남은 메일은 전부 등록된 계정 주소로만 간다:
#   가입 인증(초대제라 사실상 잠김) · 비번 재설정 · 새 글 알림
# 초대제 블로그라 그 주소는 유한하다. 그래서 그 주소들만 검증하면 전부 동작한다.
#
# 2026-08-04: 프로덕션 액세스는 **종결**했다(두 번 신청·두 번 거절, 사유 비공개 →
# 샌드박스로 계속 운영하기로 결정. docs/ses-production-access.md). 즉 이건 승인까지의
# 임시 다리가 아니라 **이 블로그의 정식 수신자 등록 절차**다. 새 사람이 늘면 여기서 등록한다.
#
# 중요 — 등록은 절반이다. AWS가 그 주소로 확인 메일을 보내고, **주소 주인이 링크를
# 눌러야** 검증이 끝난다. 이 확인 메일은 AWS가 직접 보내므로 샌드박스 제한을 안 받는다.
# 그래서 이 스크립트는 '눌렀는지'까지 보여준다 — 등록만 하고 초록으로 치면
# 07-22 SES 건과 같은 착각(설정했다 ≠ 동작한다)을 반복하게 된다.
#
# 사용:
#   scripts/ses_verify_recipients.sh --status              # 지금 상태만 본다
#   scripts/ses_verify_recipients.sh a@x.com b@y.com ...   # 없는 것만 등록 + 상태 출력
#
# 되돌리기: aws sesv2 delete-email-identity --email-identity <주소>

set -euo pipefail

REGION="${AWS_REGION:-ap-northeast-2}"

BOLD=$'\033[1m'
OFF=$'\033[0m'
RED=$'\033[31m'
GREEN=$'\033[32m'
YELLOW=$'\033[33m'

say() { printf '\n%s%s%s\n' "$BOLD" "$1" "$OFF"; }
ok() { printf '  %s✅%s %s\n' "$GREEN" "$OFF" "$1"; }
pending() { printf '  %s⏳%s %s\n' "$YELLOW" "$OFF" "$1"; }
bad() { printf '  %s❌%s %s\n' "$RED" "$OFF" "$1"; }

if ! command -v aws >/dev/null 2>&1; then
    bad "aws CLI가 없다. 이 스크립트는 그것 없이는 아무것도 판단할 수 없다."
    exit 1
fi

# 계정이 아직 샌드박스인지부터. 프로덕션이면 이 스크립트 자체가 필요 없다.
account_state() {
    say "0. 계정 상태"
    local prod
    if ! prod=$(aws sesv2 get-account --region "$REGION" \
        --query 'ProductionAccessEnabled' --output text 2>/dev/null); then
        bad "SES 계정 정보를 못 읽었다 (자격증명·권한 확인). '문제 없음'이 아니라 '확인 못 함'이다."
        exit 1
    fi
    if [ "$prod" = "True" ]; then
        ok "프로덕션 액세스가 켜져 있다 — 받는 사람 주소 검증은 더 이상 필요 없다."
        exit 0
    fi
    pending "샌드박스 (검증된 주소로만 발송) → 아래 주소들이 검증돼야 메일이 닿는다"
}

# 이미 등록된 ID와 그 검증 여부. 한 번만 불러 재사용한다.
list_identities() {
    aws sesv2 list-email-identities --region "$REGION" \
        --query 'EmailIdentities[?IdentityType==`EMAIL_ADDRESS`].IdentityName' \
        --output text 2>/dev/null | tr '\t' '\n' | sed '/^$/d'
}

is_verified() {
    local addr="$1" v
    v=$(aws sesv2 get-email-identity --region "$REGION" --email-identity "$addr" \
        --query 'VerifiedForSendingStatus' --output text 2>/dev/null) || return 2
    [ "$v" = "True" ]
}

# 확인 메일이 절대 닿지 않을 주소를 미리 걸러낸다. 등록하면 영원히 '대기'로 남아
# 목록만 지저분해진다 (예: 데모 계정 demo@example.com).
is_undeliverable_domain() {
    case "${1##*@}" in
        example.com | example.org | example.net | localhost | test | *.test | *.invalid | *.local) return 0 ;;
        *) return 1 ;;
    esac
}

report() {
    say "현재 등록된 수신 주소"
    local any=0 waiting=0 addr
    while IFS= read -r addr; do
        [ -n "$addr" ] || continue
        any=1
        if is_verified "$addr"; then
            ok "$addr"
        else
            pending "$addr — 아직 링크를 안 눌렀다 (메일함·스팸함 확인)"
            waiting=$((waiting + 1))
        fi
    done < <(list_identities)

    if [ "$any" -eq 0 ]; then
        bad "등록된 주소가 하나도 없다 — 이 계정에서는 아무에게도 메일이 닿지 않는다."
    fi

    say "결과"
    if [ "$waiting" -gt 0 ]; then
        pending "확인 대기 ${waiting}건. 등록은 절반이다 — 주소 주인이 눌러야 끝난다."
    else
        ok "등록된 주소 전부 검증됨."
    fi
}

add_addresses() {
    say "1. 등록"
    local existing addr
    existing=$(list_identities)
    for addr in "$@"; do
        case "$addr" in
            *@*.*) ;;
            *)
                bad "$addr — 이메일 주소 형태가 아니다. 건너뛴다."
                continue
                ;;
        esac
        if is_undeliverable_domain "$addr"; then
            bad "$addr — 확인 메일이 닿지 않는 도메인이다. 등록하면 영원히 대기로 남는다. 건너뛴다."
            continue
        fi
        if printf '%s\n' "$existing" | grep -qxF "$addr"; then
            ok "$addr — 이미 등록돼 있다 (건드리지 않음)"
            continue
        fi
        if aws sesv2 create-email-identity --region "$REGION" \
            --email-identity "$addr" >/dev/null 2>&1; then
            pending "$addr — 등록함. AWS가 확인 메일을 보냈다. 주인이 링크를 눌러야 한다."
        else
            bad "$addr — 등록 실패 (권한·중복·한도 확인)"
        fi
    done
}

main() {
    account_state
    if [ "$#" -gt 0 ] && [ "$1" != "--status" ]; then
        add_addresses "$@"
    fi
    report
    say "다음"
    printf '  · 각 주소 주인이 AWS 확인 메일의 링크를 누른다\n'
    printf '  · 그다음 이 스크립트를 --status 로 다시 돌려 전부 초록인지 본다\n'
    printf '  · 초록이 된 주소에만 비번 재설정·새 글 알림이 실제로 닿는다\n'
}

main "$@"

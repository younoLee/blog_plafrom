# shellcheck shell=bash
# 실행 파일이 아니라 **읽히는 파일**이라 shebang이 없다. 그래서 shellcheck에게 셸을 알려준다
# (없으면 SC2148 error로 CI가 빨간불이 된다).
#
# 인스턴스 ID를 **태그로 찾는다.** 스크립트에 박아두지 않는다.
#
# 왜 이 파일이 생겼는가 — 2026-07-27 DR 게임데이 결함 F5.
# 그날 EC2를 진짜로 terminate하고 재건했는데, 새 인스턴스는 ID가 다르다.
# 그래서 stop_server·restore_drill·env_escrow·watch·deploy_backend **5개 파일의
# `INSTANCE_ID=` 줄을 손으로 바꿔야** 했다. 안 바꾸면 정지도 훈련도 감시도
# 존재하지 않는 인스턴스를 들여다본다(InvalidInstanceID.NotFound).
# 게임데이 결론이 **"RTO 42분 중 20분이 태그 뒤 공백 하나였다 — 복구 시간은 작업량이
# 아니라 문서가 틀린 자리에서 헤매는 시간이 지배한다"**였는데, 재건마다 5개 파일을
# 손으로 고치는 절차는 정확히 그 헤맴을 구조적으로 보장한다. 그래서 없앤다.
#
# 사용:
#   . "$(dirname "${BASH_SOURCE[0]}")/lib/ec2.sh"
#   INSTANCE_ID=$(resolve_instance_id)
#
# 탈출구: 환경변수 `INSTANCE_ID`가 이미 있으면 조회하지 않고 그대로 쓴다.
# 재해 중에 태그가 깨졌거나 인스턴스가 둘로 보일 때 사람이 끼어들 자리다.
#   INSTANCE_ID=i-0123... scripts/stop_server.sh

# 태그값을 바꿀 일이 생기면 여기 하나만 고친다(terraform의 aws_instance.backend Name 태그와 같아야 한다).
: "${INSTANCE_NAME_TAG:=blog-backend}"

resolve_instance_id() {
  # 사람이 명시했으면 그 값을 믿는다.
  if [ -n "${INSTANCE_ID:-}" ]; then
    printf '%s\n' "$INSTANCE_ID"
    return 0
  fi

  local region ids count
  region="${AWS_REGION:-${AWS_DEFAULT_REGION:-ap-northeast-2}}"

  # terminated·shutting-down은 뺀다. 재건 직후에는 옛 인스턴스가 아직 목록에 남아 있어서,
  # 넣어두면 "둘이 보인다"고 멈춰 서는 자리가 재해 한복판이 된다.
  if ! ids=$(aws ec2 describe-instances --region "$region" \
      --filters "Name=tag:Name,Values=$INSTANCE_NAME_TAG" \
                "Name=instance-state-name,Values=pending,running,stopping,stopped" \
      --query 'Reservations[].Instances[].InstanceId' --output text 2>&1); then
    echo "인스턴스 조회 실패 — 자격증명이나 ec2:DescribeInstances 권한을 확인하세요." >&2
    echo "  aws 응답: $ids" >&2
    return 1
  fi

  # --output text는 여러 건을 탭으로 한 줄에 준다. 공백으로 정규화해서 센다.
  ids=$(printf '%s' "$ids" | tr '\t\r\n' '   ' | tr -s ' ' | sed 's/^ *//; s/ *$//')
  count=$(printf '%s' "$ids" | wc -w)

  if [ "$count" -eq 0 ] || [ "$ids" = "None" ]; then
    echo "Name=$INSTANCE_NAME_TAG 태그로 인스턴스를 못 찾았습니다 (region=$region)." >&2
    # 2026-07-27에 여기서 20분을 잃었다. CLI가 태그값의 뒤 공백을 잘라내서,
    # 태그가 'blog-backend '이면 이 필터는 **오류 없이 0건**을 준다. 조용한 실패다.
    echo "  ⚠️ 태그값에 공백이 섞이면 오류 없이 0건이 나옵니다 — 콘솔에서 태그부터 확인하세요." >&2
    echo "  전체 목록: aws ec2 describe-instances --query 'Reservations[].Instances[].[InstanceId,State.Name,Tags[?Key==\`Name\`].Value|[0]]' --output text" >&2
    return 1
  fi

  if [ "$count" -gt 1 ]; then
    echo "Name=$INSTANCE_NAME_TAG 인스턴스가 ${count}개입니다: $ids" >&2
    echo "  어느 쪽인지 스크립트가 정할 수 없습니다. 지울 것을 지우거나 명시하세요:" >&2
    echo "    INSTANCE_ID=i-... $0" >&2
    return 1
  fi

  printf '%s\n' "$ids"
}

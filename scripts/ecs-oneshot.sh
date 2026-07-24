#!/usr/bin/env bash
# ECS 일회성 태스크 실행기 — 백엔드 태스크 정의로 임의 명령을 한 번 돌리고 결과·로그를 본다.
# DATABASE_URL은 서빙과 동일하게 컨테이너 안에서 조립해주므로(관리 시크릿의 password 사용),
# 사용자는 그 뒤에 붙일 명령만 넘기면 된다. 마이그레이션·계정생성 같은 관리작업용.
#
# 사용:
#   scripts/ecs-oneshot.sh "alembic upgrade head"
#   scripts/ecs-oneshot.sh "python scripts/create_user.py demo@example.com --demo"
set -euo pipefail

REGION=ap-northeast-2
CLUSTER=blog
TASKDEF=blog-backend
VPC=vpc-0326229237c590a90
CMD="${1:?명령을 인자로 넘겨줘 (예: \"alembic upgrade head\")}"

SG=$(aws ec2 describe-security-groups --region "$REGION" \
  --filters "Name=group-name,Values=blog-ecs-task" \
  --query 'SecurityGroups[0].GroupId' --output text)
SUBNETS=$(aws ec2 describe-subnets --region "$REGION" \
  --filters "Name=vpc-id,Values=$VPC" \
  --query 'Subnets[].SubnetId' --output text | tr '[:space:]' ',' | sed 's/,$//')

# 컨테이너가 실행할 셸 문자열(서빙 command와 동일한 DATABASE_URL 조립 + 사용자 명령)을
# 파이썬으로 만들어 CLI 이스케이프 지옥을 피한다. $DB_* 는 컨테이너 셸이 확장한다.
OVERRIDES=$(python3 - "$CMD" <<'PY'
import json, sys
cmd = sys.argv[1]
# 비번을 URL 인코딩(특수문자 안전). alembic은 그 URL을 configparser(%보간)로 넘기므로
# %를 %%로 이스케이프해야 한다(configparser가 다시 %로 되돌림). SQLAlchemy를 직접 쓰는
# create_user 등은 단일 %가 맞다.
enc = 'urllib.parse.quote(os.environ["DB_PASSWORD"], safe="")'
if cmd.strip().startswith("alembic"):
    enc += '.replace("%", "%%")'
wrap = ('export DATABASE_URL="postgresql://$DB_USER:'
        "$(python -c 'import urllib.parse,os;print(" + enc + ")')"
        '@$DB_HOST:$DB_PORT/$DB_NAME" && ' + cmd)
print(json.dumps({"containerOverrides": [{"name": "backend", "command": ["sh", "-c", wrap]}]}))
PY
)

echo "▶ run-task: $CMD"
ARN=$(aws ecs run-task --region "$REGION" --cluster "$CLUSTER" \
  --task-definition "$TASKDEF" --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SG],assignPublicIp=ENABLED}" \
  --overrides "$OVERRIDES" --query 'tasks[0].taskArn' --output text)
echo "  taskArn: $ARN"
echo "  stopped 대기 중..."
aws ecs wait tasks-stopped --region "$REGION" --cluster "$CLUSTER" --tasks "$ARN"

CODE=$(aws ecs describe-tasks --region "$REGION" --cluster "$CLUSTER" --tasks "$ARN" \
  --query 'tasks[0].containers[0].exitCode' --output text)
REASON=$(aws ecs describe-tasks --region "$REGION" --cluster "$CLUSTER" --tasks "$ARN" \
  --query 'tasks[0].stoppedReason' --output text)
echo "  exitCode=$CODE  stoppedReason=$REASON"

echo "── 로그 ──────────────────────────────"
TID=${ARN##*/}
aws logs get-log-events --region "$REGION" \
  --log-group-name /ecs/blog-backend --log-stream-name "backend/backend/$TID" \
  --query 'events[].message' --output text 2>/dev/null | tail -50 || echo "(로그 스트림 없음)"
echo "──────────────────────────────────────"

if [ "$CODE" = "0" ]; then echo "✓ 성공"; else echo "✗ 실패 (exitCode=$CODE)"; exit 1; fi

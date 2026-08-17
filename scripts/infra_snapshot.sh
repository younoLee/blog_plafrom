#!/usr/bin/env bash
# AWS 계정에 **실제로 떠 있는 것**을 재서 content/infra.json으로 굽는다.
# 그 json을 gen-static.mjs가 /infra.html로 렌더한다.
#
# 왜 스냅샷인가 (빌드가 직접 AWS를 부르지 않는 이유):
#   프론트 배포는 GitHub Actions에서 도는데, 거기에 describe 권한을 주면 배포 역할이
#   계정 전체를 읽을 수 있게 된다. 이 저장소는 권한을 좁히려고 OIDC까지 붙였고(키 없는 배포),
#   페이지 한 장 때문에 그걸 되돌리는 건 값이 안 맞는다. 그래서 **사람이 재서 커밋**한다.
#   tags.json과 같은 방식이다 — 생성물이지만 커밋하고, 언제 잰 값인지 파일에 적는다.
#
# 낡는다는 것이 이 파일의 성질이다. 그래서 페이지에 '언제 잰 값인지'를 크게 적는다.
# 인프라를 바꾼 날 이걸 다시 돌리면 된다.
#
# 사용:  scripts/infra_snapshot.sh        # content/infra.json 갱신

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$REPO_DIR/content/infra.json"
REGION=${AWS_REGION:-ap-northeast-2}

q() { aws "$@" 2>/dev/null || echo ""; }

echo "AWS 계정을 재는 중… (region=$REGION)"

ec2_json=$(q ec2 describe-instances --region "$REGION" \
  --filters "Name=tag:Name,Values=blog-backend" \
  --query 'Reservations[].Instances[].{type:InstanceType,state:State.Name,az:Placement.AvailabilityZone}' \
  --output json)
vol_json=$(q ec2 describe-volumes --region "$REGION" \
  --query 'Volumes[].{size:Size,type:VolumeType}' --output json)
sg_count=$(q ec2 describe-security-groups --region "$REGION" --query 'length(SecurityGroups)' --output text)
eip_count=$(q ec2 describe-addresses --region "$REGION" --query 'length(Addresses)' --output text)
cf_json=$(q cloudfront list-distributions \
  --query 'DistributionList.Items[].{status:Status,price:PriceClass,http:HttpVersion}' --output json)
s3_count=$(q s3api list-buckets --query 'length(Buckets)' --output text)
lambda_count=$(q lambda list-functions --region "$REGION" --query 'length(Functions)' --output text)
alarm_count=$(q cloudwatch describe-alarms --region "$REGION" --query 'length(MetricAlarms)' --output text)

python3 - "$OUT" "$REGION" <<PY
import json, subprocess, sys, datetime
out, region = sys.argv[1], sys.argv[2]
def j(s, d):
    try: return json.loads(s) if s.strip() else d
    except Exception: return d
snap = {
    "measured_at": subprocess.run(["date","-u","+%Y-%m-%d"],capture_output=True,text=True).stdout.strip(),
    "region": region,
    "ec2": j('''$ec2_json''', []),
    "volumes": j('''$vol_json''', []),
    "security_groups": "$sg_count",
    "eips": "$eip_count",
    "cloudfront": j('''$cf_json''', []),
    "s3_buckets": "$s3_count",
    "lambda": "$lambda_count",
    "alarms": "$alarm_count",
}
open(out, "w", encoding="utf-8").write(json.dumps(snap, ensure_ascii=False, indent=2) + "\n")
print(f"  → {out}")
print(f"     EC2 {len(snap['ec2'])}대 · 볼륨 {len(snap['volumes'])}개 · SG {snap['security_groups']} · "
      f"EIP {snap['eips']} · CloudFront {len(snap['cloudfront'])} · S3 {snap['s3_buckets']} · "
      f"Lambda {snap['lambda']} · 알람 {snap['alarms']}")
PY

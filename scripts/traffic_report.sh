#!/usr/bin/env bash
# 방문 집계 — "아무도 안 오는지, 오는데 내가 모르는지"를 가른다.
#
# 사용:
#   scripts/traffic_report.sh          # 최근 14일
#   scripts/traffic_report.sh 30       # 최근 30일 (CloudWatch 표준 지표는 15개월 보관)
#
# 필요한 것: aws CLI 자격증명(cloudwatch:GetMetricStatistics).
#
# ── 왜 앱 카운터가 아닌가 ────────────────────────────────────────────────
# 이 사이트의 실제 읽기 경로는 대부분 **서버를 안 거친다**: EC2는 평소 꺼져 있고,
# 검색·RSS·공유로 들어오는 사람은 S3의 정적 아카이브를 본다. 백엔드에 카운터를 달면
# 가장 많이 읽히는 경로가 통째로 안 세진다. 모든 요청이 지나가는 지점은 CloudFront뿐이다.
#
# ── 🔴 왜 액세스 로그가 아니라 지표인가 (2026-08-15에 실제로 부딪혔다) ──────
# 처음엔 CloudFront 표준 로깅을 S3로 켜려고 terraform까지 짰다. apply가 거부했다:
#
#   InvalidArgument: Distributions with the Free pricing plan can't have
#   the following features: Standard logging
#
# 이 배포의 요금제가 CSP용 Response Headers Policy를 거부하는 것과 **같은 제약**이다.
# 그때는 CloudFront Function으로 우회했지만 로깅은 우회로가 없다. 그래서 만들었던
# 로그 버킷은 **지우고**(한 줄도 안 들어올 버킷을 남기는 게 이 저장소가 반복해서
# 당한 "설정했는데 대상이 0개"다) CloudWatch 표준 지표로 갈아탔다.
#
# **이 스크립트가 답할 수 있는 것과 없는 것을 분명히 해둔다:**
#   ✅ 요청이 있기는 한가 · 며칠에 몰리는가 · 추세가 오르는가 · 오류율
#   ❌ **어느 글이 읽혔는가** · 어디서 왔는가(Referer) · 방문자 수
#      → 그건 요청 단위 로그가 있어야 하고, 그러려면 요금제를 올려야 한다(돈 드는 결정).
# 이 구분을 안 적으면 다음 사람이 "조회수 붙였는데 왜 글별로 안 보이지"에서 시간을 쓴다.
#
# ⚠️ 숫자는 **요청 수**지 방문자 수가 아니다. 한 사람이 한 페이지를 열면 HTML·JS·CSS·
#    폰트로 요청이 여러 건 발생한다. 절대값보다 **날짜별 비교**로 읽을 것.
set -uo pipefail

DIST_ID="E1438IL9CSVBS4"
DAYS="${1:-14}"
# CloudFront 지표는 리전이 아니라 **us-east-1의 Global 차원**에 쌓인다.
# ap-northeast-2로 조회하면 데이터가 0건인데 에러도 안 난다 — 조용히 '방문 0'이 된다.
REGION="us-east-1"

command -v aws >/dev/null || { echo "❌ aws CLI가 필요합니다."; exit 1; }
START="$(date -u -d "${DAYS} days ago" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)" || {
  echo "❌ date -d 를 못 씁니다(GNU date 필요)."; exit 1
}
END="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "── CloudFront 지표 최근 ${DAYS}일 (배포 ${DIST_ID}) ──"
echo

# metric_daily <MetricName> <Statistic>  → "날짜<TAB>값" 을 날짜순으로
metric_daily() {
  aws cloudwatch get-metric-statistics \
    --region "$REGION" --namespace AWS/CloudFront --metric-name "$1" \
    --dimensions Name=DistributionId,Value="$DIST_ID" Name=Region,Value=Global \
    --start-time "$START" --end-time "$END" --period 86400 --statistics "$2" \
    --query "Datapoints[].[Timestamp,$2]" --output text 2>/dev/null \
    | awk '{split($1,d,"T"); printf "%s\t%s\n", d[1], $2}' | sort
}

REQ="$(metric_daily Requests Sum)"
if [ -z "$REQ" ]; then
  echo "지표가 0건입니다."
  echo
  echo "이건 '방문 0'이 아니라 '아직 못 읽었다'일 수 있습니다:"
  echo "  · 자격증명에 cloudwatch:GetMetricStatistics 권한이 있는지"
  echo "  · 리전이 us-east-1인지 (CloudFront 지표는 Global 차원에만 쌓인다)"
  echo "  · 배포 ID가 ${DIST_ID}가 맞는지"
  exit 0
fi

TOTAL="$(echo "$REQ" | awk '{s+=$2} END{printf "%d", s}')"
PEAK="$(echo "$REQ" | awk '{if($2>m)m=$2} END{printf "%d", (m>0?m:1)}')"
DAYS_SEEN="$(echo "$REQ" | wc -l)"

echo "총 요청 ${TOTAL}건 / ${DAYS_SEEN}일 (하루 평균 $((TOTAL / (DAYS_SEEN > 0 ? DAYS_SEEN : 1)))건)"
echo "※ 방문자 수가 아니라 요청 수다. 한 페이지가 여러 요청을 만든다 — 날짜별 비교로 읽을 것."
echo
echo "── 날짜별 요청 ──"
echo "$REQ" | awk -v peak="$PEAK" '{
  n = int($2 / peak * 40); bar = "";
  for (i = 0; i < n; i++) bar = bar "#";
  printf "%s  %6d  %s\n", $1, $2, bar
}'

echo
echo "── 전송량(하루) ──"
metric_daily BytesDownloaded Sum | awk '{printf "%s  %.1f MB\n", $1, $2/1048576}'

echo
echo "── 오류율(%) ──"
# 4xx가 갑자기 오르면 배포 사고(옛 해시 번들 404)이거나 봇 스캔이다.
# 엣지 404 함수를 넣은 뒤로는 봇 스캔이 여기 4xx로 잡힌다 — 늘어도 정상일 수 있다.
E4="$(metric_daily 4xxErrorRate Average)"
E5="$(metric_daily 5xxErrorRate Average)"
if [ -z "$E4" ] && [ -z "$E5" ]; then
  echo "(데이터 없음)"
else
  join -a1 -a2 -e 0 -o 0,1.2,2.2 \
    <(echo "$E4" | tr '\t' ' ' | sort) <(echo "$E5" | tr '\t' ' ' | sort) 2>/dev/null \
    | awk '{printf "%s  4xx %5.2f%%  5xx %5.2f%%\n", $1, $2, $3}'
fi

echo
echo "── 못 보는 것 ──"
echo "어느 글이 읽혔는지·어디서 왔는지는 이 경로로 알 수 없습니다(요청 단위 로그가 필요)."
echo "표준 로깅은 이 배포의 요금제가 거부합니다 — 올리려면 돈이 드는 결정입니다."

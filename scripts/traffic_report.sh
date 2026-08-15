#!/usr/bin/env bash
# 방문 집계 — "아무도 안 오는지, 오는데 내가 모르는지"를 가른다.
#
# 재료는 CloudFront 액세스 로그다(terraform/cf-logs.tf). 왜 앱 카운터가 아니라
# 여기인지는 그 파일 머리말에 적었다 — 한 줄로 줄이면, 이 사이트의 읽기 대부분은
# 백엔드를 안 거치기 때문이다(EC2는 평소 꺼져 있고 정적 아카이브는 S3에서 나간다).
#
# 사용:
#   scripts/traffic_report.sh          # 최근 7일
#   scripts/traffic_report.sh 30       # 최근 30일 (보존 상한이 30일이다)
#
# 필요한 것: aws CLI 자격증명(S3 읽기), gzip, awk.
#
# ⚠️ **로그가 비어 있는 것과 방문이 0인 것은 다르다.** 로깅을 켠 시각 이전은 기록이
#    없고, 켠 직후에도 첫 파일이 도착하기까지 수십 분이 걸린다. 이 스크립트는 그 둘을
#    구분해서 말한다 — 안 그러면 "0명"이라는 틀린 결론을 내리게 된다.
#
# ⚠️ **개인정보:** 로그에는 방문자 IP가 남는다. 여기서는 **세기만 하고 출력하지 않는다.**
#    (보존은 30일 — 버킷 lifecycle이 자른다)
set -uo pipefail

BUCKET="blog-cf-logs-181568979775"
PREFIX="cf/"
DAYS="${1:-7}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "── CloudFront 액세스 로그 최근 ${DAYS}일 ──"

# 파일명이 `cf/<distribution-id>.YYYY-MM-DD-HH.<hash>.gz` 형식이라 접두사로 날짜를
# 못 자른다(배포 ID가 앞에 온다). 목록을 받아 LastModified로 거른다.
SINCE="$(date -u -d "${DAYS} days ago" +%Y-%m-%d 2>/dev/null)" || {
  echo "❌ date -d 를 못 씁니다(GNU date 필요)."; exit 1
}

KEYS="$(aws s3api list-objects-v2 --bucket "$BUCKET" --prefix "$PREFIX" \
  --query "Contents[?LastModified>='${SINCE}'].Key" --output text 2>/dev/null)" || {
  echo "❌ 로그 버킷을 못 읽었습니다: s3://$BUCKET/$PREFIX"
  echo "   (terraform apply로 cf-logs.tf가 올라갔는지, 자격증명이 있는지 확인)"
  exit 1
}

if [ -z "$KEYS" ] || [ "$KEYS" = "None" ]; then
  echo "로그 파일 0개."
  echo
  echo "이건 '방문 0명'이 아니라 '기록이 없다'는 뜻일 수 있습니다. 셋 중 하나입니다:"
  echo "  1) 로깅을 방금 켰다 — 첫 파일까지 수십 분 걸립니다."
  echo "  2) terraform apply를 아직 안 했다 (cloudfront.tf의 logging_config)."
  echo "  3) 버킷 ACL이 꺼져 있어 CloudFront가 조용히 못 쓰고 있다"
  echo "     → aws_s3_bucket_ownership_controls(BucketOwnerPreferred)가 있는지 확인."
  exit 0
fi

N=0
for key in $KEYS; do
  aws s3 cp "s3://$BUCKET/$key" "$WORK/" --quiet 2>/dev/null && N=$((N + 1))
done
echo "로그 파일 ${N}개"

# CloudFront 표준 로그(W3C 확장): 탭 구분, 앞 두 줄은 #Version/#Fields.
# 쓰는 필드: 1=date 5=sc-status 8=cs-uri-stem 10=cs(User-Agent) 12=cs(Referer) 3=c-ip
#   ⚠️ 필드 번호는 #Fields 줄에 실제로 적혀 있다. 여기서는 CloudFront가 2014년부터
#      유지해온 표준 순서를 전제한다 — 어긋나면 아래 숫자가 통째로 헛돌므로,
#      결과가 이상하면 `zcat <파일> | head -2`로 #Fields를 먼저 확인할 것.
zcat "$WORK"/*.gz 2>/dev/null | grep -v '^#' > "$WORK/all.tsv"
TOTAL="$(wc -l < "$WORK/all.tsv")"

if [ "$TOTAL" -eq 0 ]; then
  echo "요청 0건 (파일은 있는데 내용이 비었습니다)."
  exit 0
fi

# 사람 요청만 남긴다. 봇을 안 걸러내면 숫자가 대부분 크롤러라 '읽혔다'로 못 읽는다.
# 자산(.js·.css·이미지)도 뺀다 — 한 번의 방문이 요청 수십 건이라 페이지뷰가 아니다.
awk -F'\t' '
  tolower($10) ~ /bot|crawler|spider|slurp|curl|wget|headless|monitor|python-|preview/ { next }
  $5 ~ /^(2|3)/ { print }
' "$WORK/all.tsv" > "$WORK/human.tsv"

PAGES="$(awk -F'\t' '$8 ~ /(\.html|\/)$/ || $8 !~ /\./' "$WORK/human.tsv" | wc -l)"
UNIQ_IP="$(awk -F'\t' '{print $3}' "$WORK/human.tsv" | sort -u | wc -l)"
BOTS=$((TOTAL - $(wc -l < "$WORK/human.tsv")))

echo
echo "요청 ${TOTAL}건 (봇·실패 제외 후 ${PAGES} 페이지뷰) · 서로 다른 방문자 약 ${UNIQ_IP}명 · 걸러낸 요청 ${BOTS}건"
echo "  ※ 방문자 수는 IP 기준 근사치입니다(같은 회선이면 여러 명이 하나로 셉니다)."

echo
echo "── 많이 본 페이지 ──"
awk -F'\t' '$8 ~ /(\.html)$/ || $8 !~ /\./ {print $8}' "$WORK/human.tsv" \
  | sort | uniq -c | sort -rn | head -15

echo
echo "── 유입 경로(Referer) ──"
# '-'는 직접 방문(주소창·북마크·앱). 그것도 정보라 버리지 않고 라벨만 바꾼다.
awk -F'\t' '{r=$12; if (r=="-") r="(직접/알수없음)"; print r}' "$WORK/human.tsv" \
  | sed 's#\(https\?://[^/]*\).*#\1#' \
  | sort | uniq -c | sort -rn | head -10

echo
echo "── 날짜별 페이지뷰 ──"
awk -F'\t' '$8 ~ /(\.html)$/ || $8 !~ /\./ {print $1}' "$WORK/human.tsv" \
  | sort | uniq -c

echo
echo "── 404·오류 ──"
awk -F'\t' '$5 ~ /^(4|5)/ {print $5, $8}' "$WORK/all.tsv" \
  | sort | uniq -c | sort -rn | head -10

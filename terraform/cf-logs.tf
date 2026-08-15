# CloudFront 액세스 로그 — "아무도 안 오는지, 오는데 내가 모르는지"를 가른다.
#
# 2026-08-14 격차검사 20번. 이 블로그에는 조회수도 방문자 수도 **없다.** 31편 24만 자를
# 써놓고 그게 읽히는지 아닌지 아는 방법이 하나도 없었다.
#
# ── 왜 앱 카운터가 아닌가 ────────────────────────────────────────────────
# 이 사이트의 실제 읽기 경로는 대부분 **서버를 안 거친다**:
#   · EC2는 평소 꺼져 있다(운영 방식이다). 켜져 있을 때만 세면 표본이 그때로 편향된다.
#   · 검색·RSS·공유로 들어오는 사람은 정적 아카이브(/devlog/*.html)를 본다 — S3다.
#   · SPA도 첫 화면은 S3에서 오고 /api는 목록을 받을 때만 탄다.
# 즉 백엔드에 카운터를 달면 **가장 많이 읽히는 경로가 통째로 안 세진다.** 유일하게
# 모든 요청이 지나가는 지점이 CloudFront라, 세려면 여기여야 한다.
#
# ── 비용 ─────────────────────────────────────────────────────────────────
# CloudFront 표준 로깅 자체는 무료다(전송 요금 없음). 붙는 건 S3 PUT과 저장뿐이고,
# 로그는 gzip이라 이 트래픽에서는 월 몇 센트 수준이다. 그마저 아래 lifecycle이
# 30일로 묶는다 — 이 블로그에 필요한 건 '지난 달 대비'지 영구 보존이 아니다.
# (실시간 로그·Kinesis는 돈이 붙는 자리라 안 쓴다.)
#
# ── 개인정보 ─────────────────────────────────────────────────────────────
# 액세스 로그에는 방문자 IP가 남는다. 그래서 셋을 정한다:
#   1. include_cookies = false — 쿠키는 안 받는다(세션 토큰이 로그로 새면 그게 사고다).
#   2. 30일 만료 — 보존 기간을 무한으로 두지 않는다.
#   3. 집계 스크립트(scripts/traffic_report.sh)는 IP를 **세기만 하고 출력하지 않는다.**

resource "aws_s3_bucket" "cf_logs" {
  bucket = "blog-cf-logs-181568979775" # 계정ID 접미사로 전역 유일성
}

resource "aws_s3_bucket_public_access_block" "cf_logs" {
  bucket                  = aws_s3_bucket.cf_logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "cf_logs" {
  bucket = aws_s3_bucket.cf_logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# 🔴 **이 블록이 없으면 로그가 한 줄도 안 쌓인다 — 그리고 아무 에러도 안 난다.**
#
# 새로 만든 S3 버킷은 기본이 `BucketOwnerEnforced`(ACL 비활성)인데, CloudFront 표준
# 로깅은 ACL로 파일을 쓴다. 그래서 ACL이 꺼진 버킷에는 CloudFront가 **조용히** 못 쓴다.
# distribution은 멀쩡히 살아 있고 terraform도 초록이라, 눈에 보이는 증상은 몇 주 뒤
# "로그 보러 갔더니 버킷이 비어 있다" 하나다 — 이 저장소가 반복해서 당한 모양이라
# 여기 크게 적어둔다. 지우지 말 것.
resource "aws_s3_bucket_ownership_controls" "cf_logs" {
  bucket = aws_s3_bucket.cf_logs.id

  rule {
    # ObjectWriter가 아니라 BucketOwnerPreferred: CloudFront가 쓰되 소유권은
    # 버킷 주인(우리)에게 온다. 그래야 집계 스크립트가 그냥 읽을 수 있다.
    object_ownership = "BucketOwnerPreferred"
  }
}

# 보존 상한. 로그가 무한히 쌓이면 '싸다'가 언젠가 거짓이 된다.
resource "aws_s3_bucket_lifecycle_configuration" "cf_logs" {
  bucket     = aws_s3_bucket.cf_logs.id
  depends_on = [aws_s3_bucket_ownership_controls.cf_logs]

  rule {
    id     = "expire-30d"
    status = "Enabled"

    filter {} # 버킷 전체

    expiration {
      days = 30
    }
  }
}

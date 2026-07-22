# 감사 로그(CloudTrail) — "누가 무엇을 했나"를 나중에 알 수 있게.
#
# 왜 필요한가: 2026-07-22 보안검사에서 이 계정에 **CloudTrail·GuardDuty·Config가 전부
# 0개**라는 게 드러났다. 즉 관리자 키가 유출돼 백업 버킷이 지워지거나 SSM에서 운영
# 시크릿이 통째로 읽혀도, **무슨 일이 있었는지 사후에 알 방법이 전혀 없었다.**
# 콘솔의 Event history(90일)는 트레일 없이도 보이지만 조회 전용이고 durable하지 않다.
#
# 비용 (2026-07-22에 AWS 요금 페이지로 확인):
#   · 관리 이벤트의 **첫 사본은 영구 무료** — "one copy of your ongoing management
#     events to your S3 bucket for free by creating trails". 체험 기간이 아니다.
#   · 데이터 이벤트($0.10/10만)와 Insights($0.35/10만)는 **일부러 켜지 않는다.**
#     이 블로그에서 S3 오브젝트 단위 감사까지는 과하고, 그쪽이 돈이 붙는 자리다.
#   · 남는 건 S3 저장·요청뿐이고, 이 계정 활동량(감시 워크플로 시간당 몇 건 + 작업
#     세션)이면 월 몇 센트 수준이다. 아래 lifecycle로 상한을 둬 그마저 묶는다.

resource "aws_s3_bucket" "cloudtrail" {
  bucket = "blog-cloudtrail-181568979775" # 계정ID 접미사로 전역 유일성
}

resource "aws_s3_bucket_public_access_block" "cloudtrail" {
  bucket                  = aws_s3_bucket.cloudtrail.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# 감사 로그가 지워지면 감사가 안 된다. 다른 버킷과 같은 원칙으로 버저닝을 켠다.
resource "aws_s3_bucket_versioning" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id

  versioning_configuration {
    status = "Enabled"
  }
}

# 무한 누적을 막는다. 90일이면 "사고를 알아차리고 되짚을" 창으로 충분하고,
# 이 계정 볼륨에서는 어차피 몇 MB 수준이다.
resource "aws_s3_bucket_lifecycle_configuration" "cloudtrail" {
  bucket     = aws_s3_bucket.cloudtrail.id
  depends_on = [aws_s3_bucket_versioning.cloudtrail]

  rule {
    id     = "expire-old-logs"
    status = "Enabled"

    filter {}

    expiration {
      days = 90
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  rule {
    id     = "clean-expired-delete-markers"
    status = "Enabled"

    filter {}

    expiration {
      expired_object_delete_marker = true
    }
  }
}

# CloudTrail 서비스가 이 버킷에 쓸 수 있게 하는 정책.
# `aws:SourceArn` 조건으로 **이 트레일이 보낸 것만** 받는다 — 조건이 없으면 다른 계정의
# 트레일이 우리 버킷에 로그를 밀어넣는 confused-deputy가 가능하다.
data "aws_caller_identity" "current" {}

resource "aws_s3_bucket_policy" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AWSCloudTrailAclCheck"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:GetBucketAcl"
        Resource  = aws_s3_bucket.cloudtrail.arn
        Condition = {
          StringEquals = {
            "aws:SourceArn" = "arn:aws:cloudtrail:ap-northeast-2:${data.aws_caller_identity.current.account_id}:trail/blog-audit"
          }
        }
      },
      {
        Sid       = "AWSCloudTrailWrite"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.cloudtrail.arn}/AWSLogs/${data.aws_caller_identity.current.account_id}/*"
        Condition = {
          StringEquals = {
            "s3:x-amz-acl"  = "bucket-owner-full-control"
            "aws:SourceArn" = "arn:aws:cloudtrail:ap-northeast-2:${data.aws_caller_identity.current.account_id}:trail/blog-audit"
          }
        }
      },
    ]
  })
}

resource "aws_cloudtrail" "main" {
  name           = "blog-audit"
  s3_bucket_name = aws_s3_bucket.cloudtrail.id

  # 전 리전 + 글로벌 서비스. IAM·CloudFront·WAF는 us-east-1에 기록되므로 이게 없으면
  # 정작 제일 중요한 '누가 IAM을 바꿨나'가 안 남는다. 리전당 첫 사본이 무료라 비용은 그대로.
  is_multi_region_trail         = true
  include_global_service_events = true

  # 로그 파일 해시 다이제스트를 같이 남겨 사후 변조를 탐지할 수 있게 한다(무료).
  enable_log_file_validation = true

  # 데이터 이벤트·Insights는 **켜지 않는다** — 여기가 돈이 붙는 자리다.
  # 기본값이 관리 이벤트(읽기+쓰기)만이고, 그게 이 계정에 필요한 전부다.

  depends_on = [aws_s3_bucket_policy.cloudtrail]
}

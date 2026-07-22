# 프론트엔드 정적 사이트 버킷 (CloudFront OAC로만 접근, 퍼블릭 차단)
# 지금은 버킷 본체만 선언한다. 퍼블릭 차단/정책 같은 부속 설정은
# import 후 terraform plan 차이를 보면서 하나씩 추가한다.
resource "aws_s3_bucket" "frontend" {
  bucket = "blogplafromops"
}

# 모든 퍼블릭 액세스 차단 (외부 직접 접근 막고, CloudFront OAC 경유로만 열어둠)
resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# 버저닝 — 이 버킷은 정적 사이트와 **업로드 이미지**를 같이 담고 있어서 필요하다.
#
# 이미지는 2026-06-26에 EC2 디스크에서 여기(`uploads/`)로 옮겼다. 인스턴스 교체에는
# 안전해졌지만, 대신 프론트 배포와 같은 버킷을 쓰게 됐다. 배포는 `s3 sync --delete`라
# 지금은 `--exclude "uploads/*"` 한 줄(.github/workflows/deploy.yml)만이 이미지를
# 지키고 있다 — 그 플래그를 빠뜨린 수동 sync 한 번이면 전부 사라지고, 되돌릴 수 없다.
# 게다가 이미지는 DB 덤프에도 안 들어가서 어떤 백업으로도 복구가 안 된다.
# 버저닝을 켜면 `--delete`는 삭제 표식만 얹으므로 실수를 되돌릴 수 있다.
resource "aws_s3_bucket_versioning" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  versioning_configuration {
    status = "Enabled"
  }
}

# 버저닝의 대가(옛 버전 누적)를 정적 자산에만 물린다.
#
# 핵심은 `uploads/`에 만료 규칙을 걸지 '않는' 것이다. 이미지는 다시 만들 수 없고
# 몇 MB 수준이라, 지워진 뒤에도 옛 버전을 영구히 남기는 편이 맞다.
# 반대로 assets/의 해시 번들은 배포할 때마다 통째로 갈리므로 30일이면 충분하다.
resource "aws_s3_bucket_lifecycle_configuration" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  depends_on = [aws_s3_bucket_versioning.frontend]

  rule {
    id     = "expire-old-spa-assets"
    status = "Enabled"

    filter {
      prefix = "assets/"
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# CloudFront(OAC)만 이 버킷 객체를 읽게 허용하는 정책.
# Condition으로 우리 배포(E1438IL9CSVBS4)에서 온 요청일 때만 통과시킨다.
resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  policy = jsonencode({
    Version = "2008-10-17"
    Id      = "PolicyForCloudFrontPrivateContent"
    Statement = [{
      Sid       = "AllowCloudFrontServicePrincipal"
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.frontend.arn}/*"
      Condition = {
        ArnLike = {
          "AWS:SourceArn" = "arn:aws:cloudfront::181568979775:distribution/E1438IL9CSVBS4"
        }
      }
    }]
  })
}

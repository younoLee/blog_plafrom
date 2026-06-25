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

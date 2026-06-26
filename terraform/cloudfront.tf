# CloudFront가 S3 버킷에 서명된 요청으로 접근하기 위한 OAC(Origin Access Control).
# 배포(distribution)의 S3 오리진이 이걸 참조한다.
resource "aws_cloudfront_origin_access_control" "s3" {
  name                              = "oac-blogplafromops.s3.ap-northeast-2.amazonaws.com-mqrhzoww6th"
  description                       = "Created by CloudFront"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# CloudFront 배포 본체. 정적 화면은 S3, /api·/uploads는 EC2 백엔드로 보낸다.
resource "aws_cloudfront_distribution" "main" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  http_version        = "http2"
  price_class         = "PriceClass_All"
  # 무료등급 WAF (이미지 업로드 위해 SizeRestrictions를 Count로 override 해둔 그 WebACL)
  web_acl_id = "arn:aws:wafv2:us-east-1:181568979775:global/webacl/CreatedByCloudFront-920ca6f5/53f85e35-3f61-4210-bfc6-e626cfc90cc6"

  tags = {
    Name = "bplgplafrom"
  }

  # 정적 사이트 오리진 (S3, OAC 경유로만 접근)
  origin {
    origin_id                = "blogplafromops.s3.ap-northeast-2.amazonaws.com-mqrht3yphkr"
    domain_name              = "blogplafromops.s3.ap-northeast-2.amazonaws.com"
    origin_access_control_id = aws_cloudfront_origin_access_control.s3.id
  }

  # 백엔드 오리진 (EC2, HTTP only :8000)
  origin {
    origin_id   = "ec2-backend"
    domain_name = "ec2-15-164-102-25.ap-northeast-2.compute.amazonaws.com"

    custom_origin_config {
      http_port              = 8000
      https_port             = 443
      origin_protocol_policy = "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  # 기본 동작: 정적 화면 → S3 (CachingOptimized)
  default_cache_behavior {
    target_origin_id           = "blogplafromops.s3.ap-northeast-2.amazonaws.com-mqrht3yphkr"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = "658327ea-f89d-4fab-a63d-7e88639e58f6" # CachingOptimized
    response_headers_policy_id = "67f7725c-6f97-4210-82d7-5512b31e9d03" # Managed-SecurityHeadersPolicy (HSTS·nosniff·frame-options 등)
  }

  # /api/* → EC2 (CachingDisabled + AllViewerExceptHostHeader)
  ordered_cache_behavior {
    path_pattern               = "/api/*"
    target_origin_id           = "ec2-backend"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # CachingDisabled
    origin_request_policy_id   = "216adef6-5c7f-47e4-b989-5492eafa07d3" # AllViewerExceptHostHeader
    response_headers_policy_id = "67f7725c-6f97-4210-82d7-5512b31e9d03" # Managed-SecurityHeadersPolicy
  }

  # /uploads/* 는 이제 S3에 저장 → 기본 동작(S3 오리진)이 서빙하므로 별도 behavior 불필요

  # SPA 라우팅 폴백: 403 → index.html 을 200으로
  custom_error_response {
    error_code            = 403
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 10
  }

  # 기본 CloudFront 인증서 (커스텀 도메인 없음)
  viewer_certificate {
    cloudfront_default_certificate = true
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }
}

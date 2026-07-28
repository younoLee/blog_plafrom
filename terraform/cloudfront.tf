# CloudFront가 S3 버킷에 서명된 요청으로 접근하기 위한 OAC(Origin Access Control).
# 배포(distribution)의 S3 오리진이 이걸 참조한다.
resource "aws_cloudfront_origin_access_control" "s3" {
  name                              = "oac-blogplafromops.s3.ap-northeast-2.amazonaws.com-mqrhzoww6th"
  description                       = "Created by CloudFront"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# CSP: Free 요금제가 커스텀 Response Headers Policy를 거부하므로 CloudFront Function으로 주입한다.
# (관리형 SecurityHeadersPolicy의 HSTS·nosniff·frame-options·referrer·xss 는 그대로 유지)
resource "aws_cloudfront_function" "csp" {
  name    = "add-csp-header"
  runtime = "cloudfront-js-2.0"
  comment = "Content-Security-Policy 헤더 추가 (viewer-response)"
  publish = true
  code    = file("${path.module}/csp-function.js")
}

# SPA 딥링크 라우팅. 원래 custom_error_response(403 → 200 /index.html)가 하던 일인데,
# 그건 distribution 전체에 걸려 백엔드의 인가 거부 403까지 200 + HTML로 바꿔버렸다
# (프론트는 res.ok로 판정하니 '실패했는데 성공으로 보이는' 상태가 됐다).
# 라우팅만 함수로 떼어 기본 동작에만 붙인다 → /api/* 응답 코드는 이제 손대지 않는다.
resource "aws_cloudfront_function" "spa" {
  name    = "spa-routing"
  runtime = "cloudfront-js-2.0"
  comment = "확장자 없는 경로를 /index.html로 (SPA 딥링크). 기본 동작에만 연결"
  publish = true
  code    = file("${path.module}/spa-routing-function.js")
}

# 큰 요청 본문(>6MB)을 엣지에서 413으로 차단 → EC2(t2.micro)에 닿기 전에 대용량 본문 DoS 방지
resource "aws_cloudfront_function" "reqsize" {
  name    = "limit-request-body"
  runtime = "cloudfront-js-2.0"
  comment = "Content-Length 6MB 초과 요청을 엣지에서 413 (원본 DoS 방지)"
  publish = true
  code    = file("${path.module}/reqsize-function.js")
}

# CloudFront 배포 본체. 정적 화면은 S3, /api·/uploads는 EC2 백엔드로 보낸다.
resource "aws_cloudfront_distribution" "main" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  http_version        = "http2"
  price_class         = "PriceClass_All"
  # CloudFront Free(flat-rate) 요금제에 '번들로 포함된' 무료 WAF (CreatedByCloudFront).
  # 이 요금제는 WAF를 필수로 요구해서 뗄 수 없다 — 떼려면 pay-as-you-go 전환이 필요하고
  # 그럼 오히려 CloudFront가 과금된다. 즉 이 WAF는 사실상 무료라 그대로 둔다.
  # (SizeRestrictions는 이미지 업로드 위해 Count로 override 해둔 그 WebACL)
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

  # 백엔드 오리진. var.api_backend 로 EC2(:8000)와 ALB(:80) 사이를 통째로 스위치한다.
  #   ec2 모드: EC2 도메인(정지 중엔 주차 → fail closed).
  #   ecs 모드: ALB 도메인(:80). ALB SG가 CloudFront prefix list만 받으므로 직접 노출 없음.
  # 포트도 함께 바뀌므로(8000↔80) 오리진 하나만 두고 domain/port를 local로 고른다
  # → 미참조 오리진이 안 생기고, 롤백은 var만 되돌리면 된다.
  origin {
    origin_id   = "api-backend"
    domain_name = local.api_origin_domain

    custom_origin_config {
      http_port              = local.api_origin_port
      https_port             = 443
      origin_protocol_policy = "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
      # AI 초안 생성이 30초(CloudFront 기본)를 넘겨 504로 끊기던 문제 → 최대값 60초로
      origin_read_timeout = 60
    }

    # 오리진 공유 시크릿 — '이 요청이 우리 배포를 거쳐 왔다'는 증거.
    # 오리진 SG가 CloudFront 엣지 전체를 받으므로, 이게 없으면 공격자가 자기 배포로
    # 우리 오리진을 직접 때려 WAF·CSP를 우회할 수 있다. 근거는 variables.tf 참고.
    # var가 비면 블록 자체가 안 생긴다(기능 off) — 켜고 끄는 순서도 거기 적어뒀다.
    dynamic "custom_header" {
      for_each = var.origin_secret != "" ? [var.origin_secret] : []
      content {
        name  = "X-Origin-Secret"
        value = custom_header.value
      }
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
    response_headers_policy_id = "67f7725c-6f97-4210-82d7-5512b31e9d03" # Managed-SecurityHeadersPolicy

    # SPA 딥링크 라우팅(확장자 없는 경로 → /index.html). 기본 동작에만 붙이는 게 핵심 —
    # /api/*는 별도 동작이라 이 함수를 안 탄다. 그래서 백엔드 응답 코드를 안 건드린다.
    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.spa.arn
    }

    # CSP 헤더 주입 (Free 플랜 우회). 정적 화면(HTML)에만 붙이면 되므로 기본 동작에만 연결
    function_association {
      event_type   = "viewer-response"
      function_arn = aws_cloudfront_function.csp.arn
    }
  }

  # /api/* → 백엔드 (CachingDisabled + AllViewerExceptHostHeader). 오리진은 api_backend 스위치가 정함.
  ordered_cache_behavior {
    path_pattern               = "/api/*"
    target_origin_id           = "api-backend"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # CachingDisabled
    origin_request_policy_id   = "216adef6-5c7f-47e4-b989-5492eafa07d3" # AllViewerExceptHostHeader
    response_headers_policy_id = "67f7725c-6f97-4210-82d7-5512b31e9d03" # Managed-SecurityHeadersPolicy

    # 큰 요청 본문(>6MB)을 엣지에서 413 차단 (원본 DoS 방지). API 경로에만 연결.
    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.reqsize.arn
    }
  }

  # /uploads/* 는 이제 S3에 저장 → 기본 동작(S3 오리진)이 서빙하므로 별도 behavior 불필요

  # ⚠️ custom_error_response(403 → 200 /index.html)를 2026-07-28에 **제거했다.**
  # SPA 딥링크 폴백 용도로 넣었는데, 이 블록은 동작별로 못 걸고 **distribution 전체**에
  # 적용된다. 그래서 백엔드가 주는 인가 거부 403까지 200 + HTML이 되고 있었고,
  # 프론트는 res.ok로 성공을 판정하므로 '막혔는데 성공으로 보이는' 상태가 만들어졌다
  # (admin.ts의 승인·차단·삭제가 그 경로다). 서버는 제대로 막았으니 권한 우회는 아니다.
  # 라우팅은 aws_cloudfront_function.spa(기본 동작 viewer-request)가 대신한다.
  # 다시 넣지 말 것 — 넣는 순간 /api/*의 403이 또 200이 된다.

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

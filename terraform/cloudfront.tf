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

# 큰 요청 본문을 엣지에서 413으로 차단 → EC2(t2.micro)에 닿기 전에 대용량 본문 DoS 방지.
# 2026-09-02부터 상한이 경로별이다: /api/upload만 6MB, 나머지는 512KB.
# (6MB는 이미지 업로드 때문에 잡은 값인데 /api/auth/login 같은 무인증 JSON 경로까지
#  같은 6MB를 받고 있었다. 앱의 BodySizeLimitMiddleware와 같은 정책으로 맞춘 것 —
#  근거는 reqsize-function.js 주석과 backend/app/main.py 참고)
resource "aws_cloudfront_function" "reqsize" {
  name    = "limit-request-body"
  runtime = "cloudfront-js-2.0"
  comment = "Content-Length 상한 초과 요청을 엣지에서 413 (upload 6MB / 그 외 512KB)"
  publish = true
  code    = file("${path.module}/reqsize-function.js")
}

# CloudFront 배포 본체. 정적 화면은 S3, /api·/uploads는 EC2 백엔드로 보낸다.
resource "aws_cloudfront_distribution" "main" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  # HTTP/3(QUIC)를 켠다. 2026-09-02까지 "http2"였는데, 그건 고른 결과가 아니라 기록이
  # 없는 기본값이었다(저장소 어디에도 http3를 검토한 흔적이 없다).
  #
  # 돈이 드는가: **안 든다.** 이 배포가 물려 있는 flat-rate 요금제 문서의
  # "Features by pricing plan tier" 표에서 HTTP/3 행은 Free·Pro·Business·Premium
  # **네 등급 모두 Yes**다(docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/
  # flat-rate-pricing-plan.html, 2026-09-02 확인). 같은 표의 Access Logs 행은 Free만
  # 비어 있는데, 그게 아래 logging_config 주석이 적은 2026-08-15의 실패와 정확히
  # 일치한다 — 즉 이 표는 이 배포의 실제 제약을 맞게 설명하고 있고, 그 표가 HTTP/3는
  # 된다고 말한다. price_class(PriceClass_All)나 WAF 연결과도 무관한 항목이다.
  # 요금제가 바뀌는 게 아니므로 새 리소스도, 월 과금도 생기지 않는다.
  #
  # 구형 클라이언트는 어떻게 되는가: "http2and3"는 **HTTP/3를 추가로 제안**하는 것이지
  # 강제가 아니다. QUIC은 TLSv1.3 + SNI를 지원하는 뷰어만 쓰고, 안 되는 쪽은 그대로
  # HTTP/2나 HTTP/1.1로 붙는다. 즉 잃는 사용자가 없다.
  # 얻는 것: 이 사이트는 모바일 방문이 있고 첫 화면에 정적 자산이 여러 개 붙는다.
  # QUIC은 연결 수립이 짧고(0/1-RTT) 네트워크가 바뀌어도 연결을 유지한다(connection
  # migration, RFC 9000) — 지하철에서 Wi-Fi↔LTE가 바뀌는 방문이 그 대상이다.
  #
  # ⚠️ 이 저장소의 습관대로: **설정했다와 동작한다는 다르다.** 적용 뒤에 실제로
  # 확인할 것 — 응답에 alt-svc: h3=":443" 이 붙는지, 또는
  #   curl --http3 -s -o /dev/null -w '%{http_version}\n' https://<배포>/ → 3
  # 이 나오는지. 안 나오면 켜진 게 아니다.
  http_version = "http2and3"
  price_class  = "PriceClass_All"
  # CloudFront Free(flat-rate) 요금제에 '번들로 포함된' 무료 WAF (CreatedByCloudFront).
  # 이 요금제는 WAF를 필수로 요구해서 뗄 수 없다 — 떼려면 pay-as-you-go 전환이 필요하고
  # 그럼 오히려 CloudFront가 과금된다. 즉 이 WAF는 사실상 무료라 그대로 둔다.
  # 2026-08-11에 ARN 하드코딩을 걷어내고 import했다 → 룰 내용(업로드를 살리는 Count
  # override 포함)이 waf.tf에 코드로 있고, 콘솔에서 바뀌면 plan에 뜬다.
  web_acl_id = aws_wafv2_web_acl.cloudfront.arn

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

    # 주차(서버 정지) 상태에서 /api/*가 30초를 끌다 504가 되던 문제. 2026-09-02 실측:
    #   curl -w '%{http_code} %{time_starttransfer}' .../api/posts → 504 30.1s
    # 원인은 기본값이다 — 연결 시도 3회 × 연결 타임아웃 10초 = 30초. 주차는 '빨리
    # 실패하라'는 fail-closed 장치인데, 30초를 끌면 브라우저 탭이 멈춘 것처럼 보이고
    # 그 사이 CloudFront 연결도 붙잡고 있다. 1 × 1초로 낮춰 1초 안에 끝내게 한다.
    #
    # 왜 안전한가:
    #   · 이건 **TCP 연결 수립 단계에만** 걸리는 노브다. 오리진이 응답을 만드는 데
    #     걸리는 시간은 아래 origin_read_timeout(60초)이 따로 담당한다 — AI 초안
    #     생성이 60초를 쓰는 것과 이 값은 무관하다. 둘을 헷갈려 read를 1초로 만든
    #     것이 아니라는 뜻이다.
    #   · 서버가 켜져 있을 때 연결은 1초 안에 붙는다. 오리진이 같은 리전(서울)의
    #     EC2이고 CloudFront 서울 엣지에서의 RTT가 수 ms 수준이라, TCP 3-way에
    #     1초는 정상 구간 대비 두 자릿수 배 여유다.
    #   · 재시도를 3회→1회로 줄이면 '한 번의 SYN 유실'을 흡수하지 못하는 것은 맞다.
    #     그 대가로 얻는 게 크다고 봤다: 실패 경로가 30초에서 1초가 되고, 정상
    #     경로에서는 애초에 재시도가 일어나지 않으므로 잃는 게 없다. 되돌리려면
    #     connection_attempts만 3으로 올리면 된다(연결 지연은 다시 최대 30초).
    #
    # 값의 유효 범위(CloudFront가 강제한다. 벗어나면 apply가 400으로 실패한다):
    #   connection_attempts 1~3 (기본 3), connection_timeout 1~10초 (기본 10).
    # 즉 여기 쓴 1·1이 각각 허용 최소값이고, 주차 상태의 최대 지연은 1×1=1초다.
    connection_attempts = 1
    connection_timeout  = 1

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

    # 큰 요청 본문을 엣지에서 413 차단 (원본 DoS 방지). API 경로에만 연결.
    # 상한은 함수가 request.uri로 고른다: /api/upload 6MB, 그 외 512KB.
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

  # ⚠️ **표준 로깅(logging_config)은 이 배포에 못 켠다 — 요금제가 거부한다.**
  # 2026-08-15에 실제로 apply 해보고 알았다:
  #   InvalidArgument: Distributions with the Free pricing plan can't have
  #   the following features: Standard logging
  # 위쪽 CSP 주석이 말하는 "Free 요금제가 커스텀 Response Headers Policy를 거부한다"와
  # **같은 제약**이다. 그때는 CloudFront Function으로 우회가 됐지만, 로깅은 우회로가 없다
  # (Function은 어디에도 쓸 수 없다).
  #
  # 그래서 방문 집계는 **CloudWatch 지표**로 간다 — Free 요금제에서도 무료로 나오고
  # 실제 값이 있다(scripts/traffic_report.sh). 대가는 글 단위를 못 본다는 것이다.
  # 글별 조회수를 원하면 요금제를 올려야 하고, 그건 돈이 드는 결정이라 사람 몫이다.
  # 다시 넣지 말 것 — 넣으면 apply가 400으로 실패한다.

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

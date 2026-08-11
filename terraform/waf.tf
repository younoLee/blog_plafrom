# CloudFront 앞단 WebACL. **콘솔이 만든 것을 terraform import로 가져온 리소스다.**
#
# 왜 코드로 가져오는가 — ARN이 cloudfront.tf에 문자열로 박혀 있던 것보다 큰 이유가 있다.
# 이 WebACL의 `SizeRestrictions_BODY`/`CrossSiteScripting_BODY` override(Block→Count)는
# **이미지 업로드가 되는 유일한 이유**인데, 그 사실이 지금까지 콘솔에만 있었다.
# 누가 관리형 룰그룹을 기본값으로 되돌리면 업로드가 조용히 깨지고, 저장소 어디에도
# "원래 Count였다"는 근거가 없다. 이제 drift가 plan에 뜬다.
#
# ⚠️ 이건 CloudFront Free(flat-rate) 요금제가 자동 생성한 WebACL이다(`CreatedByCloudFront-…`).
#    그 요금제에 번들로 포함돼 **지금 과금이 0**이다. 지웠다 다시 만들면 그냥 WAF가 되어
#    WebACL $5/월 + 관리형 룰그룹 요금이 붙는다. 그래서 `prevent_destroy`를 건다.
#    이름·scope는 CloudFront가 정한 값이라 절대 바꾸지 말 것 — 바꾸면 replace = 재생성이다.
#
# WAF는 CloudFront 스코프라 리전이 무조건 us-east-1이다(서울 아님). provider.tf의 별칭을 쓴다.
resource "aws_wafv2_web_acl" "cloudfront" {
  provider = aws.us_east_1

  name  = "CreatedByCloudFront-920ca6f5"
  scope = "CLOUDFRONT"

  default_action {
    allow {}
  }

  rule {
    name     = "AWS-AWSManagedRulesAmazonIpReputationList"
    priority = 0

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesAmazonIpReputationList"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "AWS-AWSManagedRulesAmazonIpReputationList"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "AWS-AWSManagedRulesCommonRuleSet"
    priority = 1

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesCommonRuleSet"

        # 이 두 줄이 업로드를 살려두고 있다. 기본은 Block.
        #   SizeRestrictions_BODY  — 본문 8KB 초과를 막는다. 이미지 업로드가 전부 걸린다.
        #     (진짜 상한은 이걸로 지키지 않는다 — CloudFront Function `limit-request-body`가
        #      6MB에서 413을 준다. 즉 방어를 없앤 게 아니라 엣지 함수로 옮긴 것이다.)
        #   CrossSiteScripting_BODY — 마크다운 본문(<script> 얘기를 쓰는 글 등)이 오탐으로 막힌다.
        # Count는 '통과시키되 계측은 한다'는 뜻이라, 로그로는 계속 보인다.
        rule_action_override {
          name = "SizeRestrictions_BODY"
          action_to_use {
            count {}
          }
        }

        rule_action_override {
          name = "CrossSiteScripting_BODY"
          action_to_use {
            count {}
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "AWS-AWSManagedRulesCommonRuleSet"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "AWS-AWSManagedRulesKnownBadInputsRuleSet"
    priority = 2

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "AWS-AWSManagedRulesKnownBadInputsRuleSet"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "CreatedByCloudFront-920ca6f5"
    sampled_requests_enabled   = true
  }

  lifecycle {
    prevent_destroy = true
  }
}

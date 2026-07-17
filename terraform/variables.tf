# EIP를 쓰지 않으므로 EC2 퍼블릭 DNS는 켤 때마다 바뀐다. 그래서 CloudFront 백엔드
# 오리진 주소를 코드에 박지 않고 이 변수로 넘긴다.
#
# 비워두면(기본값 = EC2 정지 상태) 오리진을 우리가 소유한 S3 도메인으로 '주차'한다.
# 이유: EC2를 정지하면 퍼블릭 IP가 AWS 풀로 반납되고 곧 다른 고객에게 배정될 수 있다.
# 오리진을 옛 ec2-<IP>.compute.amazonaws.com에 남겨두면 그 호스트명은 규칙상 계속 같은
# IP로 resolve되므로, /api/* 요청이 그 IP를 새로 받은 제3자에게 전달된다(Authorization
# 헤더 포함). 주차해두면 오리진이 우리 소유 도메인을 가리키고, 거기엔 8000 포트가 없어
# 연결 자체가 실패한다 = fail closed.
#
# 사용법:
#   EC2 켤 때:  terraform apply -var="backend_origin_dns=$(aws ec2 describe-instances \
#                 --instance-ids i-06da19f44d1f38eff \
#                 --query 'Reservations[0].Instances[0].PublicDnsName' --output text)"
#   EC2 끌 때:  terraform apply      # 기본값 "" → 주차
variable "backend_origin_dns" {
  description = "실행 중인 백엔드 EC2의 퍼블릭 DNS. 비우면 오리진을 주차해 /api/*를 fail closed로 만든다."
  type        = string
  default     = ""

  validation {
    # 실수로 IP나 오타를 넣으면 오리진이 조용히 깨지므로 형식을 강제한다.
    condition     = var.backend_origin_dns == "" || can(regex("^ec2-[0-9-]+\\.[a-z0-9-]+\\.compute\\.amazonaws\\.com$", var.backend_origin_dns))
    error_message = "backend_origin_dns는 비우거나 ec2-<IP>.<region>.compute.amazonaws.com 형식이어야 합니다."
  }
}

locals {
  # 주차용 오리진. 우리가 소유한 도메인이어야 하고(제3자 배정 불가), 백엔드 포트가
  # 열려 있지 않아야 한다 → S3 도메인 + custom_origin_config의 8000 포트 = 연결 불가.
  backend_origin_parked = aws_s3_bucket.frontend.bucket_regional_domain_name

  backend_origin_dns = var.backend_origin_dns != "" ? var.backend_origin_dns : local.backend_origin_parked
}

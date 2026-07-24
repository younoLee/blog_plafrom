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
# 사용법 — 순서가 중요하다:
#   EC2 켤 때:  ① 인스턴스 start → stopped에서 벗어나 퍼블릭 DNS가 생긴 뒤
#               ② terraform apply -var="backend_origin_dns=$(aws ec2 describe-instances \
#                    --instance-ids i-06da19f44d1f38eff \
#                    --query 'Reservations[0].Instances[0].PublicDnsName' --output text)"
#               ※ IP는 켤 때마다 바뀐다. 어디에도 적어두지 말고 항상 이 명령으로 읽을 것.
#   EC2 끌 때:  scripts/stop_server.sh  ← 아래 ①~③을 순서대로 하고 검증까지 한다
#               ① terraform apply   # 기본값 "" → 주차. 반드시 정지보다 '먼저'.
#               ② DB 백업(pg_dump → S3). 끄면 다음에 켤 때까지 사본을 만들 기회가 없다.
#                 옛 cron(KST 03시)은 그 시각에 서버가 꺼져 있어 한 번도 안 돌았다 →
#                 제거하고 여기로 옮겼다(2026-07-20에 0건인 걸 발견).
#               ③ 인스턴스 stop
#               ※ ①③ 순서를 뒤집으면 정지로 IP가 반납된 뒤에도 오리진이 옛 ec2-<IP>...를
#                 가리키는 틈이 생기고, 그 사이 /api/*는 그 IP를 새로 받은 제3자에게 간다.
#               ※ ①②도 순서가 있다(2026-07-22에 바꿨다). 백업이 먼저면 pg_dump가 스냅샷을
#                 뜬 뒤 주차까지의 몇 분 동안 들어온 글·댓글·결제가 사본에 없는 채로 서버가
#                 꺼진다. 주차를 먼저 해 /api/*를 fail closed로 만든 뒤에 사본을 떠야 한다.
# SSH를 허용할 단일 주소. 공개 저장소에 실제 IP를 남기지 않으려고 변수로 뺐다.
# 값은 terraform.tfvars(gitignore됨)에 두고, 기본값은 **일부러 없다** —
# 빠뜨리면 apply가 실패하지, 조용히 넓어지지 않는다.
variable "ssh_cidr" {
  description = "SSH(22)를 허용할 CIDR. 예: 1.2.3.4/32. terraform.tfvars에 둔다."
  type        = string

  validation {
    # /32 단일 호스트만 허용한다. 오타로 /0이나 넓은 대역이 들어가는 걸 막는다.
    condition     = can(regex("^([0-9]{1,3}\\.){3}[0-9]{1,3}/32$", var.ssh_cidr))
    error_message = "ssh_cidr는 단일 호스트(/32)여야 합니다. 예: 1.2.3.4/32"
  }
}

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

# 컷오버 스위치(Stage 5): /api/* 백엔드를 EC2에서 ECS(ALB)로 넘긴다.
#   "ec2" (기본) = 현행 그대로 — EC2 :8000, 정지 시 주차(위 backend_origin_dns 로직).
#   "ecs"        = ALB :80 로 넘긴다. 롤백은 이 값을 "ec2"로 되돌리고 apply(즉시).
# 기본이 "ec2"라 이 코드를 apply해도 아무것도 안 바뀐다 — 실제 컷오버는 -var로 명시할 때만.
variable "api_backend" {
  description = "/api/* 오리진 선택: ec2(현행) | ecs(ALB). 컷오버/롤백 스위치."
  type        = string
  default     = "ec2"

  validation {
    condition     = contains(["ec2", "ecs"], var.api_backend)
    error_message = "api_backend는 ec2 또는 ecs여야 합니다."
  }
}

# ecs 컷오버 시 CloudFront /api 오리진이 될 ALB DNS. **리소스(aws_lb)를 직접 참조하지 않는다** —
# 직접 참조하면 CloudFront가 ALB에 그래프 의존이 생겨, ALB만 -target destroy해도 CloudFront가
# 딸려가려 한다(정리 때 사이트 전체가 지워질 뻔했다). 그래서 값으로 주입한다.
# 컷오버: -var="api_backend=ecs" -var="alb_origin_dns=<ALB DNS>". ec2/정리 시엔 비운다.
variable "alb_origin_dns" {
  description = "ecs 컷오버 시 CloudFront /api 오리진이 될 ALB DNS. 비우면 ec2/주차로 폴백."
  type        = string
  default     = ""
}

locals {
  # 주차용 오리진. 우리가 소유한 도메인이어야 하고(제3자 배정 불가), 백엔드 포트가
  # 열려 있지 않아야 한다 → S3 도메인 + custom_origin_config의 8000 포트 = 연결 불가.
  backend_origin_parked = aws_s3_bucket.frontend.bucket_regional_domain_name

  backend_origin_dns = var.backend_origin_dns != "" ? var.backend_origin_dns : local.backend_origin_parked

  # /api/* 오리진 선택(컷오버). ecs면 ALB(:80, var로 주입), ec2면 현행 EC2 도메인(:8000, 주차 포함).
  # var.alb_origin_dns를 쓰는 이유: aws_lb를 직접 참조하면 CloudFront가 ALB에 그래프 의존이 생겨
  # ALB만 destroy해도 CloudFront가 딸려간다(정리 사고 방지). ecs인데 dns가 비면 안전하게 주차 폴백.
  api_use_ecs       = var.api_backend == "ecs" && var.alb_origin_dns != ""
  api_origin_domain = local.api_use_ecs ? var.alb_origin_dns : local.backend_origin_dns
  api_origin_port   = local.api_use_ecs ? 80 : 8000
}

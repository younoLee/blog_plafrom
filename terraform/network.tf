# ECS 이전용 네트워킹 — 새로 만드는 건 보안그룹 3개뿐이다.
#
# 기본 VPC(172.31.0.0/16)에 4개 AZ 퍼블릭 서브넷이 이미 있고 IGW도 붙어 있어서,
# ALB가 요구하는 '2개 이상 AZ'가 그대로 충족된다 → 서브넷을 새로 만들지 않는다.
#
# 태스크 배치 전략(비용 결정): 태스크를 **퍼블릭 서브넷 + 퍼블릭IP**로 둔다.
#   - 그러면 IGW로 ECR·CloudWatch Logs·S3에 바로 나가므로 **NAT Gateway(월 ~$32)가 불필요**.
#   - VPC 인터페이스 엔드포인트로 NAT를 피하는 길도 있지만, 소규모에선 엔드포인트 시간요금이
#     오히려 NAT보다 비싸서 안 쓴다.
#   - 노출은 SG로 막는다: 태스크 인바운드는 ALB에서만(아래 task SG). 퍼블릭IP가 있어도
#     8000을 직접 때릴 수 없다.
#   - 트레이드오프(면접용): 진짜 운영이면 프라이빗 서브넷 + NAT(또는 엔드포인트)가 정석.
#     여기선 기간한정 데모라 NAT 비용을 피하려 퍼블릭+SG잠금을 택했다.

data "aws_vpc" "main" {
  id = "vpc-0326229237c590a90"
}

# 기본 VPC의 서브넷들. ALB(다중 AZ)와 RDS 서브넷그룹이 이걸 재사용한다(Stage 3~4).
data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.main.id]
  }
}

# ── 3단 보안그룹: ALB → Task → RDS ────────────────────────────────────────────
# 각 층이 '바로 앞 층에서만' 받는다. 인터넷 → ALB(CloudFront만) → Task(ALB만) → RDS(Task만).

# ALB: CloudFront 엣지에서 오는 것만 받는다. 현재 EC2 SG가 8000을 CloudFront prefix list로
# 잠근 것과 같은 모델(ec2.tf). ALB는 인터넷-facing이지만 prefix list로 사실상 CloudFront 전용.
# 리스너는 HTTP:80 — CloudFront→오리진 구간은 지금(EC2 http:8000)도 평문이라 동일한 수준이다.
# (진짜 HTTPS 오리진은 커스텀 도메인+ACM이 필요해서 보류 상태다. ROADMAP 참고)
resource "aws_security_group" "alb" {
  name        = "blog-alb"
  description = "ALB ingress from CloudFront origin-facing only"
  vpc_id      = data.aws_vpc.main.id

  ingress {
    description     = "HTTP from CloudFront edge (origin-facing managed prefix list)"
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    prefix_list_ids = ["pl-22a6434b"] # com.amazonaws.global.cloudfront.origin-facing (ec2.tf와 동일)
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "blog-alb"
  }
}

# Task(Fargate): 앱 포트(8000)를 ALB에서만 받는다. 퍼블릭IP가 있어도 외부 직접 접근 불가.
# egress는 전체 허용 — ECR pull·CloudWatch Logs·S3(업로드)·RDS(5432)로 나가야 한다.
resource "aws_security_group" "task" {
  name        = "blog-ecs-task"
  description = "Fargate task ingress from ALB only"
  vpc_id      = data.aws_vpc.main.id

  ingress {
    description     = "App port from ALB only"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "blog-ecs-task"
  }
}

# RDS: 5432를 Task SG에서만 받는다. 인터넷·VPC 어디서도 직접 못 들어온다.
# (RDS는 publicly_accessible=false로 둘 것 — Stage 3)
resource "aws_security_group" "rds" {
  name        = "blog-rds"
  description = "RDS Postgres ingress from ECS task only"
  vpc_id      = data.aws_vpc.main.id

  ingress {
    description     = "Postgres from ECS task only"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.task.id]
  }

  # egress 없음 — DB는 바깥으로 먼저 연결할 일이 없다. 열어두면 DB 호스트가 뚫렸을 때
  # 유출 경로만 넓어진다. (task·alb는 ECR/logs/S3/RDS로 나가야 해서 egress 전체 허용)

  tags = {
    Name = "blog-rds"
  }
}

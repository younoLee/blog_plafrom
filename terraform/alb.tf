# ECS 이전용 — Application Load Balancer.
#
# CloudFront /api/* 의 새 오리진이 된다(Stage 5 컷오버). 인터넷-facing이지만 SG(alb)가
# CloudFront origin-facing prefix list만 받으므로 사실상 CloudFront 전용 — 지금 EC2:8000을
# 같은 prefix list로 잠근 것과 동일한 모델이다.
#
# 리스너는 HTTP:80. CloudFront→오리진 구간은 지금(EC2 http:8000)도 평문이라 수준이 같다.
# (HTTPS 오리진은 커스텀 도메인+ACM 필요 — 보류. 계획서 Stage 5 참고)

resource "aws_lb" "backend" {
  name               = "blog-backend"
  load_balancer_type = "application"
  internal           = false
  security_groups    = [aws_security_group.alb.id]
  subnets            = data.aws_subnets.default.ids

  # AI 초안 생성이 최대 60초(CloudFront origin_read_timeout=60와 짝). ALB 기본 idle 60초면
  # 그 경계에서 504로 끊길 수 있어 여유를 준다.
  idle_timeout = 120

  tags = {
    Name = "blog-backend"
  }
}

# Fargate 태스크는 IP로 등록된다(target_type=ip). EC2 인스턴스 등록과 다르다.
resource "aws_lb_target_group" "backend" {
  name        = "blog-backend"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = data.aws_vpc.main.id
  target_type = "ip"

  # ROADMAP이 "시간 먹는 구간"으로 콕 집은 곳. 경로는 /api/health(존재 확인됨).
  # /health 는 404라 쓰면 100% unhealthy → 태스크가 계속 교체된다.
  health_check {
    path                = "/api/health"
    matcher             = "200"
    protocol            = "HTTP"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = {
    Name = "blog-backend"
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.backend.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.backend.arn
  }
}

output "alb_dns_name" {
  # 컷오버(Stage 5) 때 CloudFront /api/* 오리진 domain_name 에 넣을 값.
  value = aws_lb.backend.dns_name
}

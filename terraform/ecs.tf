# ECS 이전용 — 클러스터 + 태스크 정의 + 서비스 (Fargate).
#
# 역할이 둘로 나뉜다(SAA 직결 소재):
#   · 실행 역할(execution) : ECS 에이전트가 쓴다 — ECR pull, 로그 쓰기, 시크릿 읽어 주입.
#   · 태스크 역할(task)     : 컨테이너 안 앱이 쓴다 — S3 업로드(현 EC2 인스턴스 역할과 동일 권한).

# 어느 커밋의 이미지를 띄울지. ECR 태그는 IMMUTABLE(=git SHA)이라 'latest'가 없다 →
# build-backend.yml이 올린 SHA를 여기에 넣고 apply한다. CI가 배포를 이어받으면 이 값을 자동 갱신.
variable "backend_image_tag" {
  description = "띄울 백엔드 이미지의 태그(=git SHA). build-backend.yml이 ECR에 올린 값."
  type        = string
  # 기본값 없음 = 필수. 빈 값이면 image가 'repo:'가 되어 CannotPullContainerError로 태스크가
  # 영영 안 뜬다 → 조용한 실패 대신 apply 자체를 막는다. apply 시 -var로 실제 SHA를 넘긴다.

  validation {
    condition     = length(var.backend_image_tag) > 0
    error_message = "backend_image_tag는 비울 수 없습니다. build-backend가 올린 git SHA를 -var로 넘기세요."
  }
}

# ── 로그 ──────────────────────────────────────────────────────────────────────
resource "aws_cloudwatch_log_group" "backend" {
  name              = "/ecs/blog-backend"
  retention_in_days = 14 # 데모라 짧게. 비용·노이즈 억제.
}

# ── 앱 시크릿 컨테이너 (값은 사용자가 채운다) ────────────────────────────────
# EC2 .env의 비밀값들을 여기 JSON으로 넣는다(코드/state엔 값이 안 남는다).
# 넣을 키: SECRET_KEY, ANTHROPIC_API_KEY, LLM_ENCRYPTION_KEY, TOSS_SECRET_KEY
#          (+ SES 쓰면 SMTP_USER, SMTP_PASSWORD). 프로드 .env와 대조해 확정할 것.
# 채우기: aws secretsmanager put-secret-value --secret-id blog-app-secrets --secret-string '{...}'
# ⚠️ 이 버전이 없으면 아래 secrets 참조가 태스크 시작 때 실패한다(설정 ≠ 동작).
resource "aws_secretsmanager_secret" "app" {
  name        = "blog-app-secrets"
  description = "블로그 앱 런타임 비밀값(EC2 .env에서 이관). 값은 콘솔/CLI로 채운다."
}

# ── IAM: 실행 역할 ────────────────────────────────────────────────────────────
resource "aws_iam_role" "ecs_execution" {
  name = "blog-ecs-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# ECR pull + CloudWatch Logs 쓰기(관리형).
resource "aws_iam_role_policy_attachment" "ecs_execution_managed" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# 시크릿 주입: 관리형 정책엔 없다. RDS 관리 비번 + 앱 시크릿 두 개만 읽게 한정한다.
resource "aws_iam_role_policy" "ecs_execution_secrets" {
  name = "read-injected-secrets"
  role = aws_iam_role.ecs_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["secretsmanager:GetSecretValue"]
      Resource = [
        aws_secretsmanager_secret.app.arn,
        aws_db_instance.main.master_user_secret[0].secret_arn,
      ]
    }]
  })
}

# ── IAM: 태스크 역할 (앱이 쓰는 권한) ────────────────────────────────────────
# 현재 EC2 인스턴스 역할(db-backup.tf의 blog-ec2-backup)이 앱에 준 건 딱 하나 —
# uploads/ 로의 PutObject. routers/uploads.py가 키 없이 역할로 S3에 올린다. 그대로 미러링.
resource "aws_iam_role" "ecs_task" {
  name = "blog-ecs-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "ecs_task_s3_uploads" {
  name = "s3-put-uploads"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "PutUploadedImages"
      Effect   = "Allow"
      Action   = "s3:PutObject"
      Resource = "${aws_s3_bucket.frontend.arn}/uploads/*"
    }]
  })
}

# ── 클러스터 ──────────────────────────────────────────────────────────────────
resource "aws_ecs_cluster" "main" {
  name = "blog"
}

# ── 태스크 정의 (백엔드 서빙) ────────────────────────────────────────────────
resource "aws_ecs_task_definition" "backend" {
  family                   = "blog-backend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256" # 0.25 vCPU — Fargate 최소
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name      = "backend"
    image     = "${aws_ecr_repository.backend.repository_url}:${var.backend_image_tag}"
    essential = true

    portMappings = [{
      containerPort = 8000
      protocol      = "tcp"
    }]

    # DATABASE_URL은 여기서 조립한다 — 앱 config는 통짜 URL 하나만 받는데(database_url),
    # RDS 관리 시크릿은 password만 준다. 비번에 URL 특수문자가 있어도 깨지지 않게 python으로
    # 인코딩한 뒤 exec 한다. (이미지 변경 없이 command 오버라이드로 해결)
    command = [
      "sh", "-c",
      "export DATABASE_URL=\"postgresql://$DB_USER:$(python -c 'import urllib.parse,os;print(urllib.parse.quote(os.environ[\"DB_PASSWORD\"], safe=\"\"))')@$DB_HOST:$DB_PORT/$DB_NAME\" && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"
    ]

    # 비밀 아닌 설정. 프로드 .env와 대조해 SMTP 등은 확정할 것(아래 TODO).
    environment = [
      { name = "DB_HOST", value = aws_db_instance.main.address },
      { name = "DB_PORT", value = "5432" },
      { name = "DB_NAME", value = "blog" },
      { name = "DB_USER", value = "postgres" },
      { name = "FRONTEND_BASE_URL", value = "https://d2j66m9udyg9yq.cloudfront.net" },
      { name = "PUBLIC_BASE_URL", value = "https://d2j66m9udyg9yq.cloudfront.net" },
      { name = "S3_BUCKET", value = "blogplafromops" },
      { name = "AWS_REGION", value = "ap-northeast-2" },
      { name = "PAYMENTS_REQUIRE_LIVE", value = "true" },
      # TODO(사용자): 메일(SES) 설정을 프로드 .env에서 확인해 넣는다. 기본값(localhost)이면
      # Fargate엔 로컬 SMTP가 없어 비번재설정 메일이 500 난다. 예(SES):
      #   { name = "SMTP_HOST", value = "email-smtp.ap-northeast-2.amazonaws.com" },
      #   { name = "SMTP_PORT", value = "587" }, { name = "SMTP_USE_TLS", value = "true" },
      #   { name = "MAIL_FROM", value = "..." }  (+ SMTP_USER/PASSWORD는 아래 secrets로)
    ]

    # 비밀값 주입. DB_PASSWORD는 RDS 관리 시크릿의 password 키에서, 나머지는 blog-app-secrets에서.
    secrets = [
      { name = "DB_PASSWORD", valueFrom = "${aws_db_instance.main.master_user_secret[0].secret_arn}:password::" },
      { name = "SECRET_KEY", valueFrom = "${aws_secretsmanager_secret.app.arn}:SECRET_KEY::" },
      { name = "ANTHROPIC_API_KEY", valueFrom = "${aws_secretsmanager_secret.app.arn}:ANTHROPIC_API_KEY::" },
      { name = "LLM_ENCRYPTION_KEY", valueFrom = "${aws_secretsmanager_secret.app.arn}:LLM_ENCRYPTION_KEY::" },
      { name = "TOSS_SECRET_KEY", valueFrom = "${aws_secretsmanager_secret.app.arn}:TOSS_SECRET_KEY::" },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.backend.name
        "awslogs-region"        = "ap-northeast-2"
        "awslogs-stream-prefix" = "backend"
      }
    }
  }])
}

# ── 서비스 ────────────────────────────────────────────────────────────────────
# 태스크를 퍼블릭 서브넷 + 퍼블릭IP로 띄운다(NAT 회피). 인바운드는 task SG가 ALB로만 잠근다.
# 롤링 배포: min 100% + max 200% → 새 태스크가 healthy가 된 뒤 옛 것을 내린다(무중단).
resource "aws_ecs_service" "backend" {
  name            = "blog-backend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.backend.arn
  desired_count   = 2 # HA: 서브넷이 4개 AZ라 Fargate가 태스크를 서로 다른 AZ에 흩뿌린다.
  launch_type     = "FARGATE"

  # apply가 서비스 'steady state'까지 기다린다. 이게 없으면 태스크가 시크릿 누락·이미지 없음·
  # crash-loop로 영영 안 떠도 apply는 성공으로 끝난다("설정했다 ≠ 동작한다"의 전형).
  # 켜두면 안 뜨는 배포에서 apply가 시끄럽게 실패한다.
  wait_for_steady_state = true

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  # 기동에 시간이 걸려도(이미지 pull + lifespan) 그 사이 ALB 헬스체크로 죽이지 않게 유예.
  health_check_grace_period_seconds = 60

  # 배포가 계속 실패하면(나쁜 이미지·빠뜨린 시크릿으로 crash-loop) 무한 재시도 대신
  # 자동으로 직전 안정 배포로 롤백한다. "오류 나면 안 됨"의 안전밸브.
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.task.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.backend.arn
    container_name   = "backend"
    container_port   = 8000
  }

  # 타깃그룹이 리스너에 붙은 뒤에 서비스가 등록되게 한다.
  depends_on = [aws_lb_listener.http]

  # desired_count는 오토스케일이 조정하므로 terraform이 되돌리지 않게 무시.
  lifecycle {
    ignore_changes = [desired_count]
  }
}

# ── 오토스케일 (부하 대응) ────────────────────────────────────────────────────
# CPU 평균 60%를 목표로 태스크 수를 2~4로 자동 조절. 부하가 몰리면 늘리고, 빠지면 줄인다.
# scale-in은 천천히(5분), scale-out은 빠르게(1분) — 급증에 먼저 대응하고 급감엔 신중.
# (in-process 스케줄러가 태스크마다 도는 건 확인상 저위험: cleanup은 멱등, recorder는 과다표본뿐)
resource "aws_appautoscaling_target" "backend" {
  max_capacity       = 4
  min_capacity       = 2
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.backend.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "backend_cpu" {
  name               = "blog-backend-cpu60"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.backend.resource_id
  scalable_dimension = aws_appautoscaling_target.backend.scalable_dimension
  service_namespace  = aws_appautoscaling_target.backend.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 60
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

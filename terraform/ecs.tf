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

  # 2026-07-27 DR 게임데이 이전에는 기본값이 없는 필수 변수였다. 그 결과 ECS를 안 쓰는
  # 지금도 `terraform apply`가 "No value for required variable"로 즉시 죽었고, **재해 복구
  # 런북(RECOVERY.md 시나리오 B)의 1번 명령이 통째로 실패했다.** 사고 한복판에서 첫 삽이
  # 안 들어가는 셈이라 기본값을 뒀다.
  #
  # 빈 값의 위험(image가 'repo:'가 되어 CannotPullContainerError로 태스크가 영영 안 뜸)은
  # 사라지지 않았다 — 다만 그 검사를 "모든 apply"가 아니라 **실제로 태스크를 만들 때**로
  # 옮겼다(aws_ecs_task_definition의 precondition). 위험한 자리에서만 시끄럽게 실패한다.
  default = ""
}

# ECS/ALB/RDS를 실제로 띄울지. **기본 false** — 2026-07-24에 ECS 스택을 tear down했고,
# 지금 운영은 EC2 단일 인스턴스다.
#
# 왜 스위치가 필요한가(2026-07-27 DR 게임데이에서 실측): 이 파일들의 리소스가 무조건
# 생성되게 두면, EC2 하나를 되살리려고 친 `terraform apply`가 **tear down한 ECS·ALB·RDS
# 10개를 통째로 부활시킨다**(월 $50~70). 재해 복구 중에 쓰지도 않을 인프라가 살아나고,
# 게다가 이미지 태그가 없으니 태스크는 CannotPullContainerError로 안 떠서 노이즈만 낸다.
# → 복구 경로에서 apply의 폭발반경을 EC2로 좁히기 위한 스위치다.
variable "enable_ecs" {
  description = "ECS/ALB/RDS 스택을 생성할지. false면 EC2 단일 인스턴스 구성만 관리한다."
  type        = bool
  default     = false
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
  count = var.enable_ecs ? 1 : 0

  name = "read-injected-secrets"
  role = aws_iam_role.ecs_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["secretsmanager:GetSecretValue"]
      Resource = [
        aws_secretsmanager_secret.app.arn,
        aws_db_instance.main[0].master_user_secret[0].secret_arn,
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
  count = var.enable_ecs ? 1 : 0

  # 태그가 비면 image가 'repo:'가 되어 CannotPullContainerError로 태스크가 영영 안 뜬다.
  # 옛날엔 변수 validation으로 막았는데, 그러면 ECS를 안 쓰는 apply까지 전부 막혀
  # DR 런북이 깨졌다(2026-07-27 게임데이). 검사를 실제로 태스크를 만드는 이 자리로 옮긴다.
  lifecycle {
    precondition {
      condition     = length(var.backend_image_tag) > 0
      error_message = "enable_ecs=true면 backend_image_tag가 필요합니다. build-backend가 올린 git SHA를 -var로 넘기세요."
    }
  }

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

    # 종료 유예 120초(Fargate 최대). 기본 30초면 롤링 배포·scale-in 때 최대 60초짜리
    # AI 초안 요청이 SIGKILL로 끊겨 502가 난다. uvicorn이 PID 1이라 SIGTERM을 받아 드레인한다.
    stopTimeout = 120

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
      { name = "DB_HOST", value = aws_db_instance.main[0].address },
      { name = "DB_PORT", value = "5432" },
      { name = "DB_NAME", value = "blog" },
      { name = "DB_USER", value = "postgres" },
      { name = "FRONTEND_BASE_URL", value = "https://d2j66m9udyg9yq.cloudfront.net" },
      { name = "PUBLIC_BASE_URL", value = "https://d2j66m9udyg9yq.cloudfront.net" },
      { name = "S3_BUCKET", value = "blogplafromops" },
      { name = "AWS_REGION", value = "ap-northeast-2" },
      { name = "PAYMENTS_REQUIRE_LIVE", value = "true" },
      # CloudFront→ALB→task = 신뢰 프록시 2홉. 안 맞추면 레이트리밋이 클라가 아니라
      # CloudFront 엣지 IP를 키로 잡아 무력화된다(현행 EC2는 1홉이 기본).
      { name = "TRUSTED_PROXY_HOPS", value = "2" },
      # TODO(사용자): 메일(SES) 설정을 프로드 .env에서 확인해 넣는다. 기본값(localhost)이면
      # Fargate엔 로컬 SMTP가 없어 비번재설정 메일이 500 난다. 예(SES):
      #   { name = "SMTP_HOST", value = "email-smtp.ap-northeast-2.amazonaws.com" },
      #   { name = "SMTP_PORT", value = "587" }, { name = "SMTP_USE_TLS", value = "true" },
      #   { name = "MAIL_FROM", value = "..." }  (+ SMTP_USER/PASSWORD는 아래 secrets로)
    ]

    # 비밀값 주입. DB_PASSWORD는 RDS 관리 시크릿의 password 키에서, 나머지는 blog-app-secrets에서.
    secrets = [
      { name = "DB_PASSWORD", valueFrom = "${aws_db_instance.main[0].master_user_secret[0].secret_arn}:password::" },
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
  count = var.enable_ecs ? 1 : 0

  name            = "blog-backend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.backend[0].arn
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
    target_group_arn = aws_lb_target_group.backend[0].arn
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
  count = var.enable_ecs ? 1 : 0

  max_capacity       = 4
  min_capacity       = 2
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.backend[0].name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "backend_cpu" {
  count = var.enable_ecs ? 1 : 0

  name               = "blog-backend-cpu60"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.backend[0].resource_id
  scalable_dimension = aws_appautoscaling_target.backend[0].scalable_dimension
  service_namespace  = aws_appautoscaling_target.backend[0].service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 60
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

# EC2가 꺼진 채 RDS만 도는 상태를 1시간마다 잡아서 정지한다.
#
# 왜 필요한가: 이 계정은 12개월 프리티어가 아니라 크레딧으로 굴러간다(PAID 플랜,
# 2026-07-17 기준 $75.10 남음 / 2027-06-24 만료). 청구서의 "$0"는 무료라서가 아니라
# 크레딧이 상계해준 결과다 — RDS db.t3.micro가 24/7이면 실사용액 월 ~$16.
# 그런데 AWS는 정지된 RDS를 7일 뒤 자동으로 되살린다(정책, 끌 수 없음). 사람이 매주
# 기억해서 다시 꺼야 하는 구조라 언젠가 반드시 샌다.
#
# 이건 '아껴 쓰기'가 아니라 '낭비 막기'다. 크레딧은 2027-06-24에 소멸하므로 안 쓰고
# 남기는 데 이득이 없다 — 그래서 이 Lambda는 '의도적으로 켜둔 것'은 절대 안 끄고
# (EC2가 살아있으면 skip), 아무도 못 쓰는 상태만 정리한다.
#
# 판단 기준을 'EC2가 stopped인가'로 둔 이유: RDS는 publicly_accessible=false라
# EC2에서만 닿는다(rds.tf). 즉 EC2가 꺼진 채 도는 RDS는 정의상 아무도 못 쓴다 =
# 켜둘 이유가 없다. EC2 상태가 곧 '지금 쓰는 중인가'의 답이라, 태그 스위치나 유예시간
# 같은 장치가 필요 없다 — 사람이 뭘 기억하지 않아도 작업 중엔 안 꺼진다.
#
# EC2는 왜 대상이 아닌가: EC2를 끄려면 CloudFront 오리진 주차(terraform apply)가
# '먼저' 와야 한다(variables.tf). Lambda는 terraform을 돌릴 수 없으니, EC2를 끄면
# 주차 없이 IP만 반납되어 dangling origin이 열린다 — 막으려던 구멍을 자동화가 여는
# 셈이다. 그래서 EC2 정지는 사람 손에 남긴다.
#
# 비용: 시간당 1회 = 월 ~730회. Lambda(요청 $0.20/1M + 컴퓨트) + EventBridge
# Scheduler($1/1M) 정가로 쳐도 합쳐 월 $0.001 미만이다. 지키는 건 월 $16.

data "aws_caller_identity" "current" {}

data "archive_file" "rds_autostop" {
  type        = "zip"
  source_file = "${path.module}/lambda/rds_autostop.py"
  output_path = "${path.module}/.build/rds_autostop.zip"
}

resource "aws_iam_role" "rds_autostop" {
  name = "blog-rds-autostop"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "rds_autostop" {
  name = "blog-rds-autostop"
  role = aws_iam_role.rds_autostop.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Describe*는 리소스 단위 제한을 지원하지 않는 API라 "*"를 쓸 수밖에 없다.
        # 읽기 전용이라 이 범위로도 할 수 있는 게 없다.
        Effect   = "Allow"
        Action   = ["ec2:DescribeInstances", "rds:DescribeDBInstances"]
        Resource = "*"
      },
      {
        # 쓰기 권한은 이 DB 하나로 좁힌다. 이 역할이 탈취돼도 blog-db를 끄는 것 외엔
        # 아무것도 못 한다(삭제·스냅샷·수정 전부 없음).
        Effect   = "Allow"
        Action   = "rds:StopDBInstance"
        Resource = aws_db_instance.blog.arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:ap-northeast-2:${data.aws_caller_identity.current.account_id}:*"
      },
    ]
  })
}

resource "aws_lambda_function" "rds_autostop" {
  function_name = "blog-rds-autostop"
  role          = aws_iam_role.rds_autostop.arn
  handler       = "rds_autostop.handler"
  runtime       = "python3.12"
  timeout       = 30
  memory_size   = 128

  filename         = data.archive_file.rds_autostop.output_path
  source_code_hash = data.archive_file.rds_autostop.output_base64sha256

  environment {
    variables = {
      EC2_INSTANCE_ID = aws_instance.backend.id
      DB_INSTANCE_ID  = aws_db_instance.blog.identifier
    }
  }
}

# 로그 그룹을 terraform이 안 만들면 Lambda가 자동 생성하는데, 그때 보관기간이
# '무기한'이라 로그가 영원히 쌓인다(그것도 돈이다). 명시적으로 만들고 14일로 자른다.
resource "aws_cloudwatch_log_group" "rds_autostop" {
  name              = "/aws/lambda/${aws_lambda_function.rds_autostop.function_name}"
  retention_in_days = 14
}

# EventBridge Scheduler가 Lambda를 부를 때 쓸 역할.
resource "aws_iam_role" "rds_autostop_scheduler" {
  name = "blog-rds-autostop-scheduler"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
      # confused deputy 방지: 다른 계정의 스케줄러가 이 역할을 빌려가지 못하게 막는다.
      Condition = {
        StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }
      }
    }]
  })
}

resource "aws_iam_role_policy" "rds_autostop_scheduler" {
  name = "invoke-lambda"
  role = aws_iam_role.rds_autostop_scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = aws_lambda_function.rds_autostop.arn
    }]
  })
}

resource "aws_scheduler_schedule" "rds_autostop" {
  name = "blog-rds-autostop"
  # 자동 재시작은 7일에 한 번뿐이라 하루 1회로도 되지만, 그러면 최악의 경우 24시간
  # (~$0.5)을 켜둔 채 흘린다. 시간당으로 줄여도 호출 비용은 여전히 0원 수준이다.
  schedule_expression          = "rate(1 hour)"
  schedule_expression_timezone = "Asia/Seoul"

  flexible_time_window { mode = "OFF" }

  target {
    arn      = aws_lambda_function.rds_autostop.arn
    role_arn = aws_iam_role.rds_autostop_scheduler.arn
  }
}

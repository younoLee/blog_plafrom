# ECS 이전용 — 관리형 Postgres(RDS).
#
# 왜 다시 RDS인가: 2026-07-18에 비용으로 RDS를 EC2 컨테이너로 들어냈다. 그런데 Fargate는
# 태스크가 휘발성이라 지금처럼 호스트에 Postgres를 얹을 수 없다 → 오케스트레이션 아키텍처엔
# 관리형 DB가 정석. 이건 **크레딧으로 굴리는 기간한정 데모**라 비용을 감수한다(ROADMAP D2/D3).
# "상시 $0 운영은 EC2 컨테이너, 오케스트레이션 데모는 RDS"라는 대조가 그대로 면접 재료.
#
# 배치: 기본 VPC의 서브넷들(퍼블릭이지만) + publicly_accessible=false + SG는 Task에서만
#       → 인터넷에서 직접 못 붙는다. 다중 서브넷은 RDS가 요구하는 서브넷그룹 형식 때문.

resource "aws_db_subnet_group" "main" {
  name       = "blog-db"
  subnet_ids = data.aws_subnets.default.ids

  tags = {
    Name = "blog-db"
  }
}

resource "aws_db_instance" "main" {
  identifier     = "blog-db"
  engine         = "postgres"
  engine_version = "16" # 최신 16.x로 해석됨. apply 시 리전 가용 버전 확인.
  instance_class = "db.t4g.micro"

  # 블로그 DB는 수 MB 수준이지만 gp3 최소가 20GB. storage_encrypted는 기본 KMS라 무료.
  allocated_storage     = 20
  max_allocated_storage = 50 # 오토스케일 상한(폭주 방지). 데모라 낮게.
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = "blog" # 이관(pg_dump→restore)이 이 DB로 적재된다. DATABASE_URL의 경로와 일치해야 함.
  username = "postgres"

  # 마스터 비번을 tfvars/state에 두지 않는다 — RDS가 Secrets Manager에 만들어 관리한다.
  # 태스크 정의는 이 시크릿을 참조해 DATABASE_URL을 조립한다(Stage 4). 로테이션도 관리형.
  manage_master_user_password = true

  # Single-AZ (D1 결정). 관리형 자동 백업 7일 — RDS의 핵심 이점이자 SAA 직결 소재.
  multi_az                = false
  backup_retention_period = 7
  publicly_accessible     = false
  db_subnet_group_name    = aws_db_subnet_group.main.name
  vpc_security_group_ids  = [aws_security_group.rds.id]

  auto_minor_version_upgrade = true

  # 데모라 정리(tear down)가 매끄럽게: 최종 스냅샷 생략 + 삭제보호 해제.
  # 원본 데이터는 EC2 EBS + S3 덤프에 남아 있으므로 이 인스턴스가 유일본이 아니다.
  skip_final_snapshot = true
  deletion_protection = false

  tags = {
    Name = "blog-db"
  }
}

output "rds_endpoint" {
  value = aws_db_instance.main.address
}

# 앱이 쓸 DATABASE_URL 조립에 필요한 마스터 비번 시크릿(Secrets Manager) ARN.
# Stage 4 태스크 정의가 이 ARN에서 password를 secrets로 주입한다.
output "rds_master_secret_arn" {
  value = aws_db_instance.main.master_user_secret[0].secret_arn
}

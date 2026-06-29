# RDS PostgreSQL (백엔드 DB). 비공개 — EC2 보안그룹 경유로만 접근.
resource "aws_db_instance" "blog" {
  identifier = "blog-db"
  engine     = "postgres"
  # AWS가 자동 마이너 업그레이드(auto_minor_version_upgrade 기본 on)로 올려서 현재 라이브는 16.13.
  # 마이너 다운그레이드는 불가 → terraform이 되돌리려 하면 apply 에러. 그래서 현실값으로 맞추고
  # 아래 lifecycle에서 engine_version 변경을 무시(AWS 자동 업그레이드에 맡김).
  engine_version = "16.13"
  instance_class = "db.t3.micro"

  allocated_storage = 20
  storage_type      = "gp2"
  storage_encrypted = true

  username = "postgres"
  # password는 코드/state에 두지 않는다. 콘솔에서 설정한 값을 그대로 쓰고,
  # 아래 lifecycle로 terraform이 비번을 변경하지 못하게 막는다(유출/오변경 방지).

  multi_az                = false
  publicly_accessible     = false
  availability_zone       = "ap-northeast-2c"
  port                    = 5432
  db_subnet_group_name    = "default-vpc-0326229237c590a90"
  vpc_security_group_ids  = [aws_default_security_group.default.id]
  backup_retention_period = 1

  # 실제 라이브에 켜져 있는 기능들 — 코드에 명시 안 하면 apply 시 꺼지므로 맞춰둔다
  copy_tags_to_snapshot        = true
  performance_insights_enabled = true

  # Terraform 동작 플래그 (라이브 상태 아님). import된 state값에 맞춰 noise 제거
  apply_immediately   = false
  skip_final_snapshot = true

  lifecycle {
    # password: 코드/state에 비번 안 둠. engine_version: AWS 자동 마이너 업그레이드 표류 무시.
    ignore_changes = [password, engine_version]
  }
}

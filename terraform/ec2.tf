# EC2 백엔드 인스턴스 (Docker로 FastAPI 구동, RDS에 연결).
resource "aws_instance" "backend" {
  ami                    = "ami-0436b3a61a7a7e22a"
  instance_type          = "t2.micro"
  key_name               = "blog-key.pem"
  subnet_id              = "subnet-04bf4b4e44fe4defe"
  vpc_security_group_ids = [aws_security_group.ec2.id]

  # IMDSv2 강제 (http_tokens=required)
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
    instance_metadata_tags      = "disabled"
  }

  root_block_device {
    delete_on_termination = true
  }

  tags = {
    Name = "blog-backend " # 끝 공백은 실제 태그값 그대로
  }
}

# EC2 백엔드 보안그룹. SSH(22)는 내 IP만, API(8000)는 CloudFront만.
resource "aws_security_group" "ec2" {
  name        = "launch-wizard-1"
  description = "launch-wizard-1 created 2026-06-24T05:31:53.556Z"
  vpc_id      = "vpc-0326229237c590a90"

  # API 포트 — CloudFront(origin-facing) 관리형 prefix list만 허용.
  # 직접 IP:8000 노출 차단 → WAF·HTTPS 우회 + /docs 노출 + 평문 전송 방지.
  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    prefix_list_ids = ["pl-22a6434b"] # com.amazonaws.global.cloudfront.origin-facing
  }

  # SSH (내 IP만)
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["220.116.54.206/32"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# VPC 기본 보안그룹. RDS(blog-db)가 사용 — PostgreSQL(5432)을 EC2 SG에서만 허용.
# aws_default_security_group은 '삭제'가 아니라 '관리'만 한다(destroy해도 SG는 남고 규칙만 비워짐).
resource "aws_default_security_group" "default" {
  vpc_id = "vpc-0326229237c590a90"

  # RDS 접속: EC2 보안그룹에서 온 5432만 통과
  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ec2.id]
  }

  # 같은 보안그룹끼리 전체 허용 (default SG 기본 규칙)
  ingress {
    from_port = 0
    to_port   = 0
    protocol  = "-1"
    self      = true
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

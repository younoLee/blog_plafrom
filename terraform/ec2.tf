# EC2 백엔드 인스턴스 (Docker로 FastAPI 구동, RDS에 연결).
resource "aws_instance" "backend" {
  ami                    = "ami-0436b3a61a7a7e22a"
  instance_type          = "t2.micro"
  key_name               = "blog-key.pem"
  subnet_id              = "subnet-04bf4b4e44fe4defe"
  vpc_security_group_ids = [aws_security_group.ec2.id]

  # DB 백업(정지 절차 1단계)이 S3(blog-db-backups)에 올릴 수 있도록 인스턴스 프로파일 부여.
  # attach는 in-place(인스턴스 교체 아님). 권한은 db-backup.tf에서 PutObject로만 한정.
  iam_instance_profile = aws_iam_instance_profile.backend.name

  # IMDSv2 강제 (http_tokens=required). SSRF로 자격증명을 캐가는 걸 막는 실질 방어선 —
  # 토큰을 PUT으로 먼저 받아 헤더에 실어야 해서, 주소만 조종하는 SSRF로는 완성 못 한다.
  # (앱 측 1차 방어는 services/llm_keys.py validate_base_url)
  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
    # 2를 1로 낮추지 말 것: 백엔드가 '컨테이너' 안에서 인스턴스 역할로 S3에 업로드하는데
    # (routers/uploads.py) 도커 브리지가 홉을 하나 더 써서, 1이면 IMDS에 못 닿아 업로드가 깨진다.
    # 보안은 hop-limit이 아니라 위의 http_tokens=required가 담당한다.
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

# 퍼블릭 IP는 EIP 없이 subnet의 auto-assign(MapPublicIpOnLaunch=true)에 맡긴다.
# → 켤 때마다 IP가 바뀌므로 CloudFront 오리진은 var.backend_origin_dns로 넘긴다.
#   (정지 중엔 오리진이 주차됨. 이유는 variables.tf 참고)

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

# VPC 기본 보안그룹. RDS를 EC2 컨테이너로 이전하면서(2026-07-18) 5432 인바운드는 제거.
# 이제 DB는 compose 네트워크 내부(db:5432)로만 접근 → VPC에 노출되는 DB 포트가 없다.
# aws_default_security_group은 '삭제'가 아니라 '관리'만 한다(destroy해도 SG는 남고 규칙만 비워짐).
resource "aws_default_security_group" "default" {
  vpc_id = "vpc-0326229237c590a90"

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

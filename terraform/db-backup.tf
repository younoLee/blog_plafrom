# DB 백업: EC2 안 Postgres 컨테이너(pgdata=EBS)를 매일 pg_dump해서 S3에 올린다.
#
# 왜 필요한가: RDS를 없애고 Postgres를 EC2 컨테이너로 옮기면(rds.tf 제거) RDS가
# 주던 자동 일일 백업·PITR이 사라진다. 데이터가 단일 EBS 볼륨 하나에만 남으므로
# 인스턴스/볼륨 손실 = 데이터 소실. 그래서 매일 논리 백업(pg_dump)을 S3에 던져
# EBS와 독립된 사본을 둔다. 실제 dump 실행은 EC2의 cron(PROGRESS 참고).
#
# 비용: 블로그 DB는 수 MB 수준 → gzip dump 30일치도 S3 스토리지 월 $0.001 미만.

# 백업 버킷. 프론트 버킷(blogplafromops)과 분리한다 — 그건 CloudFront OAC 전용
# 정책이 걸려 있어 관심사가 다르다. 이 버킷은 EC2만 쓰는 비공개 백업 저장소.
resource "aws_s3_bucket" "db_backups" {
  bucket = "blog-db-backups-181568979775" # 계정ID 접미사로 전역 유일성 확보
}

# 모든 퍼블릭 액세스 차단 (백업은 절대 공개되면 안 됨)
resource "aws_s3_bucket_public_access_block" "db_backups" {
  bucket                  = aws_s3_bucket.db_backups.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# 30일 지난 백업은 자동 삭제 (무한 누적 방지, 비용/정리)
resource "aws_s3_bucket_lifecycle_configuration" "db_backups" {
  bucket = aws_s3_bucket.db_backups.id

  rule {
    id     = "expire-old-dumps"
    status = "Enabled"

    filter {} # 버킷 전체 객체 대상

    expiration {
      days = 30
    }
  }
}

# EC2가 백업 버킷에 쓸 수 있게 하는 IAM 역할(인스턴스 프로파일).
# 장기 액세스 키를 박스에 두지 않고 인스턴스 프로파일로 임시 자격증명을 받는다.
resource "aws_iam_role" "ec2_backup" {
  name = "blog-ec2-backup"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# 권한은 이 버킷에 '올리기'만. 역할이 탈취돼도 백업 업로드 외엔 못 한다
# (다른 버킷 접근·삭제·읽기 불가). rds-autostop이 StopDBInstance 하나로 좁힌 것과 같은 원칙.
resource "aws_iam_role_policy" "ec2_backup" {
  name = "s3-put-backups"
  role = aws_iam_role.ec2_backup.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "s3:PutObject"
      Resource = "${aws_s3_bucket.db_backups.arn}/*"
    }]
  })
}

resource "aws_iam_instance_profile" "backend" {
  name = "blog-backend"
  role = aws_iam_role.ec2_backup.name
}

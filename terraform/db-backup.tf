# DB 백업: EC2 안 Postgres 컨테이너(pgdata=EBS)를 pg_dump해서 S3에 올린다.
#
# 왜 필요한가: RDS를 없애고 Postgres를 EC2 컨테이너로 옮기면(rds.tf 제거) RDS가
# 주던 자동 일일 백업·PITR이 사라진다. 데이터가 단일 EBS 볼륨 하나에만 남으므로
# 인스턴스/볼륨 손실 = 데이터 소실. 그래서 논리 백업(pg_dump)을 S3에 던져
# EBS와 독립된 사본을 둔다.
#
# 언제 도는가: EC2를 끌 때마다(scripts/stop_server.sh 1단계). 원래는 EC2의 cron
# (매일 KST 03시)이었는데, 이 서버는 필요할 때만 켜므로 그 시각에 항상 꺼져 있어
# 2026-07-20까지 단 한 번도 실행되지 않았다 → cron은 제거하고 정지 절차로 옮겼다.
# DB가 바뀌는 건 EC2가 켜진 동안뿐이니 '끄기 직전'이 사본을 뜰 확실한 시점이다.
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

# 버저닝: 덮어쓰기·삭제를 되돌릴 수 있게 한다.
#
# 왜 필요한가 — 아래 IAM은 EC2에 PutObject만 준다. 그래서 "서버가 탈취돼도 백업은
# 안전하다"고 믿기 쉬운데, PutObject는 **같은 키에 덮어쓰기**를 허용한다. 버저닝이
# 없으면 공격자가(또는 실수한 운영자가) 기존 백업을 쓰레기로 덮어 파괴할 수 있고,
# 그건 되돌릴 방법이 없다. 버저닝을 켜면 덮어써도 이전 버전이 남고, delete도
# 삭제 표식(delete marker)만 얹혀 복구 가능하다. 읽기 권한이 없는 것과 별개의 축이다.
resource "aws_s3_bucket_versioning" "db_backups" {
  bucket = aws_s3_bucket.db_backups.id

  versioning_configuration {
    status = "Enabled"
  }
}

# 보관 정책.
#
# 옛 규칙은 '버킷 전체 30일'이었는데, 백업이 도는 시점이 cron(매일)이 아니라
# **정지 절차 때**로 바뀐 뒤로는 그 조합이 위험해졌다: 한 달 넘게 서버를 안 켜면
# (휴가·중단) 데이터는 EBS에 멀쩡한데 백업만 0개가 된다. cron이 한 번도 안 돌던 것과
# 똑같은 '조용한 소멸'이다. 그래서 두 가지를 바꿨다 —
#   ① 날짜별 덤프의 수명을 180일로 늘렸다(수 MB짜리라 비용은 여전히 월 $0.01 미만).
#   ② 만료 대상을 `blog-` 접두사로 좁혔다. `keep/latest.sql.gz`(정지 절차가 매번
#      최신 덤프를 승격해 두는 자리)와 `uploads/`(이미지 사본)는 만료되지 않는다.
#      → 얼마나 오래 손을 놓든 '최소 한 벌'은 항상 남는다.
resource "aws_s3_bucket_lifecycle_configuration" "db_backups" {
  bucket = aws_s3_bucket.db_backups.id

  # 버저닝이 켜진 뒤에 noncurrent 규칙이 의미를 갖는다.
  depends_on = [aws_s3_bucket_versioning.db_backups]

  rule {
    id     = "expire-old-dumps"
    status = "Enabled"

    # 날짜별 덤프만. keep/ 와 uploads/ 는 여기 안 걸린다(= 영구 보관).
    filter {
      prefix = "blog-"
    }

    expiration {
      days = 180
    }
  }

  # 버저닝을 켜면 옛 버전이 무한 누적되므로 그쪽에 상한을 둔다.
  # 90일은 '덮어쓰기 사고를 알아차릴 시간'으로 넉넉히 잡은 값.
  rule {
    id     = "expire-noncurrent"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }

  # 전송이 중간에 끊긴 멀티파트 조각은 보이지도 않으면서 요금만 먹는다.
  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
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
#
# 대상을 `blog-*`로 더 좁혔다: 백업 스크립트가 쓰는 건 날짜별 덤프뿐이고,
# `keep/latest.sql.gz`(마지막 보루)와 `uploads/`(이미지 사본)는 운영자 자격증명으로만
# 만든다. 이렇게 두면 EC2가 탈취돼도 그 두 자리는 손대지 못한다 — 버저닝이 '되돌릴 수
# 있게' 한다면 이건 애초에 '건드리지 못하게' 하는 쪽이다.
resource "aws_iam_role_policy" "ec2_backup" {
  name = "s3-put-backups"
  role = aws_iam_role.ec2_backup.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "s3:PutObject"
      Resource = "${aws_s3_bucket.db_backups.arn}/blog-*"
    }]
  })
}

resource "aws_iam_instance_profile" "backend" {
  name = "blog-backend"
  role = aws_iam_role.ec2_backup.name
}

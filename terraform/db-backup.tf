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
#      ※ 버저닝이 켜져 있으므로 180일에 지워지는 건 '현재 버전'이 아니라 delete marker가
#        얹히는 것이고, 실제 바이트는 그 뒤 expire-noncurrent(90일)가 마저 지운다.
#        그래서 실보관은 180일이 아니라 **최장 270일**이다(비용은 여전히 무시할 수준).
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
      # 날짜만으로 자르면 `keep/latest.sql.gz`가 위험해진다 — 정지할 때마다 덮어써서
      # 옛 버전이 되므로, 나쁜 덤프가 한 번 승격되고 90일이 지나면 마지막 '좋은' 사본이
      # 사라진다. 나이와 무관하게 직전 3개는 항상 남긴다.
      newer_noncurrent_versions = 3
    }
  }

  # 만료로 얹힌 delete marker는 그 아래 버전이 다 없어져도 혼자 남아 목록을 어지럽힌다.
  rule {
    id     = "clean-expired-delete-markers"
    status = "Enabled"

    filter {}

    expiration {
      expired_object_delete_marker = true
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

# 이 역할이 인스턴스에 붙는 유일한 프로파일이라, EC2가 S3에 하는 일이 전부 여기 모인다.
# 준 것은 '올리기(PutObject)' 두 자리뿐 — 읽기·삭제·목록은 어디에도 없다.
#
#  ① 백업 버킷의 `blog-*` — 날짜별 덤프. `keep/latest.sql.gz`(마지막 보루)와
#     `uploads/`(이미지 사본)는 일부러 뺐다. 그 둘은 운영자 자격증명으로만 만들므로
#     EC2가 탈취돼도 손대지 못한다. 버저닝이 '되돌릴 수 있게' 하는 쪽이라면
#     이 접두사 제한은 애초에 '건드리지 못하게' 하는 쪽이다.
#  ② 프론트 버킷의 `uploads/*` — 사용자가 올리는 이미지(아래 주석 참고).
#
# 읽기를 안 주는 게 핵심이다: 웹서버가 탈취돼도 과거 백업 전체(비밀번호 해시 포함)를
# 읽어갈 수 없다. 그 대가로 복원할 땐 운영자가 내려받아 서버로 올려야 한다
# (scripts/restore_drill.sh가 그 순서다).
resource "aws_iam_role_policy" "ec2_backup" {
  name = "s3-put-backups"
  role = aws_iam_role.ec2_backup.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "PutDbBackups"
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.db_backups.arn}/blog-*"
      },
      # 업로드 이미지. 이게 없으면 글쓰기 화면의 이미지 업로드가 AccessDenied로 죽는다.
      #
      # 왜 여기 있어야 하나 — routers/uploads.py는 키 없이 **인스턴스 역할**로 S3에 올린다
      # (ec2.tf의 IMDSv2 주석도 그 전제로 쓰여 있다). 원래 이 권한은 별도 역할
      # `blog-ec2-role`에 CLI로 만들어져 있었는데(PROGRESS.md:525, "Terraform 미관리 =
      # 드리프트"라고 스스로 적어둔 그것), 백업용 프로파일 `blog-backend`를 terraform이
      # 인스턴스에 붙이면서 그 역할이 교체됐다. EC2는 프로파일을 하나만 가질 수 있다.
      # 그래서 **이미지 업로드가 조용히 깨진 채로 남아 있었다**(2026-07-22 코드검사에서
      # 실제 AccessDenied 확인). 이제 terraform이 관리하므로 재건해도 같이 따라온다.
      #
      # 범위는 그 버킷의 uploads/ 접두사 하나뿐이다 — 프론트 번들(assets/·index.html)은
      # 못 건드리므로, 웹서버가 탈취돼도 사이트를 갈아치울 수는 없다.
      {
        Sid      = "PutUploadedImages"
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.frontend.arn}/uploads/*"
      },
    ]
  })
}

resource "aws_iam_instance_profile" "backend" {
  name = "blog-backend"
  role = aws_iam_role.ec2_backup.name
}

# 프론트엔드 정적 사이트 버킷 (CloudFront OAC로만 접근, 퍼블릭 차단)
# 지금은 버킷 본체만 선언한다. 퍼블릭 차단/정책 같은 부속 설정은
# import 후 terraform plan 차이를 보면서 하나씩 추가한다.
resource "aws_s3_bucket" "frontend" {
  bucket = "blogplafromops"
}

# 모든 퍼블릭 액세스 차단 (외부 직접 접근 막고, CloudFront OAC 경유로만 열어둠)
resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# 버저닝 — 이 버킷은 정적 사이트와 **업로드 이미지**를 같이 담고 있어서 필요하다.
#
# 이미지는 2026-06-26에 EC2 디스크에서 여기(`uploads/`)로 옮겼다. 인스턴스 교체에는
# 안전해졌지만, 대신 프론트 배포와 같은 버킷을 쓰게 됐다. 배포는 `s3 sync --delete`라
# 지금은 `--exclude "uploads/*"` 한 줄(.github/workflows/deploy.yml)만이 이미지를
# 지키고 있다 — 그 플래그를 빠뜨린 수동 sync 한 번이면 전부 사라지고, 되돌릴 수 없다.
# 게다가 이미지는 DB 덤프에도 안 들어가서 어떤 백업으로도 복구가 안 된다.
# 버저닝을 켜면 `--delete`는 삭제 표식만 얹으므로 실수를 되돌릴 수 있다.
resource "aws_s3_bucket_versioning" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  versioning_configuration {
    status = "Enabled"
  }
}

# 버저닝의 대가(옛 버전 누적)를 정리하되, 이미지는 건드리지 않는다.
#
# 처음엔 `prefix = "assets/"`로 걸었는데 **아무것도 매치하지 않았다**(2026-07-22
# 코드검사에서 발견). `frontend/vite.config.ts`가 `assetsDir: ''`라 해시 번들이
# `assets/` 폴더가 아니라 **버킷 최상위에 평평하게** 떨어지기 때문이다
# (`index-kduWxvLj.js` 등). 규칙은 있는데 대상이 0개인, 이 저장소가 계속 당해온
# "설정했는데 동작 안 함"을 내가 그대로 재현한 것이었다.
#
# 두 번째 시도(`newer_noncurrent_versions = 3`)도 **번들엔 안 걸렸다**(2026-07-22
# 코드검사에서 지적). 번들은 content hash가 파일명에 들어가서 배포마다 **키 자체가
# 바뀌고**, `s3 sync --delete`가 옛 키에 삭제 표식을 얹으면 그 키의 옛 버전은 딱
# **1개**가 된다. "더 최신인 옛 버전이 3개 넘을 때만 지운다"는 조건에 영원히 안 걸린다.
#
# 그래서 접두사로 돌아오되 **실제 산출물 이름**에 맞춘다. vite가 `assetsDir: ''`라
# 번들이 최상위에 `index-<hash>.js|css`로 떨어지고 `index.html`도 매번 갈린다 →
# 접두사 `index` 하나가 셋을 다 덮는다.
#   · `uploads/`는 이 규칙 밖이다 → 만료 규칙이 아예 없으므로 **지워진 이미지도 영구 보존**.
#     (전에는 newer_noncurrent_versions가 우연히 지켜준 것이었는데, 이제는 명시적이다)
#   · favicon.svg·icons.svg·og-image.png는 규칙 밖이라 옛 버전이 쌓인다. 거의 안 바뀌고
#     합쳐서 30KB 미만이라 그대로 둔다.
# 빌드 산출물 이름이 바뀌면 이 규칙이 다시 헛돈다 — 그때 실패 모드는 데이터 손실이
# 아니라 '옛 버전 누적'이라 비용만 조금 는다.
resource "aws_s3_bucket_lifecycle_configuration" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  depends_on = [aws_s3_bucket_versioning.frontend]

  rule {
    id     = "expire-old-spa-bundles"
    status = "Enabled"

    filter {
      prefix = "index"
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  # 삭제 표식만 남은 키를 정리한다(백업 버킷엔 이미 같은 규칙이 있다).
  rule {
    id     = "clean-expired-delete-markers"
    status = "Enabled"

    filter {}

    expiration {
      expired_object_delete_marker = true
    }
  }

  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# CloudFront(OAC)만 이 버킷 객체를 읽게 허용하는 정책.
# Condition으로 우리 배포(E1438IL9CSVBS4)에서 온 요청일 때만 통과시킨다.
resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  policy = jsonencode({
    Version = "2008-10-17"
    Id      = "PolicyForCloudFrontPrivateContent"
    Statement = [{
      Sid       = "AllowCloudFrontServicePrincipal"
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.frontend.arn}/*"
      Condition = {
        ArnLike = {
          "AWS:SourceArn" = "arn:aws:cloudfront::181568979775:distribution/E1438IL9CSVBS4"
        }
      }
    }]
  })
}

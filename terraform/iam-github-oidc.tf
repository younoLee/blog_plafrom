# GitHub Actions → AWS 인증을 '장기 액세스 키' 대신 OIDC(임시 자격증명)로 전환.
# 배포 워크플로가 GitHub이 발급한 단기 OIDC 토큰으로 아래 역할을 assume → STS 임시키를 받아 쓴다.
# 장기 키(github-actions-deploy의 AKIA...)가 필요 없어져 유출 리스크 자체가 사라진다.

# GitHub의 OIDC 신뢰 공급자 등록 (AWS 계정에 1개면 충분)
resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  # GitHub Actions OIDC 엔드포인트 인증서 지문(잘 알려진 고정값).
  # AWS는 표준 IdP엔 자체 신뢰스토어를 쓰지만, 리소스 요구사항상 명시해 둔다.
  thumbprint_list = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1c58a3a8518e8759bf075b76b750d4f2df264fca",
  ]
}

# 배포 워크플로가 assume할 역할. '이 저장소의 main 브랜치'에서 온 OIDC 토큰만 허용.
resource "aws_iam_role" "github_deploy" {
  name = "github-actions-blog-deploy"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com" }
        # 이 저장소 + main 브랜치에서 온 요청만. 다른 브랜치/태그에서도 배포하려면
        # 값을 "repo:younoLee/blog_plafrom:*" 로 넓히면 된다.
        StringLike = { "token.actions.githubusercontent.com:sub" = "repo:younoLee/blog_plafrom:ref:refs/heads/main" }
      }
    }]
  })
}

# 기존 배포 유저가 쓰던 최소권한 정책(github-brench: S3 배포 + CloudFront 무효화)을 역할에 그대로 부착.
# → 권한 범위는 동일하게 유지하고, 인증 방식만 키에서 OIDC로 바꾼다.
# 프론트 배포 권한. 원래 콘솔에서 만들어 **terraform 밖**에 있었다 —
# 즉 배포가 무슨 권한으로 도는지가 저장소 어디에도 없었다.
#
# 2026-07-22에 정확히 그 종류의 드리프트가 사고를 냈다: 이미지 업로드 권한을 담은
# 역할 `blog-ec2-role`이 CLI로 만들어져 있었는데 terraform이 다른 프로파일을 붙이면서
# 조용히 교체돼 업로드가 AccessDenied로 죽어 있었다. 남아 있던 같은 클래스가 이거라
# `terraform import`로 회수했다(내용은 그대로, plan 무변경으로 확인).
#
# 범위 주의: 이 정책은 `blogplafromops` 버킷 전체에 DeleteObject를 준다. 그 버킷엔
# 업로드 이미지(`uploads/`)도 같이 살고 그건 DB 덤프에 안 들어간다. 배포가
# `--exclude "uploads/*"`를 지키는 게 그래서 중요하다(.github/workflows/deploy.yml).
resource "aws_iam_policy" "github_deploy" {
  name = "github-brench" # 콘솔에서 붙인 이름 그대로(바꾸면 재생성된다)

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # 액션을 대상별로 쪼갠다. 예전엔 4개를 두 ARN에 통으로 묶어서 `ListBucket`이
      # `bucket/*`에, `DeleteObject`가 버킷 ARN에 걸려 있었다(무해하지만 의도가 안 읽힌다).
      # `s3:GetObject`는 뺐다 — `aws s3 sync dist/ s3://...`는 올리기만 하고 내려받지 않는다.
      {
        Sid      = "ListForSync"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.frontend.arn
      },
      {
        Sid    = "WriteSiteObjects"
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:DeleteObject", # --delete가 옛 번들을 지운다
          "s3:AbortMultipartUpload",
        ]
        Resource = "${aws_s3_bucket.frontend.arn}/*"
      },
      # 업로드 이미지는 **정책으로** 못 박는다.
      #
      # 지금까지 복구 불가능한 이미지 전체를 지키는 건 워크플로의 플래그 한 줄
      # (`--exclude "uploads/*"`)뿐이었다. 그 한 줄을 빠뜨린 sync 한 번이면 조용히 전멸한다.
      # 명시적 Deny는 같은 정책의 Allow를 이기므로, 빠뜨리면 **삭제 대신 AccessDenied로
      # 배포가 빨간불**이 된다 — 조용한 데이터 손실이 시끄러운 실패로 바뀐다.
      #
      # EC2의 이미지 업로드는 영향 없다. 그건 다른 주체(`blog-ec2-backup` 역할의
      # `PutUploadedImages`, db-backup.tf)가 하고 이 정책은 GitHub 배포 역할에만 붙는다.
      # db-backup.tf가 EC2 쪽에 이미 같은 원칙을 적용해 뒀는데 배포 쪽만 예외였다.
      {
        Sid      = "NeverTouchUploads"
        Effect   = "Deny"
        Action   = ["s3:PutObject", "s3:DeleteObject"]
        Resource = "${aws_s3_bucket.frontend.arn}/uploads/*"
      },
      {
        Sid      = "CloudFrontInvalidate"
        Effect   = "Allow"
        Action   = "cloudfront:CreateInvalidation"
        Resource = aws_cloudfront_distribution.main.arn
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "github_deploy" {
  role       = aws_iam_role.github_deploy.name
  policy_arn = aws_iam_policy.github_deploy.arn
}

# deploy.yml의 role-to-assume 에 넣을 역할 ARN (apply 후 출력됨)
output "github_deploy_role_arn" {
  value = aws_iam_role.github_deploy.arn
}

# 감시 워크플로(.github/workflows/watch.yml)가 쓰는 읽기 전용 권한.
#
# 왜 배포 정책(위 `github_deploy`)에 얹지 않고 따로 두는가 — 관심사가 다르다.
# 저건 '사이트를 배포한다', 이건 '상태를 읽는다'이고, 배포 권한이 커지는 걸 막으려면
# 읽기 전용은 분리해 두는 편이 낫다. (배포 정책 자체는 2026-07-22에 terraform으로
# 회수했다 — 그전까지 콘솔 생성이라 내용이 저장소에 없었다.)
#
# 전부 읽기다. 감시가 뭔가를 고치면 그건 더 이상 감시가 아니다.
resource "aws_iam_role_policy" "github_watch" {
  name = "watch-readonly"
  role = aws_iam_role.github_deploy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # EC2가 켜져 있는지 + 언제부터인지. 켜져 있는데 공개 API가 죽은 조합이 핵심 신호다.
        Sid      = "ReadInstanceState"
        Effect   = "Allow"
        Action   = ["ec2:DescribeInstances"]
        Resource = "*"
      },
      {
        # 백업이 실제로 쌓이는지, 만료 안 되는 사본이 있는지, 이미지 사본 개수.
        Sid    = "ListBackupsAndImages"
        Effect = "Allow"
        Action = ["s3:ListBucket"]
        Resource = [
          aws_s3_bucket.db_backups.arn,
          aws_s3_bucket.frontend.arn,
        ]
      },
      {
        # head-object로 keep/latest.sql.gz 존재 확인 (GetObject 권한이 필요하다).
        Sid      = "HeadKeepCopy"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${aws_s3_bucket.db_backups.arn}/keep/*"
      },
      {
        # SES 샌드박스 여부. 이 한 줄이 있었으면 '프로덕션 액세스 거부'를
        # 4주가 아니라 한 시간 만에 알았다.
        Sid      = "ReadSesAccountState"
        Effect   = "Allow"
        Action   = ["ses:GetAccount"]
        Resource = "*"
      },
    ]
  })
}

# ECS 이전용 — build-backend.yml이 백엔드 이미지를 빌드해 ECR에 push하는 권한.
# 배포(S3)·감시(readonly)와 관심사가 다르므로 정책을 분리한다(같은 역할에 인라인으로 부착).
# 서비스 배포(태스크 교체)는 여기 없다 — 그건 규칙7이라 사람이 한다. 여기선 push까지만.
resource "aws_iam_role_policy" "github_ecr_push" {
  name = "ecr-push-backend"
  role = aws_iam_role.github_deploy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # 레지스트리 로그인 토큰 발급. 이 액션만은 리소스 제한이 불가(*)라 따로 둔다.
        Sid      = "EcrAuthToken"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        # 실제 레이어 업로드·PutImage는 blog-backend 리포 하나로만 한정한다.
        Sid    = "EcrPushToBackendRepo"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:PutImage",
        ]
        Resource = aws_ecr_repository.backend.arn
      },
    ]
  })
}

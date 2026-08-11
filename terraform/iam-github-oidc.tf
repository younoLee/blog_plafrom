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

# 감시 워크플로(.github/workflows/watch.yml)가 쓰는 **전용 역할**.
#
# ⚠️ 2026-08-10 보안검사에서 잡힌 것: 바로 위 문단이 "관심사가 다르니 읽기 전용은 분리해
# 두는 편이 낫다"고 적어놓고, 실제로 갈린 건 **정책 문서뿐이고 역할은 하나**였다
# (`role = aws_iam_role.github_deploy.id`). 그래서 매시 도는 감시 잡이 사이트 버킷
# Put/Delete + CloudFront 무효화 권한을 **함께 쥐고** 돌았다. 주석이 옳은 원칙을 적어놨는데
# 코드가 안 따라간 자리다 — 바로 아래 ECR push 역할에는 같은 원칙을 제대로 적용해뒀으므로
# 그 형태를 복사한다.
#
# 실제 위험 크기는 작았다(watch 잡은 checkout + bash watch.sh뿐이라 오염 표면이 좁고,
# NeverTouchUploads Deny가 이미지는 지킨다). 다만 **사이트 전체는 지울 수 있었다.**
#
# 트러스트는 배포 역할과 같다(이 저장소 main 브랜치만). 권한만 읽기 전용으로 좁힌다.
resource "aws_iam_role" "github_watch" {
  name = "github-actions-blog-watch"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          "token.actions.githubusercontent.com:sub" = "repo:younoLee/blog_plafrom:ref:refs/heads/main"
        }
      }
    }]
  })
}

output "github_watch_role_arn" {
  value = aws_iam_role.github_watch.arn
}

# 전부 읽기다. 감시가 뭔가를 고치면 그건 더 이상 감시가 아니다.
resource "aws_iam_role_policy" "github_watch" {
  name = "watch-readonly"
  role = aws_iam_role.github_watch.id

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
      {
        # watch.sh 6-B(2026-08-09) — 상태검사 알람이 **사람에게 닿을 수 있는 상태인지**.
        # SNS 이메일 구독은 받는 사람이 링크를 눌러야 활성화되는데, 안 누른 동안
        # 알람은 정상적으로 울리고 아무에게도 안 간다. 07-22에 `WARN`이 종료코드에
        # 안 들어가 알림 0건이던 것과 같은 모양이라, 같은 방식으로 감시한다.
        #
        # **이 토픽 하나로 좁힌다.** `ListSubscriptionsByTopic`의 응답에는 `Endpoint`가
        # 들어 있다 — 즉 구독자의 이메일 주소다. `Resource = "*"`로 두면 이 역할을 쥔
        # 쪽이 계정의 **모든** 토픽의 구독 주소를 읽는다. 이 역할은 공개 저장소의
        # GitHub Actions가 OIDC로 assume하므로, 오염된 액션이나 빌드 의존성 하나가
        # 그 경로다.
        Sid      = "ReadAlertSubscriptions"
        Effect   = "Allow"
        Action   = ["sns:ListSubscriptionsByTopic"]
        Resource = aws_sns_topic.alerts.arn
      },
      {
        # 알람 존재·상태 확인. 위와 달리 **Resource를 좁히지 않는다.**
        #
        # 2026-08-09 처음 쓸 때 "둘 다 리소스 단위 제한을 지원하지 않는다"고 적었는데
        # **SNS 쪽은 거짓이었다**(보안검사가 잡았다). 그래서 SNS는 위에서 좁혔다.
        # CloudWatch 쪽은 아직 재보지 못했다 — IAM 시뮬레이터는 정책 문서만 평가하고,
        # 서비스가 런타임에 리소스 단위 권한을 **실제로 존중하는지**는 알려주지 않는다.
        # `DescribeAlarms`는 목록형 액션이라 "*"를 요구하는 부류일 가능성이 높다.
        #
        # 좁혔다가 틀리면 CI에서 AccessDenied가 나고 watch.sh 6-B가
        # "상태검사 알람을 못 읽었다"로 실패한다 — 조용히 눈이 머는 게 아니라
        # 시끄럽게 실패하므로 재볼 수 있는 변경이다. 다만 **재보기 전에는 넓은 쪽**을
        # 둔다. 노출되는 건 알람 이름·설명·차원이고 이 저장소는 공개다.
        # 재보려면: Resource를 알람 ARN으로 바꿔 apply하고 다음 정시 watch 실행을 본다.
        # `DescribeAlarmHistory`가 같이 있는 이유 — 알람에 `ok_actions`를 안 붙였다.
        # 복구를 전이 순간에 메일로 알리면 거짓말이 되기 때문이다(alerts.tf 참고).
        # 대신 watch.sh가 매시 이력을 읽어 '지난 24시간에 ALARM이 있었다'를 알리고,
        # 같은 실행의 1번 검사가 공개 API가 실제로 200인지를 잰다. 복구는 그 둘을
        # 같이 읽어야 참이 된다 — 그래서 이력 읽기가 알림 설계의 일부다.
        Sid      = "ReadAlarmState"
        Effect   = "Allow"
        Action   = ["cloudwatch:DescribeAlarms", "cloudwatch:DescribeAlarmHistory"]
        Resource = "*"
      },
      {
        # 하트비트 발행 — "감시가 돌았다"는 사실 자체를 AWS 쪽에 남긴다.
        # 이게 없으면 워크플로가 멈췄을 때(60일 자동정지·Actions 비활성·이 역할 삭제)
        # **완전한 침묵이 정상과 구분되지 않는다** — 알림 경로가 'Actions 실패 메일'
        # 하나뿐이라 워크플로가 안 돌면 실패 메일도 안 온다(2026-08-11 공백검사).
        # `PutMetricData`는 리소스 단위 제한을 지원하지 않는다(네임스페이스는 조건키로
        # 좁힌다 — 이 역할이 다른 지표를 덮어쓰지 못하게).
        Sid      = "PutWatchHeartbeat"
        Effect   = "Allow"
        Action   = ["cloudwatch:PutMetricData"]
        Resource = "*"
        Condition = {
          StringEquals = { "cloudwatch:namespace" = "blog/watch" }
        }
      },
      {
        # watch.sh 5번(2026-07-27 IR 훈련) — 감사기록이 살아 있는지. 침해자의 첫 수가
        # 보통 로깅 정지라 이게 꺼진 걸 늦게 알면 '누가 뭘 했나'에 영영 답할 수 없다.
        Sid      = "ReadTrailStatus"
        Effect   = "Allow"
        Action   = ["cloudtrail:GetTrailStatus"]
        Resource = aws_cloudtrail.main.arn
      },
      {
        # watch.sh 5번 — 액세스키가 늘었는지(지속성 확보 탐지)와 키 나이.
        # 키 **메타데이터만** 읽는다(ListAccessKeys는 시크릿을 주지 않는다).
        # 자원을 두 사용자로 좁힌다 — 새 사용자가 생기면 여기 추가해야 보인다는
        # 뜻이기도 하지만, 감시 역할에 계정 전체 IAM 열람을 주는 것보다 낫다.
        Sid    = "ReadAccessKeyInventory"
        Effect = "Allow"
        Action = ["iam:ListAccessKeys"]
        # 2026-08-10 보안검사: 예전엔 사용자 두 명(IAM_cli · ses-smtp-user)만 하드코딩돼
        # 있었다. 그런데 라이브 계정에는 **AdministratorAccess 사용자가 하나 더** 있었고
        # (`youno`, 콘솔 로그인 있음), 그 계정은 감시 밖이었다. 이 검사가 선언한 위협모델이
        # "공격자가 지속성 확보하려고 키를 추가한다"인데 **키를 만들 가치가 가장 큰 계정**이
        # 루프 밖에 있던 것이다. 콘솔 세션을 잡은 공격자가 거기 키를 발급하면 영원히 초록이다.
        # 게다가 하드코딩 목록이라 **새 IAM 사용자 생성 자체가 안 보였다.**
        # 그래서 열거로 바꾼다 — 사용자 이름을 코드에 박지 않으면 목록이 낡지도 않는다.
        # 여전히 읽기 전용이고, 비밀번호·정책 열람 권한은 주지 않는다.
        Resource = "*"
      },
      {
        # 위 검사가 '누구를' 볼지 정하려면 사용자 목록이 필요하다. 열거를 안 주면
        # 하드코딩으로 돌아가고, 하드코딩은 새 사용자를 못 본다(위 주석 참고).
        Sid      = "ListUsersForKeyInventory"
        Effect   = "Allow"
        Action   = ["iam:ListUsers"]
        Resource = "*"
      },
      {
        # watch.sh 6번(2026-07-30 비용 가드레일 훈련) — 예산이 아직 존재하고, 그 알림이
        # ALARM인지. 이 파일 머리말이 "살아 있는 감시는 월 예산 알림 하나뿐"이라고 적은
        # 그 알림을 감시가 되짚어 보는 자리다(감시의 감시).
        #
        # `budgets:ViewBudget` 하나로 describe-budgets·describe-notifications-for-budget이
        # 둘 다 된다. 금액과 알림 상태만 읽고 아무것도 못 바꾼다(Modify/Delete 없음).
        #
        # Cost Explorer(`ce:GetCostAndUsage`)는 **일부러 안 준다** — 요청당 $0.01이라
        # 매시 도는 감시에 넣으면 월 $7이 넘는다. 비용을 감시하려고 비용을 더 쓰는 셈이다.
        # 필요한 상세 분해는 실패 메시지에 명령을 적어 사람이 한 번 돌리게 한다.
        Sid      = "ReadBudgetState"
        Effect   = "Allow"
        Action   = ["budgets:ViewBudget"]
        Resource = "arn:aws:budgets::${data.aws_caller_identity.current.account_id}:budget/*"
      },
    ]
  })
}

# ECS 이전용 — build-backend.yml이 백엔드 이미지를 빌드해 ECR에 push하는 **전용 역할**.
# 배포 역할(github_deploy)과 분리한다. 왜: 배포 역할엔 S3 사이트 전체 Put/Delete + CloudFront
# 무효화가 있는데, 이미지 빌드 잡은 서드파티 액션과 (docker build 중) 의존성이 도는 곳이라,
# poisoned step 하나가 그 역할을 쥐면 사이트를 통째로 지울 수 있다(코드검사 지적). push엔 그
# 권한이 필요 없으니 최소권한 역할을 따로 둔다. 트러스트는 같다(이 저장소 main 브랜치만).
resource "aws_iam_role" "github_ecr_push" {
  name = "github-actions-blog-ecr-push"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com" }
        StringLike   = { "token.actions.githubusercontent.com:sub" = "repo:younoLee/blog_plafrom:ref:refs/heads/main" }
      }
    }]
  })
}

resource "aws_iam_role_policy" "github_ecr_push" {
  name = "ecr-push-backend"
  role = aws_iam_role.github_ecr_push.id

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

# build-backend.yml의 role-to-assume 에 넣을 값.
output "github_ecr_push_role_arn" {
  value = aws_iam_role.github_ecr_push.arn
}

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
resource "aws_iam_role_policy_attachment" "github_deploy" {
  role       = aws_iam_role.github_deploy.name
  policy_arn = "arn:aws:iam::181568979775:policy/github-brench"
}

# deploy.yml의 role-to-assume 에 넣을 역할 ARN (apply 후 출력됨)
output "github_deploy_role_arn" {
  value = aws_iam_role.github_deploy.arn
}

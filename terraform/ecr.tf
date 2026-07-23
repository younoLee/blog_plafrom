# 백엔드 컨테이너 이미지 레지스트리 (ECS 이전용).
#
# 지금은 EC2가 호스트에서 직접 `docker build`한다(deploy_backend.sh). ECS로 옮기면
# 태스크가 이미지를 '어딘가에서 받아와야' 하므로 레지스트리가 필요하다 → ECR.
# 프론트(S3)·백엔드(EC2 빌드)와 달리 컨테이너 이미지는 여기 한 곳에 올려둔다.
resource "aws_ecr_repository" "backend" {
  name = "blog-backend"

  # 태그 불변(IMMUTABLE): 한번 올린 태그(=git SHA)를 덮어쓸 수 없다. 배포가 항상
  # '그 SHA의 그 이미지'를 가리켜 재현 가능해진다. 그래서 움직이는 `latest`는 안 쓰고
  # 커밋 SHA로만 태깅한다(build-backend.yml).
  image_tag_mutability = "IMMUTABLE"

  # push 시 취약점 스캔(무료). 결과는 콘솔/API로 확인.
  image_scanning_configuration {
    scan_on_push = true
  }

  # 기본 AES256 암호화. KMS는 추가비용이라 이 데모엔 과투자.
  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name = "blog-backend"
  }
}

# 이미지가 무한정 쌓이면 ECR 스토리지(월 $0.10/GB)가 는다. 최근 것만 남긴다.
# SHA 태그라 배포마다 새 태그가 생기므로(옛것은 안 지워짐) 명시적 만료가 필요하다.
resource "aws_ecr_lifecycle_policy" "backend" {
  repository = aws_ecr_repository.backend.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "최근 10개 이미지만 보관"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

# build-backend.yml / 태스크 정의가 참조할 레지스트리 URL (apply 후 출력).
output "ecr_backend_repository_url" {
  value = aws_ecr_repository.backend.repository_url
}

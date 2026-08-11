# Terraform 자체 설정 + AWS 프로바이더 선언
terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.55"
    }
    # 옛 rds-autostop.tf의 Lambda zip용이었다. 그 파일은 RDS 이전(2026-07-18) 때
    # 삭제됐고 지금 archive를 쓰는 리소스는 없다.
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }

  # 원격 state (여러 기기에서 작업 가능하게, 버저닝된 버킷에 보관)
  backend "s3" {
    bucket = "blog-tfstate-181568979775"
    key    = "blog/terraform.tfstate"
    region = "ap-northeast-2"
  }
}

# 어느 AWS 계정/리전에 붙을지. 자격증명은 기존 aws configure(IAM_cli)를 자동 사용한다.
provider "aws" {
  region = "ap-northeast-2"
}

# CloudFront 스코프의 WAFv2는 리전이 us-east-1 **하나뿐**이다(글로벌 리소스라 그렇다).
# 서울 프로바이더로 부르면 WebACL을 아예 못 찾는다. waf.tf가 이 별칭을 쓴다.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}

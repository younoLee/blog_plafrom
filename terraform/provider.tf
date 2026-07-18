# Terraform 자체 설정 + AWS 프로바이더 선언
terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.55"
    }
    # rds-autostop.tf의 Lambda 소스를 zip으로 묶는 데 사용
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

# Terraform 자체 설정 + AWS 프로바이더 선언
terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# 어느 AWS 계정/리전에 붙을지. 자격증명은 기존 aws configure(IAM_cli)를 자동 사용한다.
provider "aws" {
  region = "ap-northeast-2"
}

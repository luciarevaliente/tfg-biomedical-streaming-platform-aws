terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket         = "tfg-biomedical-terraform-state"
    key            = "tfg-biomedical/terraform.tfstate"
    region         = "eu-west-1"
    dynamodb_table = "tfg-biomedical-terraform-locks"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region
}

module "biomedical_pipeline" {
  source = "./modules/biomedical_pipeline"

  aws_region   = var.aws_region
  environment  = var.environment
  project_name = var.project_name
}
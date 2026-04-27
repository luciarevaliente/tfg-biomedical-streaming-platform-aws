# Terraform configuration for the biomedical streaming platform on AWS
terraform {
  required_version = ">= 1.0"

# Define required providers and backend configuration
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

# Configure the S3 backend for Terraform state management
  backend "s3" {
    bucket         = "tfg-biomedical-terraform-state"
    key            = "tfg-biomedical/terraform.tfstate"
    region         = "eu-west-1"
    dynamodb_table = "tfg-biomedical-terraform-locks"
    encrypt        = true
  }
}

# Configure the AWS provider
provider "aws" {
  region = var.aws_region
}
# Define the biomedical pipeline module
module "biomedical_pipeline" {
  source = "./modules/biomedical_pipeline"

  aws_region   = var.aws_region
  environment  = var.environment
  project_name = var.project_name
}
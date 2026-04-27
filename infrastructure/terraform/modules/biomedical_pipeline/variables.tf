# Variables for the biomedical pipeline module

variable "aws_region" {
  description = "AWS region where resources are deployed"
  type        = string
}

variable "environment" {
  description = "Deployment environment"
  type        = string
}

variable "project_name" {
  description = "Project name"
  type        = string
}
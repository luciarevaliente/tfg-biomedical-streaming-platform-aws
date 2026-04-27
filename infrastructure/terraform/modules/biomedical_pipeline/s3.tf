# S3 bucket for raw biomedical data
resource "aws_s3_bucket" "raw_data" {
  bucket = "${var.project_name}-${var.environment}-raw-data"

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}

# Enable versioning for raw data bucket
resource "aws_s3_bucket_versioning" "raw_data_versioning" {
  bucket = aws_s3_bucket.raw_data.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Block all public access to raw data bucket
resource "aws_s3_bucket_public_access_block" "raw_data_public_access_block" {
  bucket = aws_s3_bucket.raw_data.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Enable server-side encryption for raw data bucket
resource "aws_s3_bucket_server_side_encryption_configuration" "raw_data_encryption" {
  bucket = aws_s3_bucket.raw_data.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}
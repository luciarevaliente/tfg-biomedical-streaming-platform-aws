# Kinesis
output "kinesis_stream_name" {
  description = "Name of the Kinesis Data Stream"
  value       = aws_kinesis_stream.biomedical_stream.name
}

output "kinesis_stream_arn" {
  description = "ARN of the Kinesis Data Stream"
  value       = aws_kinesis_stream.biomedical_stream.arn
}

# Lambda
output "lambda_function_name" {
  description = "Name of the Lambda function"
  value       = aws_lambda_function.biomedical_processor.function_name
}

output "lambda_function_arn" {
  description = "ARN of the Lambda function"
  value       = aws_lambda_function.biomedical_processor.arn
}

# S3
output "s3_raw_data_bucket" {
  description = "Name of the S3 bucket for raw data"
  value       = aws_s3_bucket.raw_data.id
}

# DynamoDB
output "dynamodb_table_name" {
  description = "Name of the DynamoDB table for processed data"
  value       = aws_dynamodb_table.processed_data.name
}

output "dynamodb_table_arn" {
  description = "ARN of the DynamoDB table for processed data"
  value       = aws_dynamodb_table.processed_data.arn
}

# SQS
output "sqs_dlq_url" {
  description = "URL of the SQS Dead Letter Queue"
  value       = aws_sqs_queue.dlq.url
}

output "sqs_dlq_arn" {
  description = "ARN of the SQS Dead Letter Queue"
  value       = aws_sqs_queue.dlq.arn
}

# CloudWatch
output "cloudwatch_dashboard_name" {
  description = "Name of the CloudWatch dashboard"
  value       = aws_cloudwatch_dashboard.pipeline_dashboard.dashboard_name
}
output "kinesis_stream_name" {
  description = "Name of the Kinesis Data Stream"
  value       = module.biomedical_pipeline.kinesis_stream_name
}

output "lambda_function_name" {
  description = "Name of the Lambda function"
  value       = module.biomedical_pipeline.lambda_function_name
}

output "s3_raw_data_bucket" {
  description = "Name of the S3 bucket for raw data"
  value       = module.biomedical_pipeline.s3_raw_data_bucket
}

output "dynamodb_table_name" {
  description = "Name of the DynamoDB table for processed data"
  value       = module.biomedical_pipeline.dynamodb_table_name
}

output "sqs_dlq_url" {
  description = "URL of the SQS Dead Letter Queue"
  value       = module.biomedical_pipeline.sqs_dlq_url
}

output "cloudwatch_dashboard_name" {
  description = "Name of the CloudWatch dashboard"
  value       = module.biomedical_pipeline.cloudwatch_dashboard_name
}
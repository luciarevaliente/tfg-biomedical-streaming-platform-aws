# Lambda function for biomedical data processing
resource "aws_lambda_function" "biomedical_processor" {
  filename         = "${path.module}/../../../src/lambda/handler.zip"
  function_name    = "${var.project_name}-${var.environment}-processor"
  role             = aws_iam_role.lambda_execution_role.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.11"
  timeout          = 60
  memory_size      = 128

  # Environment variables for Lambda function
  environment {
    variables = {
      S3_BUCKET_NAME   = aws_s3_bucket.raw_data.id
      DYNAMODB_TABLE   = aws_dynamodb_table.processed_data.name
      SQS_DLQ_URL      = aws_sqs_queue.dlq.url
      ENVIRONMENT      = var.environment
      PROJECT_NAME     = var.project_name
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}

# Event source mapping: Kinesis triggers Lambda
resource "aws_lambda_event_source_mapping" "kinesis_trigger" {
  event_source_arn              = aws_kinesis_stream.biomedical_stream.arn
  function_name                 = aws_lambda_function.biomedical_processor.arn
  starting_position             = "LATEST"
  batch_size                    = 100   # Process up to 100 records per batch for better throughput
  bisect_batch_on_function_error = true # Enable bisecting batches on error to isolate problematic records

  destination_config {
    on_failure {
      destination_arn = aws_sqs_queue.dlq.arn # Send failed events to SQS DLQ for later analysis
    }
  }
}
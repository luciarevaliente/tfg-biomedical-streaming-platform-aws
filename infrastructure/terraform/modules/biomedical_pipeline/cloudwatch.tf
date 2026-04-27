# CloudWatch Log Group for Lambda
resource "aws_cloudwatch_log_group" "lambda_logs" {
  name              = "/aws/lambda/${aws_lambda_function.biomedical_processor.function_name}"
  retention_in_days = 7

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}

# Alarm 1: Lambda errors
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${var.project_name}-${var.environment}-lambda-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Lambda function errors detected - pipeline may be failing"

  dimensions = {
    FunctionName = aws_lambda_function.biomedical_processor.function_name
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}

# Alarm 2: Kinesis iterator age - direct latency SLO indicator
resource "aws_cloudwatch_metric_alarm" "kinesis_iterator_age" {
  alarm_name          = "${var.project_name}-${var.environment}-kinesis-iterator-age"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "GetRecords.IteratorAgeMilliseconds"
  namespace           = "AWS/Kinesis"
  period              = 60
  statistic           = "Maximum"
  threshold           = 10000
  alarm_description   = "Kinesis iterator age exceeds 10 seconds - SLO P95 < 10s at risk"

  dimensions = {
    StreamName = aws_kinesis_stream.biomedical_stream.name
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}

# Alarm 3: DLQ messages - failed events indicator
resource "aws_cloudwatch_metric_alarm" "dlq_messages" {
  alarm_name          = "${var.project_name}-${var.environment}-dlq-messages"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Failed events detected in DLQ - data integrity at risk"

  dimensions = {
    QueueName = aws_sqs_queue.dlq.name
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}

# Custom metrics namespace for pipeline performance
resource "aws_cloudwatch_dashboard" "pipeline_dashboard" {
  dashboard_name = "${var.project_name}-${var.environment}-dashboard"

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric"
        properties = {
          title  = "Pipeline Latency (ms)"
          period = 60
          stat   = "p95"
          metrics = [
            ["BiomedicalPipeline", "PipelineLatencyMs"]
          ]
        }
      },
      {
        type = "metric"
        properties = {
          title  = "Throughput (events/s)"
          period = 60
          stat   = "Sum"
          metrics = [
            ["BiomedicalPipeline", "ProcessedEvents"]
          ]
        }
      },
      {
        type = "metric"
        properties = {
          title  = "Data Integrity - Ingested vs Stored"
          period = 60
          stat   = "Sum"
          metrics = [
            ["BiomedicalPipeline", "IngestedEvents"],
            ["BiomedicalPipeline", "StoredEvents"]
          ]
        }
      }
    ]
  })
}
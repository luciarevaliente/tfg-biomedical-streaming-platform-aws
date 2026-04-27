# SQS Dead Letter Queue for failed Lambda events
resource "aws_sqs_queue" "dlq" {
  name                      = "${var.project_name}-${var.environment}-dlq"
  message_retention_seconds = 1209600  # 14 days (maximum retention period)
  
  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}
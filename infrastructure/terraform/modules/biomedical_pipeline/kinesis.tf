# Kinesis Data Stream for biomedical data ingestion
resource "aws_kinesis_stream" "biomedical_stream" {
  name             = "${var.project_name}-${var.environment}-stream"
  shard_count      = 1
  retention_period = 24

  stream_mode_details {
    stream_mode = "PROVISIONED"
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}
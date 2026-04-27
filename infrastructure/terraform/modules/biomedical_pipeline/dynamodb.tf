# DynamoDB table for processed biomedical data
resource "aws_dynamodb_table" "processed_data" {
  name         = "${var.project_name}-${var.environment}-processed-data"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "subject_id_sensor_type"   # Composite key: subject_id + sensor_type (to avoid hot partition)
  range_key    = "sensor_timestamp"         # Sort key: sensor timestamp for time-series data

  attribute {
    name = "subject_id_sensor_type"
    type = "S"  # string
  }

  attribute {
    name = "sensor_timestamp"
    type = "N" # number (Unix timestamp)
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}
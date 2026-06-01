import json
import time
import base64
import os
import boto3
import logging
from decimal import Decimal

# Compress-Archive -Path handler.py -DestinationPath handler.zip -Force

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS clients
s3_client = boto3.client('s3')
dynamodb_resource = boto3.resource('dynamodb')
cloudwatch_client = boto3.client('cloudwatch')
sqs_client = boto3.client('sqs')

# Environment variables
S3_BUCKET_NAME = os.environ['S3_BUCKET_NAME']
DYNAMODB_TABLE = os.environ['DYNAMODB_TABLE']
SQS_DLQ_URL = os.environ['SQS_DLQ_URL']
ENVIRONMENT = os.environ['ENVIRONMENT']
PROJECT_NAME = os.environ['PROJECT_NAME']

# DynamoDB table
table = dynamodb_resource.Table(DYNAMODB_TABLE)

# Required fields for validation
REQUIRED_FIELDS = [
    'event_id', 'subject_id', 'device_id', 'sensor_type',
    'sampling_rate_hz', 'sensor_timestamp',
    'value', 'unit', 'scenario', 'schema_version'
]

# CloudWatch batch limit
CLOUDWATCH_MAX_METRICS = 1000


def lambda_handler(event, context):
    """Main Lambda handler — processes a batch of Kinesis events."""

    records = event.get('Records', [])
    logger.info(f"Received batch of {len(records)} records")

    processed_events = []
    failed_events = []
    pipeline_latencies = []

    # Write raw batch to S3
    write_raw_to_s3(records, context.aws_request_id)

    # Process each event
    for record in records:
        try:
            # T0: timestamp assignat per Kinesis quan va rebre l'event.
            # Pertany al domini temporal d'AWS (Unix epoch, segons),
            # igual que time.time() a Lambda → la resta és lliure de clock skew.
            kinesis_arrival_ts = record['kinesis']['approximateArrivalTimestamp']

            # T1: Lambda comença a processar aquest event concret
            processing_start_ts = time.time()

            # Decode event from Kinesis
            raw_data = base64.b64decode(record['kinesis']['data']).decode('utf-8')
            event_data = json.loads(raw_data)

            # Validate required fields
            validate_event(event_data)

            # T2: validació i enriquiment completats — just abans del put_item.
            # pipeline_latency_ms s'obté com T2 - T0, excloent el temps
            # d'escriptura a DynamoDB (~5-20 ms, despreciable respecte al SLO de 10.000 ms).
            processing_end_ts = time.time()

            # ── Mètriques de latència ─────────────────────────────────────────
            # Tram Kinesis → Lambda: temps que l'event va estar al buffer
            # de Kinesis abans que Lambda comencés a processar-lo
            kinesis_to_lambda_ms  = int((processing_start_ts - kinesis_arrival_ts) * 1000)

            # Tram intern Lambda: decode + validate + enrich
            processing_latency_ms = int((processing_end_ts - processing_start_ts) * 1000)

            # Latència end-to-end dins d'AWS: des que Kinesis va rebre l'event
            # fins al final del processament Lambda. Mètrica principal del SLO [LR5.1].
            pipeline_latency_ms   = int((processing_end_ts - kinesis_arrival_ts) * 1000)
            # ──────────────────────────────────────────────────────────────────

            # Build processed record — les mètriques s'inclouen en el mateix
            # put_item per evitar una segona operació d'escriptura a DynamoDB
            processed_record = float_to_decimal({
                **event_data,
                'subject_id_sensor_type':  f"{event_data['subject_id']}#{event_data['sensor_type']}",
                'event_id':                event_data['event_id'],
                'sensor_timestamp':        event_data['sensor_timestamp'],
                'kinesis_arrival_ts':      kinesis_arrival_ts,
                'processing_start_ts':     processing_start_ts,
                'processing_end_ts':       processing_end_ts,
                'kinesis_to_lambda_ms':    kinesis_to_lambda_ms,
                'processing_latency_ms':   processing_latency_ms,
                'pipeline_latency_ms':     pipeline_latency_ms,
            })

            # Write processed record (+ metrics) to DynamoDB
            write_processed_to_dynamodb(processed_record)

            logger.info(json.dumps({
                'event_id':              event_data['event_id'],
                'kinesis_to_lambda_ms':  kinesis_to_lambda_ms,
                'processing_latency_ms': processing_latency_ms,
                'pipeline_latency_ms':   pipeline_latency_ms,
            }))

            processed_events.append(processed_record)
            pipeline_latencies.append(pipeline_latency_ms)

        except Exception as e:
            logger.error(f"Failed to process record: {e}")
            failed_events.append(record)

    # Send failed events to DLQ
    if failed_events:
        send_to_dlq(failed_events)

    # Send metrics to CloudWatch
    send_metrics(
        total_records=len(records),
        processed_count=len(processed_events),
        pipeline_latencies=pipeline_latencies
    )

    logger.info(f"Processed: {len(processed_events)}, Failed: {len(failed_events)}")
    return {
        'statusCode': 200,
        'processed': len(processed_events),
        'failed': len(failed_events)
    }


def validate_event(event_data):
    """Validate that all required fields are present."""
    missing = [field for field in REQUIRED_FIELDS if field not in event_data]
    if missing:
        raise ValueError(f"Missing required fields: {missing}")


def float_to_decimal(obj):
    """Recursively convert floats to Decimal for DynamoDB compatibility."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: float_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [float_to_decimal(i) for i in obj]
    return obj


def write_raw_to_s3(records, request_id):
    """Write raw batch to S3 exactly as received from Kinesis."""
    try:
        timestamp = int(time.time())
        key = f"raw/{timestamp}_{request_id}.json"
        body = json.dumps(records)
        s3_client.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=key,
            Body=body,
            ContentType='application/json'
        )
        logger.info(f"Raw batch written to S3: {key}")
    except Exception as e:
        logger.error(f"Failed to write raw batch to S3: {e}")
        raise


def write_processed_to_dynamodb(processed_record):
    """Write processed record to DynamoDB."""
    try:
        table.put_item(Item=processed_record)
    except Exception as e:
        logger.error(f"Failed to write to DynamoDB: {e}")
        raise


def send_to_dlq(failed_events):
    """Send failed events to SQS Dead Letter Queue."""
    for record in failed_events:
        try:
            sqs_client.send_message(
                QueueUrl=SQS_DLQ_URL,
                MessageBody=json.dumps(record)
            )
        except Exception as e:
            logger.error(f"Failed to send event to DLQ: {e}")


def send_metrics(total_records, processed_count, pipeline_latencies):
    """Send custom metrics to CloudWatch in batches of max 1000."""
    try:
        metrics = [
            {
                'MetricName': 'IngestedEvents',
                'Value': total_records,
                'Unit': 'Count'
            },
            {
                'MetricName': 'ProcessedEvents',
                'Value': processed_count,
                'Unit': 'Count'
            },
            {
                'MetricName': 'StoredEvents',
                'Value': processed_count,
                'Unit': 'Count'
            }
        ]

        for latency in pipeline_latencies:
            metrics.append({
                'MetricName': 'PipelineLatencyMs',
                'Value': latency,
                'Unit': 'Milliseconds'
            })

        # Send in chunks to respect CloudWatch 1000-metric limit
        for i in range(0, len(metrics), CLOUDWATCH_MAX_METRICS):
            chunk = metrics[i:i + CLOUDWATCH_MAX_METRICS]
            cloudwatch_client.put_metric_data(
                Namespace='BiomedicalPipeline',
                MetricData=chunk
            )

    except Exception as e:
        logger.error(f"Failed to send metrics to CloudWatch: {e}")
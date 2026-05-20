import boto3
import json
import time

kinesis = boto3.client('kinesis', region_name='eu-west-1')

event = {
    "subject_id": "S1",
    "device_id": "EmpaticaE4",
    "sensor_type": "EDA",
    "sampling_rate_hz": 4,
    "sensor_timestamp": time.time(),
    "value": 0.85,
    "unit": "uS",
    "scenario": "base",
    "schema_version": "1.0"
}

response = kinesis.put_record(
    StreamName='tfg-biomedical-dev-stream',
    Data=json.dumps(event).encode('utf-8'),
    PartitionKey='S1#EDA'
)

print(f"Enviat! ShardId: {response['ShardId']}, SequenceNumber: {response['SequenceNumber']}")
print(f"sensor_timestamp: {event['sensor_timestamp']}")
print(f"subject_id_sensor_type: S1#EDA")
# print("Espera ~30s i comprova S3 i DynamoDB")
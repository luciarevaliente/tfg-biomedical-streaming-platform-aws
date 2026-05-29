"""
check_timestamps.py — Verifica distribució de registres per run_id i sensor_type
Execució: python check_timestamps.py
"""
import boto3
from decimal import Decimal
from collections import defaultdict

REGION = 'eu-west-1'
DYNAMODB_TABLE = 'tfg-biomedical-dev-processed-data'

dynamodb = boto3.resource('dynamodb', region_name=REGION)
table    = dynamodb.Table(DYNAMODB_TABLE)

print("Scanning DynamoDB...")
items = []
response = table.scan()
items.extend(response['Items'])
while 'LastEvaluatedKey' in response:
    response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
    items.extend(response['Items'])

print(f"Total records: {len(items)}\n")

# Count per run_id and sensor_type
counts = defaultdict(lambda: defaultdict(int))
for item in items:
    run_id      = int(item.get('run_id', 0))
    sensor_type = str(item.get('sensor_type', 'unknown'))
    counts[run_id][sensor_type] += 1

print("Records per run_id and sensor_type:")
print(f"{'run_id':<8} {'sensor_type':<12} {'count':<8} {'expected':<10} {'diff'}")
print("-" * 50)

expected_per_rep = {'EDA': 1200, 'TEMP': 1200}  # 4 Hz * 300s

for run_id in sorted(counts.keys()):
    for sensor_type in sorted(counts[run_id].keys()):
        count    = counts[run_id][sensor_type]
        expected = expected_per_rep.get(sensor_type, '?')
        diff     = count - expected if isinstance(expected, int) else '?'
        print(f"{run_id:<8} {sensor_type:<12} {count:<8} {expected:<10} {diff}")
    print()
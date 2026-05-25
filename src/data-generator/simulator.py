import json
import time
import boto3
import logging
import random

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger()

# AWS client
kinesis_client = boto3.client('kinesis', region_name='eu-west-1')

# Kinesis stream name
STREAM_NAME = 'tfg-biomedical-dev-stream'

# Schema version
SCHEMA_VERSION = '1.0'

# ─────────────────────────────────────────────
# SCENARIO DEFINITIONS (from TFG Annex 4)
# ─────────────────────────────────────────────

SCENARIOS = {
    'base': {
        'description': 'Base scenario — 1 subject, Empatica E4 (EDA + TEMP)',
        'duration_s': 300,       # 5 minutes
        'repetitions': 3,
        'subjects': [
            {
                'subject_id': 'S1',
                'device_id': 'EmpaticaE4',
                'sensors': [
                    {'sensor_type': 'EDA',  'sampling_rate_hz': 4,  'unit': 'uS'},
                    {'sensor_type': 'TEMP', 'sampling_rate_hz': 4,  'unit': 'C'},
                ]
            }
        ]
    },
    'sustained': {
        'description': 'Sustained load scenario — 2 subjects, full Empatica E4',
        'duration_s': 300,       # 5 minutes
        'repetitions': 3,
        'subjects': [
            {
                'subject_id': 'S1',
                'device_id': 'EmpaticaE4',
                'sensors': [
                    {'sensor_type': 'BVP',  'sampling_rate_hz': 64, 'unit': '-'},
                    {'sensor_type': 'ACC',  'sampling_rate_hz': 32, 'unit': '1/64g'},
                    {'sensor_type': 'EDA',  'sampling_rate_hz': 4,  'unit': 'uS'},
                    {'sensor_type': 'TEMP', 'sampling_rate_hz': 4,  'unit': 'C'},
                ]
            },
            {
                'subject_id': 'S2',
                'device_id': 'EmpaticaE4',
                'sensors': [
                    {'sensor_type': 'BVP',  'sampling_rate_hz': 64, 'unit': '-'},
                    {'sensor_type': 'ACC',  'sampling_rate_hz': 32, 'unit': '1/64g'},
                    {'sensor_type': 'EDA',  'sampling_rate_hz': 4,  'unit': 'uS'},
                    {'sensor_type': 'TEMP', 'sampling_rate_hz': 4,  'unit': 'C'},
                ]
            }
        ]
    },
    'peak': {
        'description': 'Peak scenario — simultaneous Empatica E4 + RespiBAN',
        'duration_s': 30,        # 30 seconds
        'repetitions': 3,
        'subjects': [
            {
                'subject_id': 'S1',
                'device_id': 'EmpaticaE4',
                'sensors': [
                    {'sensor_type': 'BVP',  'sampling_rate_hz': 64, 'unit': '-'},
                    {'sensor_type': 'ACC',  'sampling_rate_hz': 32, 'unit': '1/64g'},
                    {'sensor_type': 'EDA',  'sampling_rate_hz': 4,  'unit': 'uS'},
                    {'sensor_type': 'TEMP', 'sampling_rate_hz': 4,  'unit': 'C'},
                ]
            },
            {
                'subject_id': 'S2',
                'device_id': 'RespiBAN',
                'sensors': [
                    {'sensor_type': 'ECG',  'sampling_rate_hz': 700, 'unit': 'mV'},
                    {'sensor_type': 'EDA',  'sampling_rate_hz': 700, 'unit': 'uS'},
                    {'sensor_type': 'EMG',  'sampling_rate_hz': 700, 'unit': 'mV'},
                    {'sensor_type': 'TEMP', 'sampling_rate_hz': 700, 'unit': 'C'},
                    {'sensor_type': 'RESP', 'sampling_rate_hz': 700, 'unit': '%'},
                    {'sensor_type': 'ACC',  'sampling_rate_hz': 700, 'unit': 'g'},
                ]
            }
        ]
    }
}


# ─────────────────────────────────────────────
# EVENT GENERATION
# ─────────────────────────────────────────────

def generate_value(sensor_type):
    """Generate a realistic simulated value for each sensor type."""
    ranges = {
        'EDA':  (0.1, 20.0),
        'TEMP': (35.0, 38.5),
        'BVP':  (-200.0, 200.0),
        'ACC':  (-2.0, 2.0),
        'ECG':  (-1.5, 1.5),
        'EMG':  (-0.5, 0.5),
        'RESP': (0.0, 100.0),
    }
    low, high = ranges.get(sensor_type, (0.0, 1.0))

    # ACC is triaxial — returns a dict with x, y, z
    if sensor_type == 'ACC':
        return {
            'x': round(random.uniform(low, high), 4),
            'y': round(random.uniform(low, high), 4),
            'z': round(random.uniform(low, high), 4)
        }
    return round(random.uniform(low, high), 4)


def generate_event(subject_id, device_id, sensor_type, sampling_rate_hz, unit, scenario, run_id):
    """Build a raw event record matching the TFG data model.

    Note: ingest_timestamp is NOT included here — it is added by Lambda
    at the moment the event is received, so it reflects the real ingestion time.
    The scenario field allows filtering results per scenario during analysis.
    """
    return {
        'subject_id': subject_id,
        'device_id': device_id,
        'sensor_type': sensor_type,
        'sampling_rate_hz': sampling_rate_hz,
        'sensor_timestamp': time.time(),
        'value': generate_value(sensor_type),
        'unit': unit,
        'scenario': scenario,
        'run_id': run_id,
        'schema_version': SCHEMA_VERSION
    }


# ─────────────────────────────────────────────
# KINESIS SENDING
# ─────────────────────────────────────────────

def send_batch_to_kinesis(events):
    """Send a batch of events to Kinesis using put_records (max 500 per call)."""
    records = []
    for event in events:
        partition_key = f"{event['subject_id']}#{event['sensor_type']}"
        records.append({
            'Data': json.dumps(event).encode('utf-8'),
            'PartitionKey': partition_key
        })

    # Kinesis put_records allows max 500 records per call
    for i in range(0, len(records), 500):
        chunk = records[i:i + 500]
        try:
            response = kinesis_client.put_records(
                Records=chunk,
                StreamName=STREAM_NAME
            )
            failed = response.get('FailedRecordCount', 0)
            if failed > 0:
                logger.warning(f"{failed} records failed in Kinesis put_records")
        except Exception as e:
            logger.error(f"Error sending to Kinesis: {e}")


# ─────────────────────────────────────────────
# SCENARIO EXECUTION
# ─────────────────────────────────────────────

def run_scenario(scenario_name, scenario_config, repetition):
    """Run a single repetition of a scenario."""
    duration_s = scenario_config['duration_s']
    subjects = scenario_config['subjects']

    logger.info(
        f"  Repetition {repetition} — "
        f"duration: {duration_s}s, "
        f"subjects: {[s['subject_id'] for s in subjects]}"
    )

    # Track next emission time per sensor
    # key: (subject_id, sensor_type) -> next_emit_time
    next_emit = {}
    for subject in subjects:
        for sensor in subject['sensors']:
            key = (subject['subject_id'], sensor['sensor_type'])
            next_emit[key] = time.time()

    start_time = time.time()
    total_sent = 0

    while time.time() - start_time < duration_s:
        now = time.time()
        batch = []

        for subject in subjects:
            for sensor in subject['sensors']:
                key = (subject['subject_id'], sensor['sensor_type'])
                interval = 1.0 / sensor['sampling_rate_hz']

                # Emit all pending events for this sensor
                while next_emit[key] <= now:
                    event = generate_event(
                        subject_id=subject['subject_id'],
                        device_id=subject['device_id'],
                        sensor_type=sensor['sensor_type'],
                        sampling_rate_hz=sensor['sampling_rate_hz'],
                        unit=sensor['unit'],
                        scenario=scenario_name,
                        run_id=repetition
                    )
                    batch.append(event)
                    next_emit[key] += interval

        if batch:
            send_batch_to_kinesis(batch)
            total_sent += len(batch)

        # Small sleep to avoid busy-waiting
        time.sleep(0.01)

    elapsed = time.time() - start_time
    logger.info(f"  -> {total_sent} events sent in {elapsed:.1f}s ({total_sent/elapsed:.1f} ev/s)")
    return total_sent


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    logger.info("=" * 60)
    logger.info("BIOMEDICAL DATA SIMULATOR — TFG Lucia Revaliente")
    logger.info("=" * 60)

    for scenario_name, scenario_config in SCENARIOS.items():
        logger.info(f"\n{'─' * 60}")
        logger.info(f"SCENARIO: {scenario_config['description']}")
        logger.info(f"{'─' * 60}")

        repetitions = scenario_config['repetitions']
        total_scenario_events = 0

        for rep in range(1, repetitions + 1):
            sent = run_scenario(scenario_name, scenario_config, rep)
            total_scenario_events += sent

            # Wait 10s between repetitions to let the system stabilize
            if rep < repetitions:
                logger.info("  Waiting 10s before next repetition...")
                time.sleep(10)

        logger.info(f"  TOTAL scenario '{scenario_name}': {total_scenario_events} events")

    logger.info("\n" + "=" * 60)
    logger.info("Simulation completed.")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
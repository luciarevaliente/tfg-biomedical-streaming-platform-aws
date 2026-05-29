"""
analysis.py — Post-experiment analysis script
TFG: Arquitectura cloud distribuïda per al processament de dades biomèdiques
Lucía Revaliente Torres — UAB 2026

Execució:
    python analysis.py --scenario base
    python analysis.py --scenario sustained
    python analysis.py --scenario peak

Prerequisits:
    pip install boto3 pandas matplotlib numpy
    AWS credentials configurades (mateix perfil que el simulador)

Output (a la carpeta results_<scenario>/):
    summary.csv            — taula resum per escenari i run_id
    slo_report.csv         — criteris de superació per escenari
    integrity.csv          — integritat de dades per escenari
    throughput.csv         — throughput real vs teòric per escenari
    fig1_boxplot.png       — boxplot de les tres latències per escenari
    fig2_stacked.png       — barres apilades normalitzades ingest vs processing
    fig3_integrity.png     — IngestedEvents vs StoredEvents per escenari
    fig4_peak_timeline.png — evolució temporal de latència durant el peak
    fig5_throughput.png    — throughput real vs teòric per escenari
"""

import boto3
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from decimal import Decimal
from datetime import datetime, timezone
import os
import logging
import argparse

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

REGION = 'eu-west-1'
DYNAMODB_TABLE = 'tfg-biomedical-dev-processed-data'
CLOUDWATCH_NAMESPACE = 'BiomedicalPipeline'
PROJECT_NAME = 'tfg-biomedical-dev'

THEORETICAL_RATES = {
    'base': 8,
    'sustained': 208,
    'peak': 4304
}

SCENARIO_DURATIONS = {
    'base': 300,
    'sustained': 300,
    'peak': 30
}

SLO_PRIMARY_MS = 10_000
SLO_PEAK_MS    = 30_000

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger()

# ─────────────────────────────────────────────
# AWS CLIENTS
# ─────────────────────────────────────────────

dynamodb   = boto3.resource('dynamodb', region_name=REGION)
cloudwatch = boto3.client('cloudwatch', region_name=REGION)
sqs        = boto3.client('sqs',        region_name=REGION)

table = dynamodb.Table(DYNAMODB_TABLE)


# ─────────────────────────────────────────────
# STEP 1 — QUERY DYNAMODB
# ─────────────────────────────────────────────

def query_dynamodb():
    """Full scan of DynamoDB processed-data table. Returns a DataFrame."""
    logger.info("Querying DynamoDB...")
    items = []
    response = table.scan()
    items.extend(response['Items'])

    while 'LastEvaluatedKey' in response:
        response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
        items.extend(response['Items'])

    logger.info(f"  {len(items)} records retrieved from DynamoDB")

    def dec_to_float(obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, dict):
            return {k: dec_to_float(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [dec_to_float(i) for i in obj]
        return obj

    items = [dec_to_float(item) for item in items]
    df = pd.DataFrame(items)

    for col in ['pipeline_latency_ms', 'ingest_latency_ms', 'processing_latency_ms',
                'sensor_timestamp', 'ingest_timestamp', 'processed_timestamp']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    if 'run_id' in df.columns:
        df['run_id'] = df['run_id'].astype(int)

    logger.info(f"  Scenarios found: {df['scenario'].unique().tolist()}")
    if 'run_id' in df.columns:
        logger.info(f"  Run IDs found: {sorted(df['run_id'].unique().tolist())}")

    return df


# ─────────────────────────────────────────────
# STEP 2 — LATENCY METRICS
# ─────────────────────────────────────────────

def compute_latency_metrics(df):
    logger.info("Computing latency metrics...")

    group_cols   = ['scenario', 'run_id'] if 'run_id' in df.columns else ['scenario']
    latency_cols = ['pipeline_latency_ms', 'ingest_latency_ms', 'processing_latency_ms']

    records = []
    for group_keys, group_df in df.groupby(group_cols):
        if isinstance(group_keys, (str, int)):
            group_keys = (group_keys,)
        row = dict(zip(group_cols, group_keys))
        row['n_records'] = len(group_df)
        for col in latency_cols:
            if col in group_df.columns:
                values = group_df[col].dropna()
                row[f'{col}_p50']  = int(np.percentile(values, 50))
                row[f'{col}_p95']  = int(np.percentile(values, 95))
                row[f'{col}_p99']  = int(np.percentile(values, 99))
                row[f'{col}_mean'] = int(values.mean())
        records.append(row)

    metrics_df = pd.DataFrame(records)
    scenario_order = ['base', 'sustained', 'peak']
    metrics_df['scenario'] = pd.Categorical(
        metrics_df['scenario'], categories=scenario_order, ordered=True
    )
    sort_cols = ['scenario', 'run_id'] if 'run_id' in metrics_df.columns else ['scenario']
    metrics_df = metrics_df.sort_values(sort_cols)

    logger.info("  Latency metrics computed")
    return metrics_df


# ─────────────────────────────────────────────
# STEP 3 — DATA INTEGRITY
# ─────────────────────────────────────────────

def compute_integrity(df, scenario):
    logger.info("Computing data integrity...")

    stored_count = len(df)
    expected     = THEORETICAL_RATES[scenario] * SCENARIO_DURATIONS[scenario] * 3
    loss_rate    = max(0, (expected - stored_count) / expected * 100) if expected > 0 else 0

    # Read actual sent events from simulator output file if available.
    # Falls back to theoretical rate if file not found.
    import json as _json
    sent_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data-generator', f'sent_events_{scenario}.json')
    if os.path.exists(sent_file):
        with open(sent_file) as f:
            sent_data = _json.load(f)
        expected = sent_data['events_sent']
        logger.info(f"  Expected events from simulator: {expected}")
    else:
        expected = THEORETICAL_RATES[scenario] * SCENARIO_DURATIONS[scenario] * 3
        logger.warning(f"  sent_events_{scenario}.json not found in data-generator/, using theoretical: {expected}")

    loss_rate = max(0, (expected - stored_count) / expected * 100) if expected > 0 else 0

    integrity_df = pd.DataFrame([{
        'scenario':        scenario,
        'expected_events': expected,
        'stored_events':   stored_count,
        'loss_rate_pct':   round(loss_rate, 3),
        'slo_met':         loss_rate < 1.0
    }])

    logger.info("  Integrity computed")
    return integrity_df


# ─────────────────────────────────────────────
# STEP 4 — DLQ CHECK
# ─────────────────────────────────────────────

def check_dlq():
    logger.info("Checking DLQ...")
    try:
        queues   = sqs.list_queues(QueueNamePrefix=PROJECT_NAME)
        dlq_urls = [u for u in queues.get('QueueUrls', []) if 'dlq' in u.lower()]
        if not dlq_urls:
            logger.warning("  DLQ not found")
            return None
        attrs = sqs.get_queue_attributes(
            QueueUrl=dlq_urls[0],
            AttributeNames=['ApproximateNumberOfMessages']
        )
        count = int(attrs['Attributes'].get('ApproximateNumberOfMessages', 0))
        logger.info(f"  DLQ messages: {count}")
        return count
    except Exception as e:
        logger.warning(f"  Could not check DLQ: {e}")
        return None


# ─────────────────────────────────────────────
# STEP 5 — SLO REPORT
# ─────────────────────────────────────────────

def compute_slo_report(metrics_df, scenario):
    logger.info("Evaluating SLO compliance...")

    agg = metrics_df.groupby('scenario')['pipeline_latency_ms_p95'].max().reset_index()
    agg.columns = ['scenario', 'p95_pipeline_ms']

    rows = []
    for _, row in agg.iterrows():
        s         = row['scenario']
        p95       = row['p95_pipeline_ms']
        threshold = SLO_PRIMARY_MS if s in ('base', 'sustained') else SLO_PEAK_MS
        criterion = 'P95 < 10.000 ms' if s in ('base', 'sustained') else 'P95 < 30.000 ms (observacional)'
        rows.append({
            'scenario':        s,
            'p95_pipeline_ms': int(p95),
            'threshold_ms':    threshold,
            'criterion':       criterion,
            'slo_met':         p95 < threshold
        })

    slo_df = pd.DataFrame(rows)
    logger.info("  SLO report done")
    return slo_df


# ─────────────────────────────────────────────
# STEP 6 — THROUGHPUT
# ─────────────────────────────────────────────

def compute_throughput(integrity_df):
    logger.info("Computing throughput...")
    rows = []
    for _, row in integrity_df.iterrows():
        scenario       = row['scenario']
        stored         = row['stored_events']
        duration_total = SCENARIO_DURATIONS[scenario] * 3
        real_rate      = round(stored / duration_total, 1) if duration_total > 0 else 0
        rows.append({
            'scenario':        scenario,
            'theoretical_evs': THEORETICAL_RATES[scenario],
            'real_evs':        real_rate,
            'efficiency_pct':  round(real_rate / THEORETICAL_RATES[scenario] * 100, 1)
        })
    throughput_df = pd.DataFrame(rows)
    logger.info("  Throughput computed")
    return throughput_df


# ─────────────────────────────────────────────
# SHARED PLOT CONSTANTS
# ─────────────────────────────────────────────

SCENARIO_COLORS = {'base': '#4C72B0', 'sustained': '#DD8452', 'peak': '#C44E52'}
SCENARIO_LABELS = {
    'base':      'Base\n(~8 ev/s)',
    'sustained': 'Càrrega sostiguda\n(~208 ev/s)',
    'peak':      'Pic\n(~4.304 ev/s)'
}


# ─────────────────────────────────────────────
# FIGURE 1 — Boxplot
# ─────────────────────────────────────────────

def fig1_boxplot(df, scenario, output_dir):
    logger.info("Generating Figure 1 — Boxplot latències...")

    latency_cols = {
        'ingest_latency_ms':     'Latència ingestió',
        'processing_latency_ms': 'Latència processament',
        'pipeline_latency_ms':   'Latència pipeline (end-to-end)'
    }

    fig, axes = plt.subplots(1, 3, figsize=(15, 6), sharey=False)
    fig.suptitle(f'Distribució de latències — Escenari {scenario}', fontsize=13)

    for ax, (col, label) in zip(axes, latency_cols.items()):
        data = [df[col].dropna().values]
        bp   = ax.boxplot(
            data, patch_artist=True,
            medianprops=dict(color='black', linewidth=2),
            whiskerprops=dict(linewidth=1.2),
            capprops=dict(linewidth=1.2),
            flierprops=dict(marker='o', markersize=2, alpha=0.4)
        )
        for patch in bp['boxes']:
            patch.set_facecolor(SCENARIO_COLORS[scenario])
            patch.set_alpha(0.75)

        if col == 'pipeline_latency_ms':
            threshold = SLO_PRIMARY_MS if scenario in ('base', 'sustained') else SLO_PEAK_MS
            ax.axhline(y=threshold, color='red', linestyle='--',
                       linewidth=1.5, label=f'SLO P95 < {threshold // 1000}s')
            ax.legend(fontsize=8)

        ax.set_title(label, fontsize=11)
        ax.set_xticks([1])
        ax.set_xticklabels([SCENARIO_LABELS[scenario]], fontsize=9)
        ax.set_ylabel('Latència (ms)', fontsize=9)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'{int(x):,}'))
        ax.grid(axis='y', linestyle='--', alpha=0.4)

    plt.tight_layout()
    path = os.path.join(output_dir, 'fig1_boxplot.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    logger.info(f"  Saved: {path}")


# ─────────────────────────────────────────────
# FIGURE 2 — Barres apilades
# ─────────────────────────────────────────────

def fig2_stacked(metrics_df, scenario, output_dir):
    logger.info("Generating Figure 2 — Barres apilades normalitzades...")

    agg = metrics_df.groupby('scenario').agg(
        ingest_p95=('ingest_latency_ms_p95', 'mean'),
        processing_p95=('processing_latency_ms_p95', 'mean')
    ).reset_index()

    total          = agg['ingest_p95'].values[0] + agg['processing_p95'].values[0]
    ingest_pct     = agg['ingest_p95'].values[0]     / total * 100 if total > 0 else 0
    processing_pct = agg['processing_p95'].values[0] / total * 100 if total > 0 else 0

    fig, ax = plt.subplots(figsize=(5, 5))
    ax.bar([0], [ingest_pct],     label='Latència ingestió',      color='#4C72B0', alpha=0.85)
    ax.bar([0], [processing_pct], bottom=[ingest_pct],
           label='Latència processament', color='#DD8452', alpha=0.85)

    if ingest_pct > 5:
        ax.text(0, ingest_pct / 2, f'{ingest_pct:.1f}%',
                ha='center', va='center', fontsize=11, color='white', fontweight='bold')
    if processing_pct > 5:
        ax.text(0, ingest_pct + processing_pct / 2, f'{processing_pct:.1f}%',
                ha='center', va='center', fontsize=11, color='white', fontweight='bold')

    ax.set_xticks([0])
    ax.set_xticklabels([SCENARIO_LABELS[scenario]], fontsize=10)
    ax.set_ylabel('Proporció (%)', fontsize=10)
    ax.set_ylim(0, 100)
    ax.set_title(f'Desglose latència P95 — Escenari {scenario}', fontsize=11)
    ax.legend(fontsize=9)
    ax.grid(axis='y', linestyle='--', alpha=0.4)

    plt.tight_layout()
    path = os.path.join(output_dir, 'fig2_stacked.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    logger.info(f"  Saved: {path}")


# ─────────────────────────────────────────────
# FIGURE 3 — Integritat
# ─────────────────────────────────────────────

def fig3_integrity(integrity_df, output_dir):
    logger.info("Generating Figure 3 — Integritat de dades...")

    row   = integrity_df.iloc[0]
    fig, ax = plt.subplots(figsize=(6, 5))
    width = 0.35

    ax.bar([-width/2], [row['expected_events']], width,
           label='Events esperats (teòric)', color='#4C72B0', alpha=0.7)
    ax.bar([width/2],  [row['stored_events']],  width,
           label='Events emmagatzemats (real)', color='#55A868', alpha=0.85)

    color = 'green' if row['slo_met'] else 'red'
    ax.text(0, max(row['expected_events'], row['stored_events']) * 1.02,
            f"Pèrdua: {row['loss_rate_pct']}%",
            ha='center', va='bottom', fontsize=9, color=color, fontweight='bold')

    ax.set_xticks([0])
    ax.set_xticklabels([SCENARIO_LABELS[row['scenario']]], fontsize=10)
    ax.set_ylabel("Nombre d'events", fontsize=10)
    ax.set_title(f"Integritat de dades — Escenari {row['scenario']}", fontsize=11)
    ax.legend(fontsize=9)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'{int(x):,}'))
    ax.grid(axis='y', linestyle='--', alpha=0.4)

    plt.tight_layout()
    path = os.path.join(output_dir, 'fig3_integrity.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    logger.info(f"  Saved: {path}")


# ─────────────────────────────────────────────
# FIGURE 4 — Evolució temporal peak
# ─────────────────────────────────────────────

def fig4_peak_timeline(df, scenario, output_dir):
    logger.info("Generating Figure 4 — Evolució temporal peak...")

    if scenario != 'peak':
        logger.info("  Not peak scenario, skipping Figure 4")
        return

    if df.empty:
        logger.warning("  No peak data found, skipping Figure 4")
        return

    fig, ax = plt.subplots(figsize=(12, 5))
    colors_rep = ['#4C72B0', '#DD8452', '#C44E52']

    run_ids = sorted(df['run_id'].unique()) if 'run_id' in df.columns else [None]

    for i, run in enumerate(run_ids):
        subset = df[df['run_id'] == run].copy() if run is not None else df.copy()
        subset = subset.sort_values('sensor_timestamp')
        t0 = subset['sensor_timestamp'].min()
        subset['t_rel'] = subset['sensor_timestamp'] - t0
        subset['t_bin'] = subset['t_rel'].apply(lambda x: int(x))
        binned = subset.groupby('t_bin')['pipeline_latency_ms'].quantile(0.95).reset_index()

        label = f'Repetició {run}' if run is not None else 'Peak'
        ax.plot(binned['t_bin'], binned['pipeline_latency_ms'],
                label=label, color=colors_rep[i % len(colors_rep)],
                linewidth=1.5, alpha=0.85)

    ax.axhline(y=SLO_PRIMARY_MS, color='red',    linestyle='--', linewidth=1.5,
               label=f'SLO principal ({SLO_PRIMARY_MS // 1000}s)')
    ax.axhline(y=SLO_PEAK_MS,    color='orange', linestyle='--', linewidth=1.5,
               label=f'SLO peak observacional ({SLO_PEAK_MS // 1000}s)')

    ax.set_xlabel('Temps relatiu (s)', fontsize=10)
    ax.set_ylabel('P95 pipeline_latency_ms (ms)', fontsize=10)
    ax.set_title("Evolució temporal de la latència durant l'escenari de pic", fontsize=11)
    ax.legend(fontsize=9)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'{int(x):,}'))
    ax.grid(linestyle='--', alpha=0.4)

    plt.tight_layout()
    path = os.path.join(output_dir, 'fig4_peak_timeline.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    logger.info(f"  Saved: {path}")


# ─────────────────────────────────────────────
# FIGURE 5 — Throughput
# ─────────────────────────────────────────────

def fig5_throughput(throughput_df, output_dir):
    logger.info("Generating Figure 5 — Throughput real vs teòric...")

    row   = throughput_df.iloc[0]
    fig, ax = plt.subplots(figsize=(6, 5))
    width = 0.35

    ax.bar([-width/2], [row['theoretical_evs']], width,
           label='Taxa teòrica (ev/s)', color='#4C72B0', alpha=0.7)
    ax.bar([width/2],  [row['real_evs']],        width,
           label='Taxa real processada (ev/s)', color='#55A868', alpha=0.85)

    ax.text(width/2, row['real_evs'] * 1.05,
            f"{row['efficiency_pct']}%",
            ha='center', va='bottom', fontsize=10, fontweight='bold', color='#333333')

    ax.set_xticks([0])
    ax.set_xticklabels([SCENARIO_LABELS[row['scenario']]], fontsize=10)
    ax.set_ylabel('Events per segon (ev/s)', fontsize=10)
    ax.set_title(f"Throughput real vs teòric — Escenari {row['scenario']}", fontsize=11)
    ax.legend(fontsize=9)
    ax.set_yscale('log')
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'{int(x):,}'))
    ax.grid(axis='y', linestyle='--', alpha=0.4)

    plt.tight_layout()
    path = os.path.join(output_dir, 'fig5_throughput.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    logger.info(f"  Saved: {path}")


# ─────────────────────────────────────────────
# EXPORT CSVs + CONSOLE SUMMARY
# ─────────────────────────────────────────────

def export_results(metrics_df, slo_df, integrity_df, throughput_df, dlq_count, output_dir):
    metrics_df.to_csv(    os.path.join(output_dir, 'summary.csv'),    index=False)
    slo_df.to_csv(        os.path.join(output_dir, 'slo_report.csv'), index=False)
    integrity_df.to_csv(  os.path.join(output_dir, 'integrity.csv'),  index=False)
    throughput_df.to_csv( os.path.join(output_dir, 'throughput.csv'), index=False)

    print("\n" + "=" * 65)
    print("RESUM RESULTATS EXPERIMENTALS — TFG Lucía Revaliente Torres")
    print("=" * 65)

    print("\n── LATÈNCIA P95 pipeline_latency_ms ──")
    agg = metrics_df.groupby('scenario')['pipeline_latency_ms_p95'].max().reset_index()
    for _, row in agg.iterrows():
        print(f"  {row['scenario']:12s}  P95 = {int(row['pipeline_latency_ms_p95']):>8,} ms")

    print("\n── COMPLIMENT SLO ──")
    for _, row in slo_df.iterrows():
        status = "✓ COMPLERT" if row['slo_met'] else "✗ NO COMPLERT"
        print(f"  {row['scenario']:12s}  P95 = {int(row['p95_pipeline_ms']):>8,} ms  |  "
              f"Threshold = {row['threshold_ms']:,} ms  |  {status}")

    print("\n── INTEGRITAT DE DADES ──")
    for _, row in integrity_df.iterrows():
        status = "✓ < 1%" if row['slo_met'] else "✗ > 1%"
        print(f"  {row['scenario']:12s}  Esperats = {int(row['expected_events']):>8,}  |  "
              f"Emmagatzemats = {int(row['stored_events']):>8,}  |  "
              f"Pèrdua = {row['loss_rate_pct']:.3f}%  {status}")

    print("\n── DLQ ──")
    if dlq_count is not None:
        status = "✓ Buit" if dlq_count == 0 else f"⚠ {dlq_count} missatges"
        print(f"  Missatges a la DLQ: {dlq_count}  →  {status}")
    else:
        print("  DLQ: no s'ha pogut consultar")

    print("\n── THROUGHPUT ──")
    for _, row in throughput_df.iterrows():
        print(f"  {row['scenario']:12s}  Teòric = {row['theoretical_evs']:>6,} ev/s  |  "
              f"Real = {row['real_evs']:>6,} ev/s  |  Eficiència = {row['efficiency_pct']}%")

    print("\n" + "=" * 65)
    print(f"Resultats exportats a: {os.path.abspath(output_dir)}/")
    print("=" * 65 + "\n")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Post-experiment analysis — TFG Lucia Revaliente')
    parser.add_argument(
        '--scenario',
        choices=['base', 'sustained', 'peak'],
        required=True,
        help='Scenario to analyse (base, sustained or peak)'
    )
    args = parser.parse_args()

    scenario   = args.scenario
    base_dir   = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'experiments')
    output_dir = os.path.join(base_dir, f'results_{scenario}')
    os.makedirs(output_dir, exist_ok=True)

    # 1. Query DynamoDB and filter by scenario
    df_all = query_dynamodb()
    df = df_all[df_all['scenario'] == scenario].copy()

    if df.empty:
        logger.error(f"No records found in DynamoDB for scenario '{scenario}'. Exiting.")
        return

    logger.info(f"  {len(df)} records filtered for scenario '{scenario}'")

    # 2. Latency metrics
    metrics_df = compute_latency_metrics(df)

    # 3. Data integrity
    integrity_df = compute_integrity(df, scenario)

    # 4. DLQ check
    dlq_count = check_dlq()

    # 5. SLO report
    slo_df = compute_slo_report(metrics_df, scenario)

    # 6. Throughput
    throughput_df = compute_throughput(integrity_df)

    # 7. Figures
    fig1_boxplot(df, scenario, output_dir)
    fig2_stacked(metrics_df, scenario, output_dir)
    fig3_integrity(integrity_df, output_dir)
    fig4_peak_timeline(df, scenario, output_dir)
    fig5_throughput(throughput_df, output_dir)

    # 8. Export + summary
    export_results(metrics_df, slo_df, integrity_df, throughput_df, dlq_count, output_dir)


if __name__ == '__main__':
    main()
# Garmin Raw JSON to Observations v0

This document describes the first Garmin extraction step after the raw fetch proof.

## Purpose

This step converts wrapped Garmin raw JSON files into:

* `observations.csv`
* `health_metric.csv`

This extraction is intentionally separate from the raw fetch step.

The fetch flow remains:

```text
Garmin Connect -> raw JSON -> local outputs / GCS raw bucket
```

The extraction flow is:

```text
raw JSON -> observations.csv -> health_metric.csv
```

The extractor does not authenticate to Garmin, does not upload files to GCS, and does not write directly to BigQuery.

## Scope

The extractor currently supports a small Garmin subset:

* daily summary / steps when present in the fetched payload
* resting heart rate when present
* sleep when present
* HRV when present
* activities as activity-level observations when present

This is v0 parser logic. Actual Garmin JSON shapes may evolve as we inspect more fetched categories and more real-world payload variants.

Unsupported categories are skipped with warnings rather than failing the whole extraction run.

## CLI

Script:

```text
scripts/extraction/extract_garmin_raw_json.py
```

Python module:

```text
family_health_lake.extraction.garmin_raw_json
```

Arguments:

```text
--input-dir
--person-id
--document-id
--output-observations-csv
--output-health-metrics-csv
--write-discovery-report
```

## Input Shape

Each input JSON file is expected to match the wrapper shape created by `fetch_garmin_to_gcs.py`:

* `person_id`
* `provider`
* `source`
* `category`
* `start_date`
* `end_date`
* `fetched_at`
* `raw_payload`

The extractor currently processes only:

* `provider=garmin`
* `source=python_garminconnect`

## Mapping Config

Metric mappings live in:

```text
config/metric_mappings/garmin_raw_json_metrics.yaml
```

Initial mapped metrics:

* `steps`
* `resting_hr`
* `sleep_minutes`
* `hrv_avg`
* `activity_duration_minutes`
* `activity_distance_km`

## Example

```bash
python3 scripts/extraction/extract_garmin_raw_json.py \
  --input-dir outputs/garmin_fetch/person_id=p001/provider=garmin/date_range=2026-06-10_2026-06-16 \
  --person-id p001 \
  --document-id doc_p001_garmin_raw_2026_06_10_2026_06_16_fetch_v0 \
  --output-observations-csv outputs/garmin_observations_p001.csv \
  --output-health-metrics-csv outputs/garmin_health_metric_p001.csv \
  --write-discovery-report outputs/garmin_raw_discovery_report.json
```

## Output Behavior

The extractor:

* emits observation-first rows
* emits one `health_metric` row per converted observation
* preserves trace through `health_metric.observation_id`
* uses deterministic IDs for daily metrics and activity metrics
* includes source location hints with file name and JSON path where practical
* can write a structure-only discovery report for wrapper/category debugging without copying full raw payloads

The extractor does not:

* modify the raw fetch script
* write directly to BigQuery
* create trends, alerts, insights, dashboards, or recommendations

## Safety Notes

* do not commit real Garmin JSON
* do not commit generated CSV outputs
* do not commit credentials, tokens, `.env` files, or health data
* tests use fake wrapped Garmin JSON fixtures only

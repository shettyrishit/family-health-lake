# family-health-lake

Private repository for a personal and family health data lake. This repository is intended to contain only code, documentation, schemas, configuration, and dummy test fixtures.

## Purpose

The project organizes health data into a traceable pipeline from raw source documents through normalized observations, derived metrics, insights, coaching outputs, and dashboard views.

## Current Goal

Complete all layers for `person_id` `p001` first.

## First Vertical Slice

Tata 1mg lab report PDF -> source document -> observations -> health metrics -> trends -> alerts -> insights -> dashboard trace

## GCP Resources

- Project ID: `project-b01843b0-70b0-47d0-af0`
- Bucket: `fhl-raw-bucket-1`
- Dataset: `health_os`
- Region: `asia-south1`

## Safety Rule

Never commit real health data or credentials. Do not add medical PDFs, CSV exports, spreadsheets, service account keys, or other sensitive artifacts to this repository.

## Local Tata 1mg Extraction

Install the local dependency:

```bash
python -m pip install .
```

Run the first extractor locally against a PDF that stays outside version control:

```bash
python scripts/extraction/extract_tata_1mg_lab_report.py \
  --pdf-path /path/to/report.pdf \
  --person-id p001 \
  --document-id doc_p001_lab_2026_04_25_tata_1mg_fitness_premium \
  --metric-date 2026-04-25 \
  --output-observations-csv outputs/observations_p001_2026_04_25.csv \
  --output-health-metrics-csv outputs/health_metric_p001_2026_04_25.csv \
  --output-unconverted-observations-csv outputs/unconverted_observations_p001_2026_04_25.csv \
  --output-extraction-report-json outputs/extraction_report_p001_2026_04_25.json
```

The extractor reads metric mappings from `config/metric_mappings/tata_1mg_lab_metrics.yaml`, writes mapped observations to `observations.csv`, writes mapped normalized metrics to `health_metric.csv`, and routes obvious-but-unmapped or unclassified lab-like rows into `unconverted_observations.csv`.

Run the fake-fixture test suite with:

```bash
python3 -m pytest
```

## Garmin Cloud Fetch Spike

Use the Garmin spike CLI to authenticate to Garmin Connect, fetch raw JSON for a bounded date range, write the raw files under `outputs/`, and optionally upload the same raw files to the configured GCS raw bucket.

Install the optional Garmin dependencies:

```bash
python3 -m pip install -e ".[garmin]"
```

The current upstream `garminconnect` package release requires Python 3.12 or newer.

Authenticate to Google Application Default Credentials before using `--upload-to-gcs`:

```bash
gcloud auth application-default login
```

Run the spike locally:

```bash
GARMIN_EMAIL="..." GARMIN_PASSWORD="..." python3 scripts/spikes/fetch_garmin_to_gcs.py \
  --environment-config config/environments/dev.yaml \
  --person-id p001 \
  --start-date 2026-06-10 \
  --end-date 2026-06-16 \
  --output-dir outputs/garmin_fetch
```

Upload the same raw JSON files to GCS:

```bash
GARMIN_EMAIL="..." GARMIN_PASSWORD="..." python3 scripts/spikes/fetch_garmin_to_gcs.py \
  --environment-config config/environments/dev.yaml \
  --person-id p001 \
  --start-date 2026-06-10 \
  --end-date 2026-06-16 \
  --output-dir outputs/garmin_fetch \
  --upload-to-gcs
```

This is a raw-landing-only spike. It does not parse Garmin data into observations, does not write to BigQuery, and does not create `health_metric`, trend, alert, insight, or dashboard rows. See `docs/spikes/garmin_cloud_fetch_proof.md` for the spike scope and safety notes.

## Garmin Raw JSON Extraction

Use the Garmin raw JSON extractor to convert the wrapped Garmin fetch outputs into `observations.csv` and `health_metric.csv`.

This step is intentionally separate from the Garmin fetch step:
- fetch preserves raw JSON locally and optionally uploads it to GCS
- extraction reads those raw JSON files and emits observation-first CSV outputs

Run the extractor with:

```bash
python3 scripts/extraction/extract_garmin_raw_json.py \
  --input-dir outputs/garmin_fetch/person_id=p001/provider=garmin/date_range=2026-06-10_2026-06-16 \
  --person-id p001 \
  --document-id doc_p001_garmin_raw_2026_06_10_2026_06_16_fetch_v0 \
  --output-observations-csv outputs/garmin_observations_p001.csv \
  --output-health-metrics-csv outputs/garmin_health_metric_p001.csv \
  --write-discovery-report outputs/garmin_raw_discovery_report.json
```

This is the first Garmin extraction step. It currently supports a bounded subset of wrapped Garmin categories, writes a structure-only discovery report when requested, and skips unsupported or empty categories with clear reasons. It does not write directly to BigQuery. See `docs/spikes/garmin_raw_json_to_observations.md` for scope, mapping details, and safety notes.

## Garmin Weekly Rollup

Use the Garmin weekly rollup CLI to read Garmin daily/activity facts from BigQuery and generate synthetic weekly rollup observations plus weekly health metrics.

This is a weekly facts layer, not an insight or coaching layer.

Run it with:

```bash
python3 scripts/synthesis/generate_garmin_weekly_rollup.py \
  --environment-config config/environments/dev.yaml \
  --person-id p001 \
  --start-date 2026-06-01 \
  --end-date 2026-06-28 \
  --output-observations-csv outputs/garmin_weekly_observations_p001.csv \
  --output-health-metrics-csv outputs/garmin_weekly_health_metric_p001.csv
```

Load the same weekly rollups back to BigQuery using non-streaming batch load/query jobs:

```bash
python3 scripts/synthesis/generate_garmin_weekly_rollup.py \
  --environment-config config/environments/dev.yaml \
  --person-id p001 \
  --start-date 2026-06-01 \
  --end-date 2026-06-28 \
  --output-observations-csv outputs/garmin_weekly_observations_p001.csv \
  --output-health-metrics-csv outputs/garmin_weekly_health_metric_p001.csv \
  --load-to-bigquery \
  --replace-existing
```

The rollup uses Monday as `week_start`, treats weekly outputs as synthetic observations derived from Garmin daily/activity metrics, and stores compact source trace in `notes`. See `docs/spikes/garmin_weekly_rollup_v0.md` for scope and traceability notes.

## Local BigQuery Load

Install the optional BigQuery dependencies when you want to load extractor outputs into BigQuery:

```bash
python -m pip install -e ".[bigquery]"
```

If your system Python is externally managed and refuses direct installs, create a local virtual environment first:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[bigquery]"
```

Authenticate locally with Google Application Default Credentials before running the loader:

```bash
gcloud auth application-default login
```

The loader:
- uses ADC through the `google-cloud-bigquery` client
- reads `project_id` and `dataset` from `config/environments/dev.yaml`
- uses BigQuery batch load/query jobs to avoid streaming buffer issues
- does not read credentials from repo config
- does not create or require service account key files
- does not rely on the global `gcloud` project setting

Load extracted observations and health metrics into the configured dataset with:

```bash
python3 scripts/ingestion/load_extracted_csvs_to_bigquery.py \
  --environment-config config/environments/dev.yaml \
  --observations-csv outputs/observations_p001_2026_04_25.csv \
  --health-metrics-csv outputs/health_metric_p001_2026_04_25.csv \
  --document-id doc_p001_lab_2026_04_25_tata_1mg_fitness_premium \
  --person-id p001 \
  --replace-existing
```

When `--replace-existing` is provided, the loader deletes existing `observation` and `health_metric` rows for the given `document_id` and `person_id` before inserting the new CSV contents.

## Local Thyroid Intelligence

Use the thyroid synthesis CLI to read thyroid `health_metric` rows from BigQuery and write traceable `metric_trend`, `alert`, and `insight` rows for the same `person_id` and `document_id`.

Install the optional BigQuery dependencies if needed:

```bash
python -m pip install -e ".[bigquery]"
```

If your system Python is externally managed and refuses direct installs, use a local virtual environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[bigquery]"
```

The thyroid synthesis CLI:
- uses ADC through the `google-cloud-bigquery` client
- reads `project_id` and `dataset` from `config/environments/dev.yaml`
- reads thyroid metrics from `health_metric`
- writes thyroid intelligence rows to `metric_trend`, `alert`, and `insight` using BigQuery query jobs
- does not use BigQuery streaming inserts for derived intelligence writes
- does not generate coach recommendations

Run it with:

```bash
python3 scripts/synthesis/generate_thyroid_intelligence.py \
  --environment-config config/environments/dev.yaml \
  --person-id p001 \
  --document-id doc_p001_lab_2026_04_25_tata_1mg_fitness_premium \
  --replace-existing
```

When `--replace-existing` is provided, the CLI runs `DELETE` query jobs for existing thyroid `metric_trend`, `alert`, and `insight` rows for the same `person_id` whose `source_document_ids` contain the target `document_id`, then runs `INSERT` query jobs for the newly generated rows.

## Local Thyroid Dashboard Markdown

Use the dashboard renderer CLI to read the thyroid dashboard view from BigQuery and write a human-readable Markdown card under `outputs/`.

Install the optional BigQuery dependencies if needed:

```bash
python -m pip install -e ".[bigquery]"
```

If your system Python is externally managed and refuses direct installs, use a local virtual environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[bigquery]"
```

The thyroid dashboard renderer:
- uses ADC through the `google-cloud-bigquery` client
- reads `project_id` and `dataset` from `config/environments/dev.yaml`
- reads summary rows from `v_thyroid_dashboard_card`
- reads metric and trace rows from `v_thyroid_dashboard_trace`
- renders a simple Markdown card with insight, alert, trend, metrics, and trace
- does not generate coach recommendations

Run it with:

```bash
python3 scripts/dashboard/render_thyroid_dashboard_markdown.py \
  --environment-config config/environments/dev.yaml \
  --person-id p001 \
  --output-md outputs/thyroid_dashboard_p001.md
```

## Admin: Scrub Person Data

Use the admin script to scrub BigQuery data for a specific `person_id`. This is useful for rerunning extraction flows or completely removing a person from the dataset.

**Note: This script only scrubs BigQuery rows and does not delete raw files from Google Cloud Storage.**

There are two modes:
1. `generated` (default): Deletes only derived/generated data (`insight`, `alert`, `metric_trend`, `health_metric`, `observation`). Preserves `source_document` and `person` metadata.
2. `full-person`: Deletes everything for the person, including metadata (`source_document` and `person`).

Example dry run (generated mode):
```bash
python3 scripts/admin/scrub_person_bigquery_data.py \
  --environment-config config/environments/dev.yaml \
  --person-id p001
```

Example execute (generated mode):
```bash
python3 scripts/admin/scrub_person_bigquery_data.py \
  --environment-config config/environments/dev.yaml \
  --person-id p001 \
  --mode generated \
  --confirm-person-id p001 \
  --execute
```

Example execute (full-person mode):
```bash
python3 scripts/admin/scrub_person_bigquery_data.py \
  --environment-config config/environments/dev.yaml \
  --person-id p001 \
  --mode full-person \
  --confirm-person-id p001 \
  --execute
```

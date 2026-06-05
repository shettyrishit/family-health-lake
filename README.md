# family-health-lake

Private repository for a personal and family health data lake. This repository is intended to contain only code, documentation, schemas, configuration, and dummy test fixtures.

## Purpose

The project organizes health data into a traceable pipeline from raw source documents through normalized observations, derived metrics, insights, coaching outputs, and dashboard views.

## Current Goal

Complete all layers for `person_id` `p001` first.

## First Vertical Slice

Tata 1mg lab report PDF -> source document -> observations -> health metrics -> trends -> alerts -> insights -> coach recommendation -> dashboard trace

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

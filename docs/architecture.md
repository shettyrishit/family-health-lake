# Architecture

Family Health Lake is organized as a layered system.

## Layers

1. Ingestion Layer
2. Observation Layer
3. Normalization / Metric Layer
4. Trend + Alert Layer
5. Synthesis / Insight Layer
6. Personal Coach Layer
7. Dashboard Layer

## End-to-End Flow

Source Data  
→ Raw Data in Google Cloud Storage  
→ Source Document Metadata in BigQuery  
→ Observations  
→ Metrics  
→ Trends  
→ Alerts  
→ Insights  
→ Coach Recommendations  
→ Dashboard

## Raw Storage

Google Cloud Storage stores raw files before interpretation.
Raw data should be preserved before extraction or synthesis.

Example:

```text
gs://fhl-raw-bucket-1/raw/person_id=p001/labs/pdf/2026/04/25/report.pdf
```

## Structured Storage

BigQuery stores structured entities such as:

→ person
→ source_document
→ observation
→ health_metric
→ metric_trend
→ alert
→ insight
→ recommendation

## Current Environment

Environment-specific GCP configuration is stored in:

`config/environments/dev.yaml`

The current v1 environment uses Google Cloud Storage for raw files and BigQuery for structured entities.
# health_metric.csv Schema

This file defines the CSV contract for normalized, queryable health metrics.

## Columns

| Column | Meaning |
|---|---|
| metric_id | Deterministic unique ID for the metric |
| person_id | Person this metric belongs to, e.g. `p001` |
| document_id | Source document ID, if applicable |
| observation_id | Source observation ID for traceability |
| metric_date | Date of metric measurement |
| source | Source system, e.g. `tata_1mg`, `garmin`, `fittr` |
| category | Metric category, e.g. `thyroid`, `lipids`, `recovery` |
| metric_name | Standard metric name, e.g. `TSH`, `Free T4`, `VO2 Max` |
| value | Numeric metric value if available |
| text_value | Raw text value when needed, e.g. `>1000` or `<1.0` |
| unit | Unit of measure |
| reference_low | Lower reference bound, if available |
| reference_high | Upper reference bound, if available |
| status | `normal`, `high`, `low`, `low_normal`, `above_desirable`, or `tracked` |
| notes | Additional context |

## Purpose

Health metrics are normalized values used for trends, alerts, insights, coach recommendations, and dashboards.

Each metric should preserve traceability through `observation_id`.
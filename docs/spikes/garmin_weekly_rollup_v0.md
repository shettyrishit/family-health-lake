# Garmin Weekly Rollup v0

This document describes the first Garmin weekly facts layer for the Family Health Lake.

## Purpose

This step reads Garmin daily and activity metrics from BigQuery and writes synthetic weekly rollup:

* `observations.csv`
* `health_metric.csv`

These weekly rows are facts, not insights or coaching outputs.

## Scope

This v0 rollup:

* reads Garmin metrics from BigQuery
* groups them by calendar week
* uses Monday as `week_start`
* emits synthetic weekly observations
* emits weekly normalized health metrics
* can optionally load the generated weekly rows back to BigQuery with non-streaming load/query jobs

This v0 rollup does **not**:

* create trends
* create alerts
* create insights
* create dashboards
* create recommendations

## Source Inputs

The rollup reads Garmin daily/activity facts for:

* `person_id = --person-id`
* `metric_date between --start-date and --end-date`
* `source = garmin_connect_raw_json`

It prefers reading from:

```text
v_garmin_daily_metrics
```

If that view does not exist, it falls back to joining:

* `health_metric`
* `observation`

## Weekly Metrics in v0

* `Average Steps`
* `Average Resting HR`
* `Average HRV`
* `Average Sleep`
* `Activity Count`
* `Total Activity Duration`
* `Total Activity Distance`

Optional type-specific weekly counts such as cardio/strength are not required for v0.

## Synthetic Observation Rules

Weekly rollups are written as synthetic observations with:

* `source = garmin_weekly_rollup`
* `observation_type = weekly_rollup`
* `observed_at = week_start`
* `conversion_status = converted`

Each weekly `health_metric` row points back to the synthetic weekly `observation_id`.

## Traceability

Weekly rows are derived from Garmin daily/activity facts.

Long-term, this may deserve a dedicated derivation table such as `metric_derivation`.

In v0, source lineage is stored compactly in the `notes` field as JSON containing source metric IDs and source observation IDs where available.

## Example

```bash
python3 scripts/synthesis/generate_garmin_weekly_rollup.py \
  --environment-config config/environments/dev.yaml \
  --person-id p001 \
  --start-date 2026-06-01 \
  --end-date 2026-06-28 \
  --output-observations-csv outputs/garmin_weekly_observations_p001.csv \
  --output-health-metrics-csv outputs/garmin_weekly_health_metric_p001.csv
```

Load the same weekly rollups to BigQuery:

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

## Safety Notes

* do not commit real Garmin data
* do not commit outputs
* do not commit credentials, tokens, `.env` files, or health data
* tests for this step use fake BigQuery/query results only

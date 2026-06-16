# Roadmap

## Current Goal

Complete all layers for `person_id = p001`.

The system should be built as vertical slices, not by integrating every source first.

## Milestone 1: Repo and Cloud Foundation

Status: Completed

- Private GitHub repo created
- GCP project created
- Cloud Storage bucket created
- BigQuery dataset created
- Initial base tables created
- Initial Tata 1mg report uploaded to raw storage

## Milestone 2: Product and Data Model Foundation

Status: Completed

- Document product concept
- Document architecture
- Document traceability principle
- Document data model
- Add environment config
- Add health taxonomies
- Add observation-first model

## Milestone 3: BigQuery Schema Upgrade

Status: Mostly Completed [recommendation is for later]

Add schema files for:

- person
- source_document
- observation
- health_metric
- metric_trend
- alert
- insight
- recommendation

Also update the live BigQuery dataset to support `observation_id` trace from `health_metric`.

## Milestone 4: TaTata 1mg PDF

Status: Completed

→ extraction
→ observations + health metrics
→ BigQuery load
→ thyroid intelligence
→ markdown thyroid dashboard

## Garmin Cloud Fetch Proof v0
- Garmin authentication works, including MFA
- Raw Garmin data downloads locally
- Raw Garmin payloads upload to GCS
- No observation/metric conversion yet
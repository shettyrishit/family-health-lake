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

## Future Work: Evaluate Open Wearables as Multi-Provider Wearable Gateway

Current Garmin ingestion is built using `python-garminconnect` as a Garmin-specific fetch adapter. This is acceptable for the current personal Health Lake phase because it proves:

- Garmin authentication works
- Raw Garmin data can be fetched locally
- Raw Garmin payloads can land in GCS
- Downstream extraction into observations and health metrics is independent of the fetcher

However, this should not be treated as the final long-term wearable integration strategy.

Evaluate Open Wearables / openwearables.io later as a self-hosted multi-provider wearable data gateway, especially if the Health Lake expands beyond one Garmin user or needs support for multiple wearable providers.

Evaluation questions:

1. Can Open Wearables be hosted cleanly on GCP?
2. Can it connect Garmin reliably?
3. Which Garmin data categories are available today?
   - activities
   - steps
   - sleep
   - resting heart rate
   - HRV
   - heart rate
   - intensity minutes
   - VO₂ max, if available
4. Can sync be triggered on schedule or manually?
5. Can fetched data be exported cleanly to GCS raw landing paths?
6. Does it preserve enough provider/source metadata for traceability?
7. Does it support additional providers useful later, such as Oura, Whoop, Fitbit, Apple Health, Health Connect, Ultrahuman, or others?
8. Is it simpler to operate than maintaining provider-specific fetchers?
9. Can it coexist with provider-specific command adapters such as `python-garminconnect` for Garmin workout upload/scheduling?

Target long-term architecture:

```text
Wearable provider
→ Open Wearables or provider-specific fetcher
→ GCS raw landing
→ Health Lake observations
→ health_metric
→ trends / alerts / insights
→ dashboard / coach
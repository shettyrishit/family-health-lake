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

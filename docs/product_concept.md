# Product Concept

Family Health Lake is a personal/family health data system that preserves raw health data, extracts observations and metrics, computes trends and alerts, generates taxonomy-level insights, and enables a person-specific coach to produce recommendations.

The first goal is to complete all layers for `person_id = p001`.

## Input Sources

Data may come from sources such as:

- Garmin Connect
- FITTR Hart / body composition devices
- Tata 1mg or other lab reports
- Medical prescriptions and imaging reports
- Recovery and symptom notes
- Supplement and medication routines
- Manual measurements such as waist

## Taxonomies

All input data is classified into one of the following health taxonomies:

1. Training & Activity
2. Recovery & Sleep
3. Nutrition & Supplements
4. Body Composition
5. Medical & Lab Reports
6. Symptoms & Notes

A system taxonomy called `Unidentified` is used when data cannot yet be classified. This is used for process improvement, not as a normal health category.

## Core Pipeline

Source Data  
→ Raw Data Preservation  
→ Observation Extraction  
→ Taxonomy Classification  
→ Metric Conversion / Unconverted Observation Handling  
→ Metric Trends  
→ Metric Alerts  
→ Taxonomy Insights  
→ Insight Trends  
→ Insight Alerts  
→ Personal Coach  
→ Recommendations  
→ Dashboard

## Observation Abstraction

An observation is a raw or semi-structured fact extracted from source data before forcing it into a metric.

Examples:

- TSH 6.264 µIU/mL
- Sleep duration 7h 42m
- Completed Pull + Core
- Calf felt fine
- Started Whole Truth cold coffee protein experiment

Some observations become metrics. Some remain unconverted observations for later analysis.

## Metric Conversion

Within each taxonomy, observations are converted into normalized metrics where possible.

Examples:

- Thyroid Stimulating Hormone - Ultra Sensitive → TSH
- Glycosylated Hemoglobin (HbA1c) → HbA1c
- Cholesterol - LDL → LDL Cholesterol
- VO₂ Max → VO₂ Max
- Waist measurement → Waist

Data that cannot be converted should not be dropped. It should be preserved as an unconverted observation for future process improvement.

## Trends and Alerts

Metrics maintain trends over time.

Alerts are generated from:

- Out-of-range values
- Repeated deviations
- Meaningful trend changes
- Person-specific thresholds
- Goal-specific thresholds

Insights also maintain trends, and insight alerts may be generated where repeated patterns emerge.

## Personal Coach

Each person has a personal coach.

The coach is customized by person profile and person preferences. A default coach is generated from the person’s profile; customization is applied on top.

The coach consumes:

- Person profile
- Goals
- Constraints
- Medical context
- Supplement/medication context
- Metrics
- Metric trends
- Metric alerts
- Insights
- Insight trends
- Insight alerts
- Source evidence
- Person-specific benchmark rules

The coach then produces recommendations across taxonomies.

## Benchmarks

Benchmarks are person-specific and may include:

- Reference range
- Clinical target
- Personal baseline
- Goal benchmark

Examples:

- Lab TSH reference range
- Doctor-guided thyroid target
- Personal HRV baseline
- VO₂ max goal
- Waist reduction goal

## Dashboard

The dashboard shows metrics, trends, insights, alerts, and coach recommendations in context.

Recommendations should appear next to the relevant metric or insight, not only in a generic advice feed.

## Product Principles

1. Preserve raw data before interpreting it.
2. Do not drop unknown data; route it to Unidentified or Unconverted.
3. Every recommendation must be traceable to source evidence.
4. Trace must be navigable from the dashboard.
5. Benchmarks must be person-specific, not universal.
6. Alerts are delivered to the coach, not directly to the person.
7. Insights are not medical decisions; they are structured prompts for review/action.
8. Manual input should be minimal and used only when sources cannot provide the data.
9. The system should learn from failed classification and failed conversion.
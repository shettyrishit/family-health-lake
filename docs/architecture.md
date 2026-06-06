# Architecture

Family Health Lake is organized as a layered health data system.

The system preserves raw health data, extracts observations and metrics, computes trends and alerts, generates taxonomy-level insights, and exposes metrics, insights, and traceability through dashboards.

The first implementation goal is to complete all layers for `person_id = p001`.

---

## Core Principle

Raw health data should be preserved before interpretation.

The system should never silently drop unknown, unmapped, or unconverted data. If the system cannot classify or convert something, it should preserve enough context to improve the process later.

---

## Health Taxonomies

All input data is classified into one of the following health taxonomies:

1. **Training & Activity**
2. **Recovery & Sleep**
3. **Nutrition & Supplements**
4. **Body Composition**
5. **Medical & Lab Reports**
6. **Symptoms & Notes**

A system taxonomy called **Unidentified** is used when data cannot yet be classified.

`Unidentified` is not a normal health category. It is a process-improvement bucket.

---

## Layered Architecture

The system has six active data layers and one separate future coach layer.

```text
Source Data
→ Raw Data Preservation
→ Source Document Metadata
→ Observation Extraction
→ Normalization / Metric Conversion
→ Trends
→ Alerts
→ Taxonomy Insights
→ Dashboard
```

The **Personal Coach** is separate and holistic. It is not produced by a single taxonomy slice.

---

## Layer Responsibilities

### 1. Ingestion Layer

The ingestion layer brings source data into the system and registers it.

Sources may include:

* Tata 1mg or other lab reports
* Garmin Connect exports or integrations
* FITTR Hart / body composition data
* Medical prescriptions and imaging reports
* Recovery and symptom notes
* Supplement or medication routine changes
* Manual measurements such as waist

Responsibilities:

* Preserve raw files before interpretation
* Store raw files in Google Cloud Storage
* Register each source in `source_document`
* Capture source metadata such as person, source, document type, date, and file URI

The ingestion layer should not perform health interpretation.

---

### 2. Observation Layer

An observation is a raw or semi-structured fact extracted from source data before forcing it into a metric.

Examples:

```text
TSH 6.264 µIU/mL
Sleep duration 7h 42m
Completed Pull + Core
Calf felt fine
Started Whole Truth cold coffee protein experiment
```

Responsibilities:

* Extract facts from raw source data
* Preserve raw labels, raw values, and source location
* Preserve source context such as parsed text and surrounding text
* Mark whether the observation was converted, unconverted, or unidentified

Some observations become metrics. Some remain unconverted observations.

---

### 3. Normalization / Metric Layer

The normalization layer converts observations into standardized metrics where possible.

Examples:

```text
Thyroid Stimulating Hormone - Ultra Sensitive → TSH
Glycosylated Hemoglobin (HbA1c) → HbA1c
Cholesterol - LDL → LDL Cholesterol
VO₂ Max → VO₂ Max
Waist measurement → Waist
```

Responsibilities:

* Map source-specific labels to standard metric names
* Normalize units where needed
* Parse numeric values and comparator values
* Preserve reference ranges where available
* Assign basic status such as `normal`, `high`, `low`, or `tracked`
* Preserve trace from metric back to observation

The metric layer should remain mostly mechanical. It should not produce holistic recommendations.

---

### 4. Trend Layer

The trend layer computes changes over time from normalized metrics.

Examples:

```text
TSH remains above reference range across multiple tests.
VO₂ max has been flat for 8 weeks.
Waist is trending down over 4 weeks.
HRV has dipped compared with personal baseline.
```

Responsibilities:

* Track metric movement over time
* Compare against reference ranges, clinical targets, personal baselines, and goal benchmarks
* Produce metric-level trend records
* Preserve the metric IDs used to compute each trend

Trends must remain traceable to the underlying metrics.

---

### 5. Alert Layer

The alert layer identifies signals that need attention.

Alerts may be generated from:

* Out-of-range metrics
* Repeated deviations
* Meaningful trend changes
* Person-specific thresholds
* Goal-specific thresholds
* Missing scheduled checks

Examples:

```text
TSH is above reference range.
LDL is above desirable range.
VO₂ max has not improved over the review period.
Core training frequency dropped below target.
```

Responsibilities:

* Generate explicit attention signals
* Attach severity and reason
* Link alerts to related metrics and trends
* Avoid over-alerting on noise

Alerts are system signals. They are not coach recommendations.

---

### 6. Insight Layer

The insight layer produces taxonomy-level synthesis from metrics, trends, alerts, and context.

Examples:

```text
Medical & Lab Reports: Thyroid is monitored but not fully optimized because TSH remains above range while FT4 and FT3 are in range.

Training & Activity: Strength consistency is good, but Zone 2 exposure is low.

Recovery & Sleep: Sleep duration is adequate, but HRV dipped after an interval-heavy week.
```

Responsibilities:

* Synthesize related metrics, trends, and alerts within a taxonomy
* Produce a clear insight statement
* Preserve supporting evidence
* Link back to metrics, trends, alerts, observations, and source documents

Insights are not medical decisions. They are structured prompts for review and action.

---

### 7. Dashboard Layer

The dashboard displays metrics, trends, alerts, and insights in context.
Future scope: Coach recommendations shown next to the relevant metrics, insights, or trace paths

Dashboard cards should generally show:

```text
Taxonomy
→ Key metrics
→ Trends
→ Alerts
→ Insight
→ Source evidence
→ Trace
```

For example:

```text
Medical & Lab Reports → Thyroid

Metric:
TSH = 6.264 µIU/mL, High

Trend:
TSH remains above reference range.

Insight:
Thyroid is monitored / not fully optimized because TSH is high while FT4 and FT3 are in range.

Trace:
Insight → Alert → Trend → Metric → Observation → Source Document → Raw File
```

The dashboard must support navigable trace.

---

## Coach Layer Is Separate

The personal coach is intentionally decoupled from individual taxonomy slices.

A taxonomy slice should produce traceable insight packages. It should not directly produce coach recommendations.

The coach is a separate holistic layer that will later consume:

* Person profile
* Goals
* Constraints
* Medical context
* Supplement and medication context
* Metrics
* Metric trends
* Alerts
* Taxonomy insight packages
* Source evidence
* Person-specific benchmarks
* Preferences

The coach should not react to a single alert or one taxonomy slice in isolation.

For v1, the thyroid insight package may become the first input to the coach, but the thyroid slice itself should not directly generate coach recommendations.

Future coach-owned entities may include:

```text
coach_profile
coach_input_package
recommendation
```

These are not part of the current active intelligence slice.

---

## Raw Storage

Raw files are stored in **Google Cloud Storage** before interpretation.

Examples of raw files:

* Lab report PDFs
* Garmin exports
* FITTR Hart exports
* Prescriptions
* Imaging reports
* Recovery or symptom notes
* Manual measurement files, if any

Example raw path:

```text
gs://fhl-raw-bucket-1/raw/person_id=p001/labs/pdf/2026/04/25/report.pdf
```

Raw data should be preserved before extraction, normalization, synthesis, or coaching.

---

## Structured Storage

Structured entities are stored in **BigQuery**.

Current active entities:

| Entity            | Purpose                                                        |
| ----------------- | -------------------------------------------------------------- |
| `person`          | Identifies the person being tracked                            |
| `source_document` | Tracks raw files and source metadata                           |
| `observation`     | Stores raw or semi-structured facts extracted from source data |
| `health_metric`   | Stores normalized, queryable health metrics                    |
| `metric_trend`    | Stores trends computed from metrics                            |
| `alert`           | Stores alerts generated from metrics or trends                 |
| `insight`         | Stores taxonomy-level insights                                 |

Future coach-owned entities:

| Entity                | Purpose                                                             |
| --------------------- | ------------------------------------------------------------------- |
| `coach_profile`       | Stores person-specific coach configuration                          |
| `coach_input_package` | Stores grouped insight/alert/context packages for coach consumption |
| `recommendation`      | Stores holistic coach recommendations                               |

---

## High-Level Data Model

### `person`

Represents a person in the family health lake.

Examples:

```text
p001 = self
p002 = child
p003 = father
```

### `source_document`

Represents a raw source file or source dataset.

Examples:

* Tata 1mg PDF
* Garmin export
* FITTR export
* prescription
* imaging report
* symptom note

A source document points back to the raw file path in Cloud Storage.

### `observation`

Represents extracted source facts before metric normalization.

Key fields include:

```text
observation_id
person_id
document_id
taxonomy
observation_type
raw_label
raw_value
raw_text
surrounding_text
normalized_label
parsed_value
unit
source_location
conversion_status
failure_reason
```

### `health_metric`

Represents normalized, queryable health metrics.

Key fields include:

```text
metric_id
person_id
document_id
observation_id
metric_date
source
category
metric_name
value
text_value
unit
reference_low
reference_high
status
```

Each metric should link back to an observation through `observation_id`.

### `metric_trend`

Represents a computed trend over time.

Key fields may include:

```text
trend_id
person_id
taxonomy
category
metric_name
trend_type
trend_summary
trend_status
start_date
end_date
related_metric_ids
source_document_ids
```

### `alert`

Represents an attention signal generated from a metric or trend.

Key fields may include:

```text
alert_id
person_id
taxonomy
category
alert_type
severity
message
related_metric_ids
related_trend_ids
status
```

### `insight`

Represents taxonomy-level synthesis.

Key fields may include:

```text
insight_id
person_id
taxonomy
category
insight_type
summary
supporting_metric_ids
supporting_trend_ids
supporting_alert_ids
source_document_ids
```

---

## Traceability

Traceability is mandatory.

Every dashboard insight, alert, trend, and metric must be traceable back to the source observation and raw document/data.

Required trace path:

```text
Insight
→ Alert
→ Trend
→ Metric
→ Observation
→ Source Document
→ Raw File
```

When coach recommendations are added later, the trace path extends to:

```text
Recommendation
→ Coach Input Package
→ Insight
→ Alert
→ Trend
→ Metric
→ Observation
→ Source Document
→ Raw File
```

The dashboard must allow the user to inspect this trace.

---

## Current Environment

Environment-specific GCP configuration is stored in:

```text
config/environments/dev.yaml
```

The current v1 environment uses:

| Resource         | Value                            |
| ---------------- | -------------------------------- |
| Project ID       | `project-b01843b0-70b0-47d0-af0` |
| Raw bucket       | `fhl-raw-bucket-1`               |
| BigQuery dataset | `health_os`                      |
| Region           | `asia-south1`                    |

Raw files are stored in Cloud Storage. Structured entities are stored in BigQuery.

---

## Current Person Scope

The first person profile is:

| Field         | Value                                                           |
| ------------- | --------------------------------------------------------------- |
| Person ID     | `p001`                                                          |
| Relationship  | `self`                                                          |
| Initial focus | Fitness, thyroid, supplements, body composition, recovery, labs |

The system should support family expansion later, but the first implementation should complete all layers for `p001`.

---

## Vertical Slice Strategy

The system will be built as vertical slices rather than by completing every source integration first.

This means one source and one person should flow through every active layer end to end before expanding.

---

## Completed Foundation Slice

The first ingestion foundation slice is:

```text
Tata 1mg lab PDF
→ Source document registration
→ Observation extraction
→ Health metric creation
→ BigQuery load
→ Trace query
```

This has proven:

* Raw report can be preserved
* Source document can be registered
* Observations can be extracted
* Metrics can be normalized
* Metrics can be loaded into BigQuery
* Metrics can be traced back to observations and source documents

---

## Next Vertical Slice

The next slice is **Medical & Lab Reports Intelligence for `p001`**, starting with thyroid.

Flow:

```text
Thyroid metrics
→ Thyroid metric trend
→ Thyroid alert
→ Thyroid insight package
→ Dashboard trace
```

This slice should not generate coach recommendations.

The output should be a traceable thyroid insight package that can later become one input to the holistic coach.

---

## Later Vertical Slices

### Garmin Slice

```text
Garmin export / integration
→ Observations
→ Metrics: VO₂ max, HRV, resting HR, sleep, steps, workouts
→ Trends
→ Alerts
→ Training and recovery insights
→ Dashboard trace
```

### FITTR Body Composition Slice

```text
FITTR data
→ Observations
→ Metrics: weight, body fat, muscle mass, visceral fat
→ Trends
→ Alerts
→ Body composition insights
→ Dashboard trace
```

### Notes / Symptoms Slice

```text
Manual or semi-structured note
→ Observation
→ Optional metric
→ Symptom trend
→ Alert where needed
→ Insight
→ Dashboard trace
```

### Coach Slice

```text
Person profile
+ goals
+ constraints
+ medical context
+ supplement context
+ insight packages
+ alerts
+ trends
+ preferences
→ coach input package
→ holistic recommendation
→ recommendation trace
```

---

## Product Principles Reflected in Architecture

1. Preserve raw data before interpreting it.
2. Do not drop unknown data; route it to Unidentified or Unconverted.
3. Use observations before metrics.
4. Every metric must trace back to an observation where possible.
5. Every insight must trace back to source evidence.
6. Trace must be navigable from the dashboard.
7. Benchmarks must be person-specific, not universal.
8. Alerts are system signals, not coach recommendations.
9. Coach is separate and holistic.
10. Manual input should be minimal and used only when sources cannot provide the data.
11. The system should learn from failed classification and failed conversion.
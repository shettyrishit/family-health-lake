# Coding Agent Working Rules

These rules apply to any coding agent working in the `family-health-lake` repo, including Codex, Junie, or any future coding assistant.

## 1. Source of Truth

Before making changes, use the repo documentation and config as the source of truth:

* `docs/product_concept.md`
* `docs/architecture.md`
* `docs/data_model.md`
* `docs/traceability.md`
* `docs/roadmap.md`
* `config/taxonomies/health_taxonomies.yaml`
* `config/metric_mappings/`
* `schemas/csv/`
* `schemas/bigquery/`

Do not re-interpret the product concept unless explicitly asked.

## 2. Safety Rules

Never commit:

* Real health data
* Real medical PDFs
* Garmin or FITTR exports
* Real generated CSV outputs
* `.env` files
* Service account keys
* Credentials
* API tokens
* Secrets
* Raw data folders
* Download folders
* Reports folders

Raw health files belong in Google Cloud Storage, not Git.

Structured real metrics belong in BigQuery, not Git.

The repo should contain only:

* Code
* Docs
* Schemas
* Config
* Tests
* Fake fixtures
* Dummy sample data

## 3. Traceability Rule

Traceability is mandatory.

Every generated metric must trace back to an observation.

Every recommendation must ultimately trace back to source evidence.

Required trace path:

```text
Recommendation
→ Insight
→ Alert
→ Trend
→ Metric
→ Observation
→ Source Document
→ Raw File
```

For extractor work:

```text
health_metric.observation_id must point to observation.observation_id
```

Do not create metrics without trace unless explicitly marked and justified.

## 4. Observation-First Rule

Do not extract directly from raw source data into metrics only.

Use the flow:

```text
Source data
→ Observation
→ Metric
```

Some observations become metrics.

Some observations remain unconverted.

Unknown or failed cases must not be silently dropped.

## 5. Unconverted and Unidentified Data

If data looks health-relevant but cannot be converted into a metric, preserve it.

Use:

```text
conversion_status = unconverted
```

If data cannot be classified into a taxonomy, preserve it as:

```text
conversion_status = unidentified
taxonomy = unidentified
```

The system should learn from failed classification and failed conversion.

## 6. Keep Changes Small

Prefer small, reviewable changes.

Do not combine unrelated work.

Good task boundaries:

* Add schema files
* Add one extractor
* Add one mapping config
* Fix packaging
* Add tests
* Update README usage

Avoid large mixed changes that include docs, schema, parser logic, dashboard logic, and cloud automation in one step.

## 7. Python Packaging Rule

This repo contains top-level folders such as:

* `docs/`
* `config/`
* `schemas/`
* `samples/`
* `scripts/`

Do not let Python packaging accidentally treat these as packages.

Preferred structure for Python package code:

```text
src/family_health_lake/
```

CLI scripts may remain under:

```text
scripts/
```

If using `pyproject.toml`, package discovery must explicitly include only:

```text
family_health_lake
```

Do not rely on automatic flat-layout package discovery.

## 8. Testing Rules

Tests must use fake fixtures only.

Do not use real medical reports or real extracted health values in tests.

Test fixtures should be synthetic and safe to commit.

Tests should cover:

* ID generation
* Value parsing
* Comparator values such as `>1000` and `<1.0`
* Mapping from raw labels to normalized metric names
* Observation-to-metric trace
* Unconverted observation capture
* Extraction report counts

## 9. Extractor Rules

For extractors:

* Prefer text extraction over OCR.
* Do not use OCR in v1 unless explicitly asked.
* Keep extraction logic conservative.
* Do not silently drop relevant-looking data.
* Emit extraction reports with counts and warnings.
* Do not implement medical interpretation in extractors.
* Extractors should produce structured outputs only.

Extractor outputs should usually include:

```text
observations.csv
health_metric.csv
unconverted_observations.csv
extraction_report.json
```

Generated outputs should not be committed.

## 10. Dependency Rules

Keep dependencies minimal.

If dependencies are needed, add them to dependency management files.

Preferred for now:

```text
requirements.txt
```

or a properly configured:

```text
pyproject.toml
```

Do not add heavy frameworks unless required.

## 11. Cloud Rules

Do not implement cloud upload, BigQuery load, or scheduled jobs unless explicitly asked.

Local extractor work should remain:

```text
local input file → local CSV/JSON outputs
```

Cloud integration should be a separate task.

## 12. README Updates

When adding a usable script or workflow, update `README.md` with:

* Purpose
* Setup
* Command example
* Safety notes
* Expected outputs

Keep README concise and link to docs for deeper explanation.

## 13. Agent-Specific Usage

### Codex

Use Codex for bounded repo-level implementation tasks, such as:

* Creating extractors
* Adding tests
* Updating schemas
* Fixing packaging
* Implementing CLI workflows
* Updating README usage

Codex should produce reviewable diffs and should follow this file before making changes.

### Junie

Use Junie for IDE-local refinement tasks, such as:

* Refactoring code
* Debugging failing tests
* Improving naming
* Explaining implementation
* Cleaning module structure
* Making targeted edits inside PyCharm/IntelliJ

Junie should not broaden the scope beyond the requested local change.

## 14. Review Before Commit

Before committing, verify:

```bash
git status
```

There should be no:

```text
*.pdf
*.csv
*.xlsx
.env
credentials
service-account keys
raw/
data/
downloads/
exports/
reports/
medical_reports/
outputs/
```

Only commit safe code, docs, schemas, config, and fake fixtures.
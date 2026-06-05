# observation.csv Schema

This file defines the CSV contract for extracted observations before they are converted into normalized metrics.

## Columns

| Column | Meaning |
|---|---|
| observation_id | Deterministic unique ID for the observation |
| person_id | Person this observation belongs to, e.g. `p001` |
| document_id | Source document ID, if applicable |
| observed_at | Date of observation or sample collection |
| source | Source system, e.g. `tata_1mg`, `garmin`, `fittr` |
| taxonomy | Health taxonomy, e.g. `medical_lab_reports` |
| observation_type | Type of observation, e.g. `lab_result`, `sleep_summary`, `workout_summary` |
| raw_label | Original label from source |
| raw_value | Original raw value from source |
| normalized_label | Standardized label after mapping |
| parsed_value | Numeric value if parsed |
| unit | Unit of measure |
| source_location | Page, section, line, or source pointer where available |
| confidence | Extraction confidence from 0 to 1 |
| conversion_status | `converted`, `unconverted`, or `unidentified` |
| raw_text | Exact extracted line or block that triggered capture |
| surrounding_text | Small nearby context window, ideally previous/current/next lines |
| failure_reason | Why conversion/classification failed, e.g. `raw_label_not_mapped`, `value_parse_failed`, `reference_range_parse_failed`, `unable_to_classify` |
| notes | Additional context |

## Purpose

Observations preserve source meaning before metric normalization.

Every metric should trace back to an observation where possible.

# Garmin Cloud Fetch Proof v0

This document describes a feasibility spike for fetching Garmin Connect data into the Family Health Lake raw landing zone.

## Scope

This spike is intentionally limited to:

* authenticating to Garmin Connect with `python-garminconnect`
* fetching a small raw data set for a date range
* writing raw JSON files locally under `outputs/`
* optionally uploading those raw JSON files to the configured Google Cloud Storage raw bucket

This spike does **not**:

* parse raw Garmin data into observations
* write to BigQuery
* create `health_metric` rows
* create trends, alerts, insights, or dashboards
* upload workouts back into Garmin

Downstream observation extraction should be built only after this raw fetch proof is successful.

## CLI

Script:

```text
scripts/spikes/fetch_garmin_to_gcs.py
```

Python module:

```text
family_health_lake.spikes.garmin_cloud_fetch
```

## Setup

Install the Garmin spike dependencies:

```bash
python3 -m pip install -e ".[garmin]"
```

The current upstream `garminconnect` package release requires Python 3.12 or newer, so run this spike in a Python 3.12+ environment.

If you want GCS upload, authenticate with Application Default Credentials first:

```bash
gcloud auth application-default login
```

Garmin credentials must come from environment variables, not CLI literals:

```bash
export GARMIN_EMAIL="you@example.com"
export GARMIN_PASSWORD="your-password"
```

Do not commit Garmin credentials, token files, raw JSON outputs, or real health data.

## Command Examples

Local-only raw fetch:
 
 ```bash
 GARMIN_EMAIL="..." GARMIN_PASSWORD="..." python3 scripts/spikes/fetch_garmin_to_gcs.py \
   --environment-config config/environments/dev.yaml \
   --person-id p001 \
   --start-date 2026-06-10 \
   --end-date 2026-06-16 \
   --token-dir .local/garmin_tokens \
   --output-dir outputs/garmin_fetch
 ```
 
 Raw fetch plus GCS upload:
 
 ```bash
 GARMIN_EMAIL="..." GARMIN_PASSWORD="..." python3 scripts/spikes/fetch_garmin_to_gcs.py \
   --environment-config config/environments/dev.yaml \
   --person-id p001 \
   --start-date 2026-06-10 \
   --end-date 2026-06-16 \
   --token-dir .local/garmin_tokens \
   --output-dir outputs/garmin_fetch \
   --upload-to-gcs
 ```

## Expected Behavior

The CLI reads:

* `gcp.project_id` from the environment config
* `storage.raw_bucket` from the environment config
* Garmin email and password from the environment variable names passed via `--garmin-email-env` and `--garmin-password-env`

The CLI attempts to fetch these raw categories when the library methods are available:

* resting heart rate (`get_rhr_day`)
* heart rates (`get_heart_rates`)
* steps / daily activity summary (`get_user_summary`, `get_steps_data`)
* sleep (`get_sleep_data`)
* HRV (`get_hrv_data`)
* activities for the requested date range (`get_activities`)

If one category is unavailable or fails, the CLI logs a warning and continues with the other categories.

## Authentication and Tokens
 
 The CLI uses the `python-garminconnect` library's built-in session and token management.
-Tokens are stored locally in the directory specified by `--token-dir` (default: `~/.garminconnect`).
-The script attempts to reuse valid tokens from this directory first to avoid repeated logins and MFA prompts.
-If a fresh login is required and Garmin triggers MFA, the script will:
-1. Log that a fresh login is starting.
-2. Prompt the user to check their email/SMS for the Garmin MFA code.
-3. Accept the code from standard input.
-4. Save the new tokens for future use.
-
-**Note on MFA:** If you do not receive an email, it may be because Garmin's backend did not trigger it for the specific login strategy used by the library. The script logs when it is waiting for an MFA code to clarify the state.
+
+Tokens are stored locally in the directory specified by `--token-dir` (default: `~/.garminconnect`).
+The script attempts to reuse valid tokens from this directory first to avoid repeated logins and MFA prompts.
+
+If a fresh login is required and Garmin triggers MFA, the script will:
+
+1. Log that a fresh login is starting.
+2. Prompt the user to check their email/SMS for the Garmin MFA code.
+3. Accept the code from standard input.
+4. Save the new tokens for future use.
+
+**Note on MFA:** If you do not receive an email, it may be because Garmin's backend did not trigger it for the specific login strategy used by the library. The script logs when it is waiting for an MFA code to clarify the state.

## Output Layout

Local raw JSON path pattern:

```text
outputs/garmin_fetch/person_id={person_id}/provider=garmin/date_range={start_date}_{end_date}/{category}.json
```

GCS raw landing path pattern:

```text
raw/person_id={person_id}/wearables/provider=garmin/source=python_garminconnect/date_range={start_date}_{end_date}/{category}.json
```

Each JSON file contains:

* `person_id`
* `provider`
* `source`
* `category`
* `start_date`
* `end_date`
* `fetched_at`
* `raw_payload`

## Summary Output

At the end of the run, the CLI prints one summary line per category with:

* category
* success or failure
* local file path
* GCS URI if uploaded

## Safety Notes

* `outputs/` stays gitignored and should remain local-only
* do not commit Garmin raw JSON, CSVs, PDFs, token files, or credentials
* tests for this spike use fake Garmin and fake GCS clients only

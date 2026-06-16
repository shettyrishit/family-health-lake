from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional, Sequence

from family_health_lake.utils import load_yaml_config

try:
    from garminconnect import (
        Garmin,
        GarminConnectAuthenticationError,
        GarminConnectConnectionError,
        GarminConnectTooManyRequestsError,
    )
except ImportError:
    # We will handle the missing dependency in create_garmin_client
    Garmin = None  # type: ignore
    GarminConnectAuthenticationError = Exception  # type: ignore
    GarminConnectConnectionError = Exception  # type: ignore
    GarminConnectTooManyRequestsError = Exception  # type: ignore

PROVIDER = "garmin"
SOURCE = "python_garminconnect"

# Set up logging for the library if needed, but keep it quiet by default
logging.getLogger("garminconnect").setLevel(logging.ERROR)


@dataclass(frozen=True)
class GarminCloudFetchConfig:
    project_id: str
    raw_bucket: str
    raw_prefix: str


@dataclass(frozen=True)
class CategoryFetchResult:
    category: str
    success: bool
    local_file: Optional[str]
    gcs_uri: Optional[str]
    warning: Optional[str] = None


class CategoryUnavailableError(RuntimeError):
    """Raised when a Garmin category cannot be fetched."""


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Spike CLI that fetches raw Garmin Connect JSON locally and optionally "
            "uploads the raw files to Google Cloud Storage."
        )
    )
    parser.add_argument("--environment-config", required=True)
    parser.add_argument("--person-id", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--garmin-email-env", default="GARMIN_EMAIL")
    parser.add_argument("--garmin-password-env", default="GARMIN_PASSWORD")
    parser.add_argument(
        "--token-dir",
        default="~/.garminconnect",
        help="Path to directory for storing Garmin tokens.",
    )
    parser.add_argument("--output-dir", default="outputs/garmin_fetch")
    parser.add_argument("--upload-to-gcs", action="store_true")
    return parser


def load_garmin_environment_config(path: str | Path) -> GarminCloudFetchConfig:
    config = load_yaml_config(path)
    gcp = config.get("gcp") or {}
    storage = config.get("storage") or {}

    project_id = gcp.get("project_id")
    raw_bucket = storage.get("raw_bucket")
    raw_prefix = storage.get("raw_prefix") or "raw/"

    if not project_id:
        raise ValueError(f"Missing gcp.project_id in environment config: {path}")
    if not raw_bucket:
        raise ValueError(f"Missing storage.raw_bucket in environment config: {path}")

    return GarminCloudFetchConfig(
        project_id=str(project_id),
        raw_bucket=str(raw_bucket),
        raw_prefix=str(raw_prefix),
    )


def parse_iso_date(value: str, *, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be in YYYY-MM-DD format: {value}") from exc


def build_local_output_path(
    *,
    output_dir: str | Path,
    person_id: str,
    start_date: str,
    end_date: str,
    category: str,
) -> Path:
    return (
        Path(output_dir)
        / f"person_id={person_id}"
        / f"provider={PROVIDER}"
        / f"date_range={start_date}_{end_date}"
        / f"{category}.json"
    )


def build_gcs_blob_name(
    *,
    raw_prefix: str,
    person_id: str,
    start_date: str,
    end_date: str,
    category: str,
) -> str:
    normalized_prefix = raw_prefix.strip("/") or "raw"
    return (
        f"{normalized_prefix}/person_id={person_id}/wearables/provider={PROVIDER}/"
        f"source={SOURCE}/date_range={start_date}_{end_date}/{category}.json"
    )


def read_required_env_var(env_name: str) -> str:
    value = os.getenv(env_name)
    if value is None or value.strip() == "":
        raise ValueError(
            f"Environment variable '{env_name}' is required and must be non-empty."
        )
    return value


def create_garmin_client(
    email: str, password: str, token_dir: str | Path = "~/.garminconnect"
) -> Garmin:
    if Garmin is None:
        raise RuntimeError(
            "garminconnect is required for this spike. "
            'Install the optional Garmin dependencies with `python3 -m pip install -e ".[garmin]"`.'
        )

    token_dir_path = str(Path(token_dir).expanduser())
    os.makedirs(token_dir_path, exist_ok=True)

    # Try to restore saved tokens first (as per example.py)
    try:
        print(f"Attempting to login using tokens from: {token_dir_path}")
        client = Garmin()
        client.login(token_dir_path)
        print("Successfully logged in using stored tokens.")
        return client
    except GarminConnectTooManyRequestsError as err:
        raise RuntimeError(f"Garmin rate limit during token login: {err}") from err
    except (GarminConnectAuthenticationError, GarminConnectConnectionError):
        print("Stored tokens invalid or missing. Attempting fresh login...")
        pass

    try:
        def prompt_mfa() -> str:
            print("\nGarmin MFA Required. Please check your email/SMS.")
            code = input("Enter Garmin MFA code: ").strip()
            return code

        client = Garmin(
            email=email,
            password=password,
            prompt_mfa=prompt_mfa,
        )
        client.login(token_dir_path)
        print("Successfully logged in and saved new tokens.")
        return client
    except GarminConnectAuthenticationError as exc:
        raise RuntimeError(f"Garmin authentication failed: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"Failed to authenticate to Garmin Connect: {exc}") from exc


def create_storage_client(project_id: str) -> Any:
    try:
        from google.cloud import storage  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-storage is required for GCS upload. "
            'Install the optional Garmin dependencies with `python3 -m pip install -e ".[garmin]"`.'
        ) from exc

    try:
        return storage.Client(project=project_id)
    except Exception as exc:
        raise RuntimeError(
            "Failed to create a Google Cloud Storage client using Application Default Credentials. "
            "Run `gcloud auth application-default login` and retry."
        ) from exc


def _list_date_strings(start_date: date, end_date: date) -> List[str]:
    day_count = (end_date - start_date).days + 1
    return [
        (start_date + timedelta(days=offset)).isoformat()
        for offset in range(day_count)
    ]


def _require_garmin_method(client: Any, method_name: str) -> Any:
    method = getattr(client, method_name, None)
    if method is None or not callable(method):
        raise CategoryUnavailableError(
            f"Garmin client does not expose method '{method_name}'."
        )
    return method


def _fetch_single_method_by_date(
    client: Any,
    *,
    category: str,
    method_name: str,
    date_strings: Sequence[str],
) -> dict[str, Any]:
    method = _require_garmin_method(client, method_name)
    entries = []
    for day in date_strings:
        entries.append({"date": day, "payload": method(day)})
    return {"category": category, "entries": entries}


def fetch_resting_heart_rate(client: Garmin, date_strings: Sequence[str]) -> dict[str, Any]:
    return _fetch_single_method_by_date(
        client,
        category="resting_heart_rate",
        method_name="get_rhr_day",
        date_strings=date_strings,
    )


def fetch_heart_rates(client: Garmin, date_strings: Sequence[str]) -> dict[str, Any]:
    return _fetch_single_method_by_date(
        client,
        category="heart_rates",
        method_name="get_heart_rates",
        date_strings=date_strings,
    )


def fetch_sleep(client: Garmin, date_strings: Sequence[str]) -> dict[str, Any]:
    return _fetch_single_method_by_date(
        client,
        category="sleep",
        method_name="get_sleep_data",
        date_strings=date_strings,
    )


def fetch_daily_activity_summary(
    client: Any, date_strings: Sequence[str]
) -> tuple[dict[str, Any], Optional[str]]:
    summary_method = getattr(client, "get_user_summary", None)
    steps_method = getattr(client, "get_steps_data", None)
    if not callable(summary_method) and not callable(steps_method):
        raise CategoryUnavailableError(
            "Garmin client does not expose get_user_summary or get_steps_data."
        )

    entries = []
    warnings: List[str] = []
    for day in date_strings:
        day_entry: dict[str, Any] = {"date": day}

        if callable(summary_method):
            day_entry["user_summary"] = summary_method(day)
        else:
            warnings.append("get_user_summary unavailable; steps data only.")

        if callable(steps_method):
            day_entry["steps_data"] = steps_method(day)
        else:
            warnings.append("get_steps_data unavailable; summary only.")

        entries.append(day_entry)

    warning = None
    if warnings:
        warning = "; ".join(sorted(set(warnings)))
    return {"category": "daily_activity_summary", "entries": entries}, warning


def fetch_hrv(
    client: Garmin, *, start_date: str, end_date: str, date_strings: Sequence[str]
) -> dict[str, Any]:
    method = _require_garmin_method(client, "get_hrv_data")

    # In current library, get_hrv_data often takes a single date string.
    # demo.py uses: api.get_hrv_data(config.today.isoformat())
    entries = []
    for day in date_strings:
        try:
            payload = method(day)
            entries.append({"date": day, "payload": payload})
        except Exception as exc:
            entries.append({"date": day, "error": str(exc)})

    return {"category": "hrv", "entries": entries}


def _extract_activity_date(activity: dict[str, Any]) -> Optional[date]:
    activity_date = activity.get("activityDate")
    if isinstance(activity_date, str) and len(activity_date) >= 10:
        try:
            return date.fromisoformat(activity_date[:10])
        except ValueError:
            return None

    for field_name in ("startTimeLocal", "startTimeGMT"):
        timestamp = activity.get(field_name)
        if isinstance(timestamp, str) and len(timestamp) >= 10:
            try:
                return date.fromisoformat(timestamp[:10])
            except ValueError:
                continue
    return None


def fetch_activities(client: Any, *, start_date: date, end_date: date) -> dict[str, Any]:
    method = _require_garmin_method(client, "get_activities")

    limit = 100
    offset = 0
    matched: List[dict[str, Any]] = []

    while True:
        page = method(offset, limit)
        if not page:
            break
        if not isinstance(page, list):
            raise CategoryUnavailableError(
                "Garmin get_activities returned an unexpected payload type."
            )

        oldest_page_date: Optional[date] = None
        for activity in page:
            if not isinstance(activity, dict):
                continue
            activity_day = _extract_activity_date(activity)
            if activity_day is None:
                continue
            if oldest_page_date is None or activity_day < oldest_page_date:
                oldest_page_date = activity_day
            if start_date <= activity_day <= end_date:
                matched.append(activity)

        if len(page) < limit:
            break
        if oldest_page_date is not None and oldest_page_date < start_date:
            break
        offset += limit

    return {"category": "activities", "entries": matched}


def write_json_payload(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def upload_file_to_gcs(
    *,
    storage_client: Any,
    bucket_name: str,
    blob_name: str,
    file_path: Path,
) -> str:
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(str(file_path), content_type="application/json")
    return f"gs://{bucket_name}/{blob_name}"


def _build_metadata_payload(
    *,
    person_id: str,
    category: str,
    start_date: str,
    end_date: str,
    raw_payload: Any,
    fetched_at: str,
) -> dict[str, Any]:
    return {
        "person_id": person_id,
        "provider": PROVIDER,
        "source": SOURCE,
        "category": category,
        "start_date": start_date,
        "end_date": end_date,
        "fetched_at": fetched_at,
        "raw_payload": raw_payload,
    }


def fetch_garmin_to_gcs(
    *,
    environment_config_path: str | Path,
    person_id: str,
    start_date_str: str,
    end_date_str: str,
    garmin_email_env: str,
    garmin_password_env: str,
    token_dir: str | Path,
    output_dir: str | Path,
    upload_to_gcs: bool,
    garmin_client: Any = None,
    storage_client: Any = None,
    fetched_at: Optional[str] = None,
) -> List[CategoryFetchResult]:
    start_date = parse_iso_date(start_date_str, field_name="start_date")
    end_date = parse_iso_date(end_date_str, field_name="end_date")
    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date.")

    config = load_garmin_environment_config(environment_config_path)
    date_strings = _list_date_strings(start_date, end_date)
    fetched_at_value = fetched_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")

    email = read_required_env_var(garmin_email_env)
    password = read_required_env_var(garmin_password_env)

    garmin = garmin_client or create_garmin_client(email, password, token_dir)
    storage = None
    if upload_to_gcs:
        storage = storage_client or create_storage_client(config.project_id)

    results: List[CategoryFetchResult] = []
    fetchers = [
        (
            "resting_heart_rate",
            lambda: (fetch_resting_heart_rate(garmin, date_strings), None),
        ),
        (
            "heart_rates",
            lambda: (fetch_heart_rates(garmin, date_strings), None),
        ),
        (
            "daily_activity_summary",
            lambda: fetch_daily_activity_summary(garmin, date_strings),
        ),
        (
            "sleep",
            lambda: (fetch_sleep(garmin, date_strings), None),
        ),
        (
            "hrv",
            lambda: (
                fetch_hrv(
                    garmin,
                    start_date=start_date_str,
                    end_date=end_date_str,
                    date_strings=date_strings,
                ),
                None,
            ),
        ),
        (
            "activities",
            lambda: (fetch_activities(garmin, start_date=start_date, end_date=end_date), None),
        ),
    ]

    for category, fetcher in fetchers:
        try:
            raw_payload, warning = fetcher()
            local_path = build_local_output_path(
                output_dir=output_dir,
                person_id=person_id,
                start_date=start_date_str,
                end_date=end_date_str,
                category=category,
            )
            document = _build_metadata_payload(
                person_id=person_id,
                category=category,
                start_date=start_date_str,
                end_date=end_date_str,
                raw_payload=raw_payload,
                fetched_at=fetched_at_value,
            )
            write_json_payload(local_path, document)

            gcs_uri = None
            if upload_to_gcs and storage is not None:
                blob_name = build_gcs_blob_name(
                    raw_prefix=config.raw_prefix,
                    person_id=person_id,
                    start_date=start_date_str,
                    end_date=end_date_str,
                    category=category,
                )
                gcs_uri = upload_file_to_gcs(
                    storage_client=storage,
                    bucket_name=config.raw_bucket,
                    blob_name=blob_name,
                    file_path=local_path,
                )

            results.append(
                CategoryFetchResult(
                    category=category,
                    success=True,
                    local_file=str(local_path),
                    gcs_uri=gcs_uri,
                    warning=warning,
                )
            )
        except Exception as exc:
            warning = f"{category}: {exc}"
            print(f"Warning: {warning}")
            results.append(
                CategoryFetchResult(
                    category=category,
                    success=False,
                    local_file=None,
                    gcs_uri=None,
                    warning=warning,
                )
            )

    return results


def print_summary(results: Iterable[CategoryFetchResult]) -> None:
    print("Garmin fetch summary:")
    for result in results:
        status = "success" if result.success else "failure"
        local_file = result.local_file or "-"
        gcs_uri = result.gcs_uri or "-"
        print(
            f"category={result.category} status={status} "
            f"local_file={local_file} gcs_uri={gcs_uri}"
        )
        if result.warning and result.success:
            print(f"warning={result.warning}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)

    try:
        results = fetch_garmin_to_gcs(
            environment_config_path=args.environment_config,
            person_id=args.person_id,
            start_date_str=args.start_date,
            end_date_str=args.end_date,
            garmin_email_env=args.garmin_email_env,
            garmin_password_env=args.garmin_password_env,
            token_dir=args.token_dir,
            output_dir=args.output_dir,
            upload_to_gcs=args.upload_to_gcs,
        )
    except Exception as exc:
        print(f"Error: {exc}")
        return 1

    print_summary(results)
    return 0 if any(result.success for result in results) else 1

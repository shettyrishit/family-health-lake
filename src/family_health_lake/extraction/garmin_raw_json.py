from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from family_health_lake.extraction.tata_1mg_lab_report import (
    HEALTH_METRIC_FIELDS,
    OBSERVATION_FIELDS,
    write_csv,
)
from family_health_lake.utils import load_yaml_config, normalize_id_component


SUPPORTED_PROVIDER = "garmin"
SUPPORTED_RAW_SOURCE = "python_garminconnect"
EXTRACTED_SOURCE = "garmin_connect_raw_json"
REQUIRED_WRAPPER_FIELDS = {
    "person_id",
    "provider",
    "source",
    "category",
    "start_date",
    "end_date",
    "fetched_at",
    "raw_payload",
}


@dataclass(frozen=True)
class GarminMetricMapping:
    metric_key: str
    display_name: str
    unit: str
    taxonomy: str
    observation_type: str
    status: str
    category: str


@dataclass(frozen=True)
class GarminRawDocument:
    path: Path
    payload: Dict[str, Any]


@dataclass(frozen=True)
class MetricCandidate:
    metric_key: str
    observed_at: str
    value: float
    raw_label: str
    raw_value: str
    source_location: str
    raw_text: str
    notes: str
    activity_id: Optional[str] = None


@dataclass
class DiscoveryRecord:
    filename: str
    category: str
    provider: str
    source: str
    start_date: str
    end_date: str
    raw_payload_type: str
    raw_payload_top_level_keys: List[str]
    detected_record_count: Optional[int]
    extraction_status: str
    skip_reason: str


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extract Garmin raw JSON into observation.csv and health_metric.csv "
            "without writing directly to BigQuery."
        )
    )
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--person-id", required=True)
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--output-observations-csv", required=True)
    parser.add_argument("--output-health-metrics-csv", required=True)
    parser.add_argument("--write-discovery-report")
    return parser


def load_metric_mappings(path: str | Path) -> Dict[str, GarminMetricMapping]:
    config = load_yaml_config(path)
    metrics = config.get("metrics") or {}
    mappings: Dict[str, GarminMetricMapping] = {}

    for metric_key, metric_spec in metrics.items():
        taxonomy = str(metric_spec.get("taxonomy") or "")
        mappings[str(metric_key)] = GarminMetricMapping(
            metric_key=str(metric_key),
            display_name=str(metric_spec.get("display_name") or metric_key),
            unit=str(metric_spec.get("unit") or ""),
            taxonomy=taxonomy,
            observation_type=str(metric_spec.get("observation_type") or ""),
            status=str(metric_spec.get("status") or "tracked"),
            category=str(metric_spec.get("category") or taxonomy),
        )

    return mappings


def validate_garmin_wrapper(payload: Dict[str, Any], *, file_path: str | Path) -> None:
    missing_fields = sorted(REQUIRED_WRAPPER_FIELDS.difference(payload.keys()))
    if missing_fields:
        raise ValueError(
            f"Garmin raw JSON wrapper is missing required fields {missing_fields}: {file_path}"
        )

    provider = payload.get("provider")
    source = payload.get("source")
    if provider != SUPPORTED_PROVIDER:
        raise ValueError(
            f"Garmin raw JSON wrapper has unsupported provider '{provider}': {file_path}"
        )
    if source != SUPPORTED_RAW_SOURCE:
        raise ValueError(
            f"Garmin raw JSON wrapper has unsupported source '{source}': {file_path}"
        )


def load_raw_documents(input_dir: str | Path) -> List[GarminRawDocument]:
    base_path = Path(input_dir)
    if not base_path.exists():
        raise FileNotFoundError(f"Input directory not found: {base_path}")
    if not base_path.is_dir():
        raise ValueError(f"Input path must be a directory: {base_path}")

    documents: List[GarminRawDocument] = []
    for path in sorted(base_path.rglob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        documents.append(GarminRawDocument(path=path, payload=payload))
    return documents


def write_discovery_report(records: Sequence[Dict[str, Any]], output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(list(records), indent=2), encoding="utf-8")


def _warn(message: str, warnings: List[str]) -> None:
    warnings.append(message)
    print(f"Warning: {message}")


def _ensure_iso_date(value: str, *, context: str) -> str:
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError as exc:
        raise ValueError(f"Expected ISO date for {context}: {value}") from exc


def _to_float(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped == "":
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def _format_raw_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, sort_keys=True)


def _json_snippet(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _describe_document(document: GarminRawDocument) -> DiscoveryRecord:
    payload = document.payload
    raw_payload = payload.get("raw_payload")
    raw_payload_type = type(raw_payload).__name__
    raw_payload_top_level_keys: List[str] = []
    detected_record_count: Optional[int] = None

    if isinstance(raw_payload, dict):
        raw_payload_top_level_keys = sorted(raw_payload.keys())
        entries = raw_payload.get("entries")
        if isinstance(entries, list):
            detected_record_count = len(entries)
    elif isinstance(raw_payload, list):
        detected_record_count = len(raw_payload)

    return DiscoveryRecord(
        filename=document.path.name,
        category=str(payload.get("category") or ""),
        provider=str(payload.get("provider") or ""),
        source=str(payload.get("source") or ""),
        start_date=str(payload.get("start_date") or ""),
        end_date=str(payload.get("end_date") or ""),
        raw_payload_type=raw_payload_type,
        raw_payload_top_level_keys=raw_payload_top_level_keys,
        detected_record_count=detected_record_count,
        extraction_status="pending",
        skip_reason="",
    )


def _build_daily_ids(person_id: str, observed_at: str, metric_key: str) -> Tuple[str, str]:
    normalized_metric_key = normalize_id_component(metric_key)
    return (
        f"obs_{person_id}_{observed_at}_{normalized_metric_key}",
        f"m_{person_id}_{observed_at}_{normalized_metric_key}",
    )


def _build_activity_ids(
    person_id: str,
    observed_at: str,
    activity_id: str,
    metric_key: str,
) -> Tuple[str, str]:
    normalized_metric_key = normalize_id_component(metric_key)
    normalized_activity_id = normalize_id_component(activity_id)
    return (
        f"obs_{person_id}_{observed_at}_{normalized_activity_id}_{normalized_metric_key}",
        f"m_{person_id}_{observed_at}_{normalized_activity_id}_{normalized_metric_key}",
    )


def _build_observation_row(
    *,
    observation_id: str,
    person_id: str,
    document_id: str,
    observed_at: str,
    mapping: GarminMetricMapping,
    raw_label: str,
    raw_value: str,
    parsed_value: float,
    source_location: str,
    raw_text: str,
    notes: str,
) -> Dict[str, Any]:
    return {
        "observation_id": observation_id,
        "person_id": person_id,
        "document_id": document_id,
        "observed_at": observed_at,
        "source": EXTRACTED_SOURCE,
        "taxonomy": mapping.taxonomy,
        "observation_type": mapping.observation_type,
        "raw_label": raw_label,
        "raw_value": raw_value,
        "normalized_label": mapping.display_name,
        "parsed_value": parsed_value,
        "unit": mapping.unit,
        "source_location": source_location,
        "confidence": 0.95,
        "conversion_status": "converted",
        "raw_text": raw_text,
        "surrounding_text": "",
        "failure_reason": "",
        "notes": notes,
    }


def _build_health_metric_row(
    *,
    metric_id: str,
    observation_id: str,
    person_id: str,
    document_id: str,
    metric_date: str,
    mapping: GarminMetricMapping,
    value: float,
    notes: str,
) -> Dict[str, Any]:
    return {
        "metric_id": metric_id,
        "person_id": person_id,
        "document_id": document_id,
        "observation_id": observation_id,
        "metric_date": metric_date,
        "source": EXTRACTED_SOURCE,
        "category": mapping.category,
        "metric_name": mapping.display_name,
        "value": value,
        "text_value": "",
        "unit": mapping.unit,
        "reference_low": None,
        "reference_high": None,
        "status": mapping.status,
        "notes": notes,
    }


def _emit_candidate_rows(
    *,
    candidate: MetricCandidate,
    person_id: str,
    document_id: str,
    mapping: GarminMetricMapping,
    seen_observation_ids: set[str],
    seen_metric_ids: set[str],
    warnings: List[str],
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    if candidate.activity_id:
        observation_id, metric_id = _build_activity_ids(
            person_id,
            candidate.observed_at,
            candidate.activity_id,
            candidate.metric_key,
        )
    else:
        observation_id, metric_id = _build_daily_ids(
            person_id,
            candidate.observed_at,
            candidate.metric_key,
        )

    if observation_id in seen_observation_ids or metric_id in seen_metric_ids:
        _warn(
            f"Skipping duplicate Garmin metric id for {candidate.metric_key} at {candidate.source_location}.",
            warnings,
        )
        return None, None

    seen_observation_ids.add(observation_id)
    seen_metric_ids.add(metric_id)

    observation = _build_observation_row(
        observation_id=observation_id,
        person_id=person_id,
        document_id=document_id,
        observed_at=candidate.observed_at,
        mapping=mapping,
        raw_label=candidate.raw_label,
        raw_value=candidate.raw_value,
        parsed_value=candidate.value,
        source_location=candidate.source_location,
        raw_text=candidate.raw_text,
        notes=candidate.notes,
    )
    health_metric = _build_health_metric_row(
        metric_id=metric_id,
        observation_id=observation_id,
        person_id=person_id,
        document_id=document_id,
        metric_date=candidate.observed_at,
        mapping=mapping,
        value=candidate.value,
        notes=candidate.notes,
    )
    return observation, health_metric


def _extract_steps_from_entry(entry: Dict[str, Any]) -> Optional[Tuple[float, str, str]]:
    user_summary = entry.get("user_summary")
    if isinstance(user_summary, dict):
        for field_name in ("totalSteps", "steps"):
            steps = _to_float(user_summary.get(field_name))
            if steps is not None:
                return steps, _format_raw_value(user_summary.get(field_name)), f"user_summary.{field_name}"

    steps_data = entry.get("steps_data")
    if isinstance(steps_data, list):
        step_values = [
            _to_float(item.get("steps"))
            for item in steps_data
            if isinstance(item, dict) and _to_float(item.get("steps")) is not None
        ]
        if step_values:
            total_steps = sum(step_values)
            return total_steps, _json_snippet(steps_data), "steps_data[*].steps"

    return None


def _metric_map_value_candidates(
    payload: Dict[str, Any],
    metric_key: str,
) -> List[Tuple[Any, str]]:
    metrics_map = ((payload.get("allMetrics") or {}).get("metricsMap") or {})
    metric_value = metrics_map.get(metric_key)
    candidates: List[Tuple[Any, str]] = []

    if isinstance(metric_value, dict):
        candidates.append((metric_value.get("value"), f"allMetrics.metricsMap.{metric_key}.value"))
    elif isinstance(metric_value, list):
        for index, item in enumerate(metric_value):
            if isinstance(item, dict):
                candidates.append(
                    (item.get("value"), f"allMetrics.metricsMap.{metric_key}[{index}].value")
                )
            else:
                candidates.append((item, f"allMetrics.metricsMap.{metric_key}[{index}]"))

    return candidates


def parse_daily_activity_summary(
    document: GarminRawDocument,
    warnings: List[str],
) -> List[MetricCandidate]:
    raw_payload = document.payload.get("raw_payload") or {}
    entries = raw_payload.get("entries")
    if not isinstance(entries, list):
        _warn(f"Skipping {document.path.name}: daily activity summary has no entries list.", warnings)
        return []

    candidates: List[MetricCandidate] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        entry_date = _ensure_iso_date(str(entry.get("date") or ""), context=f"{document.path.name} entry date")
        steps_result = _extract_steps_from_entry(entry)
        if steps_result is None:
            continue
        value, raw_value, json_path = steps_result
        candidates.append(
            MetricCandidate(
                metric_key="steps",
                observed_at=entry_date,
                value=value,
                raw_label="steps",
                raw_value=raw_value,
                source_location=f"file={document.path.name};json_path=raw_payload.entries[{index}].{json_path}",
                raw_text=_json_snippet(entry),
                notes="garmin_category=daily_activity_summary",
            )
        )
    return candidates


def parse_steps(
    document: GarminRawDocument,
    warnings: List[str],
) -> List[MetricCandidate]:
    return parse_daily_activity_summary(document, warnings)


def parse_resting_heart_rate(
    document: GarminRawDocument,
    warnings: List[str],
) -> List[MetricCandidate]:
    raw_payload = document.payload.get("raw_payload") or {}
    entries = raw_payload.get("entries")
    if not isinstance(entries, list):
        _warn(f"Skipping {document.path.name}: resting heart rate has no entries list.", warnings)
        return []

    candidates: List[MetricCandidate] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        entry_date = _ensure_iso_date(str(entry.get("date") or ""), context=f"{document.path.name} entry date")
        payload = entry.get("payload")
        value = None
        json_path = ""
        if isinstance(payload, dict):
            candidate_specs = [
                (payload.get("restingHeartRate"), "payload.restingHeartRate"),
                (payload.get("value"), "payload.value"),
            ]
            candidate_specs.extend(
                (
                    candidate_value,
                    f"payload.{candidate_path}",
                )
                for candidate_value, candidate_path in _metric_map_value_candidates(
                    payload, "WELLNESS_RESTING_HEART_RATE"
                )
            )
            for candidate_value, candidate_path in candidate_specs:
                numeric_value = _to_float(candidate_value)
                if numeric_value is not None:
                    value = numeric_value
                    json_path = candidate_path
                    raw_value = _format_raw_value(candidate_value)
                    break
            else:
                raw_value = _json_snippet(payload)
        else:
            numeric_value = _to_float(payload)
            value = numeric_value
            json_path = "payload"
            raw_value = _format_raw_value(payload)

        if value is None:
            continue

        candidates.append(
            MetricCandidate(
                metric_key="resting_hr",
                observed_at=entry_date,
                value=value,
                raw_label="resting_heart_rate",
                raw_value=raw_value,
                source_location=f"file={document.path.name};json_path=raw_payload.entries[{index}].{json_path}",
                raw_text=_json_snippet(entry),
                notes="garmin_category=resting_heart_rate",
            )
        )
    return candidates


def _extract_sleep_minutes(payload: Dict[str, Any]) -> Optional[Tuple[float, str, str]]:
    second_specs = [
        (payload.get("sleepTimeSeconds"), "sleepTimeSeconds"),
        (((payload.get("dailySleepDTO") or {}).get("sleepTimeSeconds")), "dailySleepDTO.sleepTimeSeconds"),
    ]
    for raw_value, json_path in second_specs:
        seconds = _to_float(raw_value)
        if seconds is not None:
            return seconds / 60.0, _format_raw_value(raw_value), json_path

    minute_specs = [
        (payload.get("sleepTimeMinutes"), "sleepTimeMinutes"),
        (((payload.get("dailySleepDTO") or {}).get("sleepTimeMinutes")), "dailySleepDTO.sleepTimeMinutes"),
    ]
    for raw_value, json_path in minute_specs:
        minutes = _to_float(raw_value)
        if minutes is not None:
            return minutes, _format_raw_value(raw_value), json_path

    return None


def parse_sleep(
    document: GarminRawDocument,
    warnings: List[str],
) -> List[MetricCandidate]:
    raw_payload = document.payload.get("raw_payload") or {}
    entries = raw_payload.get("entries")
    if not isinstance(entries, list):
        _warn(f"Skipping {document.path.name}: sleep has no entries list.", warnings)
        return []

    candidates: List[MetricCandidate] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        entry_date = _ensure_iso_date(str(entry.get("date") or ""), context=f"{document.path.name} entry date")
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue
        sleep_result = _extract_sleep_minutes(payload)
        if sleep_result is None:
            continue
        value, raw_value, json_path = sleep_result
        candidates.append(
            MetricCandidate(
                metric_key="sleep_minutes",
                observed_at=entry_date,
                value=value,
                raw_label="sleep",
                raw_value=raw_value,
                source_location=f"file={document.path.name};json_path=raw_payload.entries[{index}].payload.{json_path}",
                raw_text=_json_snippet(entry),
                notes="garmin_category=sleep;derived_from_source_seconds_or_minutes=true",
            )
        )
    return candidates


def _extract_hrv_average(payload: Dict[str, Any]) -> Optional[Tuple[float, str, str]]:
    candidate_specs = [
        (payload.get("lastNightAvg"), "lastNightAvg"),
        (((payload.get("hrvSummary") or {}).get("lastNightAvg")), "hrvSummary.lastNightAvg"),
        (payload.get("weeklyAverage"), "weeklyAverage"),
        (((payload.get("hrvSummary") or {}).get("weeklyAverage")), "hrvSummary.weeklyAverage"),
        (((payload.get("hrvSummary") or {}).get("avg")), "hrvSummary.avg"),
        (payload.get("average"), "average"),
    ]
    for raw_value, json_path in candidate_specs:
        average = _to_float(raw_value)
        if average is not None:
            return average, _format_raw_value(raw_value), json_path
    return None


def parse_hrv(
    document: GarminRawDocument,
    warnings: List[str],
) -> List[MetricCandidate]:
    raw_payload = document.payload.get("raw_payload") or {}
    entries = raw_payload.get("entries")
    if not isinstance(entries, list):
        _warn(f"Skipping {document.path.name}: hrv has no entries list.", warnings)
        return []

    candidates: List[MetricCandidate] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        if entry.get("error"):
            _warn(
                f"Skipping {document.path.name} entry {index}: Garmin HRV payload contains error '{entry.get('error')}'.",
                warnings,
            )
            continue
        entry_date = _ensure_iso_date(str(entry.get("date") or ""), context=f"{document.path.name} entry date")
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue
        hrv_result = _extract_hrv_average(payload)
        if hrv_result is None:
            continue
        value, raw_value, json_path = hrv_result
        candidates.append(
            MetricCandidate(
                metric_key="hrv_avg",
                observed_at=entry_date,
                value=value,
                raw_label="hrv_average",
                raw_value=raw_value,
                source_location=f"file={document.path.name};json_path=raw_payload.entries[{index}].payload.{json_path}",
                raw_text=_json_snippet(entry),
                notes="garmin_category=hrv",
            )
        )
    return candidates


def _extract_heart_rate_average(payload: Dict[str, Any]) -> Optional[Tuple[float, str, str]]:
    descriptors = payload.get("heartRateValueDescriptors")
    values = payload.get("heartRateValues")
    if not isinstance(descriptors, list) or not isinstance(values, list):
        return None

    heartrate_index = None
    for descriptor in descriptors:
        if not isinstance(descriptor, dict):
            continue
        if str(descriptor.get("key") or "").casefold() == "heartrate":
            descriptor_index = descriptor.get("index")
            if isinstance(descriptor_index, int):
                heartrate_index = descriptor_index
                break

    if heartrate_index is None:
        return None

    samples: List[float] = []
    for item in values:
        if not isinstance(item, list) or heartrate_index >= len(item):
            continue
        sample = _to_float(item[heartrate_index])
        if sample is None or sample <= 0:
            continue
        samples.append(sample)

    if not samples:
        return None

    return sum(samples) / len(samples), _json_snippet(values[:5]), "heartRateValues[*][heartrate]"


def parse_heart_rates(
    document: GarminRawDocument,
    warnings: List[str],
) -> List[MetricCandidate]:
    raw_payload = document.payload.get("raw_payload") or {}
    entries = raw_payload.get("entries")
    if not isinstance(entries, list):
        _warn(f"Skipping {document.path.name}: heart rates has no entries list.", warnings)
        return []

    candidates: List[MetricCandidate] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue
        entry_date = _ensure_iso_date(
            str(payload.get("calendarDate") or entry.get("date") or ""),
            context=f"{document.path.name} entry date",
        )
        activity_note = "garmin_category=heart_rates"

        metric_specs = [
            ("min_hr", "min_heart_rate", payload.get("minHeartRate"), "minHeartRate"),
            ("max_hr", "max_heart_rate", payload.get("maxHeartRate"), "maxHeartRate"),
        ]
        for metric_key, raw_label, raw_value_obj, json_path in metric_specs:
            metric_value = _to_float(raw_value_obj)
            if metric_value is None:
                continue
            candidates.append(
                MetricCandidate(
                    metric_key=metric_key,
                    observed_at=entry_date,
                    value=metric_value,
                    raw_label=raw_label,
                    raw_value=_format_raw_value(raw_value_obj),
                    source_location=f"file={document.path.name};json_path=raw_payload.entries[{index}].payload.{json_path}",
                    raw_text=_json_snippet(entry),
                    notes=activity_note,
                )
            )

        average_result = _extract_heart_rate_average(payload)
        if average_result is not None:
            value, raw_value, json_path = average_result
            candidates.append(
                MetricCandidate(
                    metric_key="avg_hr",
                    observed_at=entry_date,
                    value=value,
                    raw_label="average_heart_rate",
                    raw_value=raw_value,
                    source_location=f"file={document.path.name};json_path=raw_payload.entries[{index}].payload.{json_path}",
                    raw_text=_json_snippet(entry),
                    notes=f"{activity_note};derived_from_intraday_samples=true",
                )
            )

    return candidates


def _default_skip_reason_for_category(category: str) -> str:
    reasons = {
        "activities": "no_supported_activity_fields_found",
        "daily_activity_summary": "no_steps_values_found",
        "daily_summary": "no_steps_values_found",
        "steps": "no_steps_values_found",
        "resting_heart_rate": "no_resting_heart_rate_values_found",
        "sleep": "no_sleep_duration_fields_found",
        "hrv": "no_daily_hrv_values_found",
        "heart_rates": "no_supported_daily_heart_rate_aggregates_found",
    }
    return reasons.get(category, "no_supported_values_found")


def _extract_activity_date(activity: Dict[str, Any]) -> Optional[str]:
    for field_name in ("activityDate", "startTimeLocal", "startTimeGMT"):
        value = activity.get(field_name)
        if not isinstance(value, str):
            continue
        try:
            return date.fromisoformat(value[:10]).isoformat()
        except ValueError:
            continue
    return None


def parse_activities(
    document: GarminRawDocument,
    warnings: List[str],
) -> List[MetricCandidate]:
    raw_payload = document.payload.get("raw_payload") or {}
    entries = raw_payload.get("entries")
    if not isinstance(entries, list):
        _warn(f"Skipping {document.path.name}: activities has no entries list.", warnings)
        return []

    candidates: List[MetricCandidate] = []
    for index, activity in enumerate(entries):
        if not isinstance(activity, dict):
            continue
        activity_date = _extract_activity_date(activity)
        if activity_date is None:
            _warn(
                f"Skipping activity at {document.path.name} entry {index}: missing activity date.",
                warnings,
            )
            continue
        activity_id = activity.get("activityId")
        if activity_id in (None, ""):
            _warn(
                f"Skipping activity at {document.path.name} entry {index}: missing activityId.",
                warnings,
            )
            continue
        activity_id_text = str(activity_id)
        activity_name = str(activity.get("activityName") or "activity")

        duration = _to_float(activity.get("duration"))
        if duration is None:
            duration = _to_float(activity.get("movingDuration"))
            duration_path = "movingDuration"
        else:
            duration_path = "duration"
        if duration is not None:
            candidates.append(
                MetricCandidate(
                    metric_key="activity_duration_minutes",
                    observed_at=activity_date,
                    activity_id=activity_id_text,
                    value=duration / 60.0,
                    raw_label="activity_duration",
                    raw_value=_format_raw_value(activity.get(duration_path)),
                    source_location=f"file={document.path.name};json_path=raw_payload.entries[{index}].{duration_path}",
                    raw_text=_json_snippet(activity),
                    notes=f"garmin_category=activities;activity_name={activity_name};derived_from_seconds=true",
                )
            )

        distance = _to_float(activity.get("distance"))
        if distance is None:
            distance = _to_float(activity.get("distanceInMeters"))
            distance_path = "distanceInMeters"
        else:
            distance_path = "distance"
        if distance is not None:
            candidates.append(
                MetricCandidate(
                    metric_key="activity_distance_km",
                    observed_at=activity_date,
                    activity_id=activity_id_text,
                    value=distance / 1000.0,
                    raw_label="activity_distance",
                    raw_value=_format_raw_value(activity.get(distance_path)),
                    source_location=f"file={document.path.name};json_path=raw_payload.entries[{index}].{distance_path}",
                    raw_text=_json_snippet(activity),
                    notes=f"garmin_category=activities;activity_name={activity_name};derived_from_meters=true",
                )
            )

    return candidates


def extract_garmin_raw_json(
    *,
    input_dir: str | Path,
    person_id: str,
    document_id: str,
    mapping_path: str | Path,
    discovery_report_path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    mappings = load_metric_mappings(mapping_path)
    documents = load_raw_documents(input_dir)

    parser_by_category = {
        "daily_activity_summary": parse_daily_activity_summary,
        "daily_summary": parse_daily_activity_summary,
        "steps": parse_steps,
        "resting_heart_rate": parse_resting_heart_rate,
        "sleep": parse_sleep,
        "hrv": parse_hrv,
        "heart_rates": parse_heart_rates,
        "activities": parse_activities,
    }

    observations: List[Dict[str, Any]] = []
    health_metrics: List[Dict[str, Any]] = []
    warnings: List[str] = []
    seen_observation_ids: set[str] = set()
    seen_metric_ids: set[str] = set()
    discovery_records: List[DiscoveryRecord] = []

    for document in documents:
        discovery = _describe_document(document)
        try:
            validate_garmin_wrapper(document.payload, file_path=document.path)
        except ValueError as exc:
            _warn(str(exc), warnings)
            discovery.extraction_status = "skipped"
            discovery.skip_reason = str(exc)
            discovery_records.append(discovery)
            continue

        document_person_id = str(document.payload.get("person_id") or "")
        if document_person_id != person_id:
            reason = (
                f"wrapper person_id '{document_person_id}' does not match CLI person_id '{person_id}'"
            )
            _warn(f"Skipping {document.path.name}: {reason}.", warnings)
            discovery.extraction_status = "skipped"
            discovery.skip_reason = reason
            discovery_records.append(discovery)
            continue

        category = str(document.payload.get("category") or "")
        parser = parser_by_category.get(category)
        if parser is None:
            reason = f"unsupported_category:{category}"
            _warn(f"Skipping unsupported Garmin category '{category}' in {document.path.name}.", warnings)
            discovery.extraction_status = "skipped"
            discovery.skip_reason = reason
            discovery_records.append(discovery)
            continue

        try:
            candidates = parser(document, warnings)
        except Exception as exc:
            reason = f"parser_error:{exc}"
            _warn(f"Skipping Garmin category '{category}' in {document.path.name}: {exc}", warnings)
            discovery.extraction_status = "skipped"
            discovery.skip_reason = reason
            discovery_records.append(discovery)
            continue

        extracted_count = 0

        for candidate in candidates:
            mapping = mappings.get(candidate.metric_key)
            if mapping is None:
                _warn(
                    f"Missing Garmin metric mapping for '{candidate.metric_key}' in {document.path.name}.",
                    warnings,
                )
                continue

            observation, health_metric = _emit_candidate_rows(
                candidate=candidate,
                person_id=person_id,
                document_id=document_id,
                mapping=mapping,
                seen_observation_ids=seen_observation_ids,
                seen_metric_ids=seen_metric_ids,
                warnings=warnings,
            )
            if observation and health_metric:
                observations.append(observation)
                health_metrics.append(health_metric)
                extracted_count += 1

        if extracted_count > 0:
            discovery.extraction_status = "converted"
            discovery.skip_reason = ""
        else:
            discovery.extraction_status = "skipped"
            discovery.skip_reason = _default_skip_reason_for_category(category)
        discovery_records.append(discovery)

    observations.sort(key=lambda row: row["observation_id"])
    health_metrics.sort(key=lambda row: row["metric_id"])
    discovery_report = [record.__dict__ for record in discovery_records]
    if discovery_report_path:
        write_discovery_report(discovery_report, discovery_report_path)
    return {
        "observations": observations,
        "health_metrics": health_metrics,
        "warnings": warnings,
        "discovery_report": discovery_report,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[3]
    mapping_path = repo_root / "config/metric_mappings/garmin_raw_json_metrics.yaml"
    extraction = extract_garmin_raw_json(
        input_dir=args.input_dir,
        person_id=args.person_id,
        document_id=args.document_id,
        mapping_path=mapping_path,
        discovery_report_path=args.write_discovery_report,
    )

    write_csv(extraction["observations"], OBSERVATION_FIELDS, args.output_observations_csv)
    write_csv(
        extraction["health_metrics"],
        HEALTH_METRIC_FIELDS,
        args.output_health_metrics_csv,
    )
    print(
        f"Garmin extraction complete: observations={len(extraction['observations'])} "
        f"health_metrics={len(extraction['health_metrics'])} warnings={len(extraction['warnings'])}"
    )
    return 0

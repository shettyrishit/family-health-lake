from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from family_health_lake.extraction.tata_1mg_lab_report import (
    HEALTH_METRIC_FIELDS,
    OBSERVATION_FIELDS,
    write_csv,
)
from family_health_lake.ingestion.bigquery_csv_loader import (
    create_bigquery_client,
    insert_rows,
    load_environment_config,
)
from family_health_lake.utils import get_row_value, load_yaml_config, normalize_id_component


RAW_GARMIN_SOURCE = "garmin_connect_raw_json"
WEEKLY_ROLLUP_SOURCE = "garmin_weekly_rollup"
GARMIN_VIEW_NAME = "v_garmin_daily_metrics"
ACTIVITY_OBSERVATION_ID_RE = re.compile(
    r"^obs_(?P<person_id>.+?)_(?P<activity_date>\d{4}-\d{2}-\d{2})_(?P<activity_id>.+)_(?P<metric_key>activity_duration_minutes|activity_distance_km)$"
)


@dataclass(frozen=True)
class GarminWeeklyMetricMapping:
    metric_key: str
    display_name: str
    unit: str
    taxonomy: str
    aggregation: str
    source_metric_names: List[str]
    category: str


@dataclass(frozen=True)
class GarminSourceMetricRecord:
    metric_id: str
    observation_id: str
    person_id: str
    document_id: str
    metric_date: str
    source: str
    category: str
    metric_name: str
    value: float
    unit: str
    observation_type: str
    source_location: str
    notes: str
    raw_text: str


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate weekly Garmin rollup observations and health metrics from "
            "BigQuery daily/activity Garmin facts."
        )
    )
    parser.add_argument("--environment-config", required=True)
    parser.add_argument("--person-id", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--output-observations-csv", required=True)
    parser.add_argument("--output-health-metrics-csv", required=True)
    parser.add_argument("--load-to-bigquery", action="store_true")
    parser.add_argument("--replace-existing", action="store_true")
    return parser


def parse_iso_date(value: str, *, field_name: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format: {value}") from exc


def week_start_monday(metric_date: str) -> str:
    parsed = date.fromisoformat(metric_date)
    return (parsed - timedelta(days=parsed.weekday())).isoformat()


def load_weekly_metric_mappings(path: str | Path) -> Dict[str, GarminWeeklyMetricMapping]:
    config = load_yaml_config(path)
    metrics = config.get("metrics") or {}
    mappings: Dict[str, GarminWeeklyMetricMapping] = {}
    for metric_key, metric_spec in metrics.items():
        taxonomy = str(metric_spec.get("taxonomy") or "")
        raw_source_metric_names = metric_spec.get("source_metric_names") or []
        if isinstance(raw_source_metric_names, str):
            source_metric_names = [
                item.strip()
                for item in raw_source_metric_names.split("|")
                if item.strip()
            ]
        else:
            source_metric_names = [
                str(item)
                for item in raw_source_metric_names
                if str(item).strip()
            ]
        mappings[str(metric_key)] = GarminWeeklyMetricMapping(
            metric_key=str(metric_key),
            display_name=str(metric_spec.get("display_name") or metric_key),
            unit=str(metric_spec.get("unit") or ""),
            taxonomy=taxonomy,
            aggregation=str(metric_spec.get("aggregation") or ""),
            source_metric_names=source_metric_names,
            category=str(metric_spec.get("category") or taxonomy),
        )
    return mappings


def _default_view_exists_job_config_factory(table_name: str) -> Any:
    try:
        from google.cloud import bigquery  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-bigquery is required for Garmin weekly rollup. "
            "Install the bigquery extra before running this CLI."
        ) from exc

    return bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("table_name", "STRING", table_name),
        ]
    )


def _default_metrics_query_job_config_factory(
    person_id: str,
    start_date: str,
    end_date: str,
    source: str,
) -> Any:
    try:
        from google.cloud import bigquery  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-bigquery is required for Garmin weekly rollup. "
            "Install the bigquery extra before running this CLI."
        ) from exc

    return bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("person_id", "STRING", person_id),
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
            bigquery.ScalarQueryParameter("source", "STRING", source),
        ]
    )


def _default_delete_query_job_config_factory(
    person_id: str,
    week_start_dates: Sequence[str],
    source: str,
) -> Any:
    try:
        from google.cloud import bigquery  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-bigquery is required for Garmin weekly rollup. "
            "Install the bigquery extra before running this CLI."
        ) from exc

    return bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("person_id", "STRING", person_id),
            bigquery.ArrayQueryParameter("week_start_dates", "DATE", list(week_start_dates)),
            bigquery.ScalarQueryParameter("source", "STRING", source),
        ]
    )


def garmin_daily_view_exists(
    client: Any,
    *,
    project_id: str,
    dataset: str,
    table_name: str = GARMIN_VIEW_NAME,
    query_job_config_factory: Optional[Callable[[str], Any]] = None,
) -> bool:
    query = (
        f"SELECT COUNT(*) AS cnt "
        f"FROM `{project_id}.{dataset}.INFORMATION_SCHEMA.TABLES` "
        "WHERE table_name = @table_name AND table_type = 'VIEW'"
    )
    config_factory = query_job_config_factory or _default_view_exists_job_config_factory
    rows = list(client.query(query, job_config=config_factory(table_name)).result())
    count = int(get_row_value(rows[0], "cnt") or 0) if rows else 0
    return count > 0


def _coerce_source_metric_row(row: Any) -> Optional[GarminSourceMetricRecord]:
    value = get_row_value(row, "value")
    if value is None:
        return None
    return GarminSourceMetricRecord(
        metric_id=str(get_row_value(row, "metric_id")),
        observation_id=str(get_row_value(row, "observation_id")),
        person_id=str(get_row_value(row, "person_id")),
        document_id=str(get_row_value(row, "document_id") or ""),
        metric_date=str(get_row_value(row, "metric_date")),
        source=str(get_row_value(row, "source") or ""),
        category=str(get_row_value(row, "category") or ""),
        metric_name=str(get_row_value(row, "metric_name")),
        value=float(value),
        unit=str(get_row_value(row, "unit") or ""),
        observation_type=str(get_row_value(row, "observation_type") or ""),
        source_location=str(get_row_value(row, "source_location") or ""),
        notes=str(get_row_value(row, "notes") or ""),
        raw_text=str(get_row_value(row, "raw_text") or ""),
    )


def fetch_garmin_source_metrics(
    client: Any,
    *,
    project_id: str,
    dataset: str,
    person_id: str,
    start_date: str,
    end_date: str,
    view_exists_query_job_config_factory: Optional[Callable[[str], Any]] = None,
    metrics_query_job_config_factory: Optional[
        Callable[[str, str, str, str], Any]
    ] = None,
) -> List[GarminSourceMetricRecord]:
    config_factory = metrics_query_job_config_factory or _default_metrics_query_job_config_factory
    if garmin_daily_view_exists(
        client,
        project_id=project_id,
        dataset=dataset,
        query_job_config_factory=view_exists_query_job_config_factory,
    ):
        query = (
            f"SELECT * FROM `{project_id}.{dataset}.{GARMIN_VIEW_NAME}` "
            "WHERE person_id = @person_id "
            "AND metric_date BETWEEN @start_date AND @end_date "
            "AND source = @source "
            "ORDER BY metric_date ASC, metric_id ASC"
        )
    else:
        query = (
            f"SELECT hm.metric_id, hm.person_id, hm.document_id, hm.observation_id, hm.metric_date, "
            f"hm.source, hm.category, hm.metric_name, hm.value, hm.unit, "
            f"o.observation_type, o.source_location, o.notes, o.raw_text "
            f"FROM `{project_id}.{dataset}.health_metric` hm "
            f"LEFT JOIN `{project_id}.{dataset}.observation` o "
            "ON hm.observation_id = o.observation_id AND hm.person_id = o.person_id "
            "WHERE hm.person_id = @person_id "
            "AND hm.metric_date BETWEEN @start_date AND @end_date "
            "AND hm.source = @source "
            "ORDER BY hm.metric_date ASC, hm.metric_id ASC"
        )

    rows = client.query(
        query,
        job_config=config_factory(person_id, start_date, end_date, RAW_GARMIN_SOURCE),
    ).result()
    return [
        record
        for row in rows
        if (record := _coerce_source_metric_row(row)) is not None
    ]


def _extract_activity_identity(observation_id: str) -> Optional[str]:
    match = ACTIVITY_OBSERVATION_ID_RE.match(observation_id)
    if match is None:
        return None
    return str(match.group("activity_id"))


def _compact_json(value: Dict[str, Any]) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _format_numeric_raw_value(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return str(value)


def _build_rollup_document_id(person_id: str, week_start: str) -> str:
    return f"doc_{person_id}_garmin_weekly_rollup_{week_start}"


def _build_rollup_observation_id(person_id: str, week_start: str, metric_key: str) -> str:
    return f"obs_{person_id}_{week_start}_{normalize_id_component(metric_key)}_weekly_rollup"


def _build_rollup_metric_id(person_id: str, week_start: str, metric_key: str) -> str:
    return f"m_{person_id}_{week_start}_{normalize_id_component(metric_key)}_weekly_rollup"


def _metric_rows_for_names(
    rows: Sequence[GarminSourceMetricRecord],
    metric_names: Sequence[str],
) -> List[GarminSourceMetricRecord]:
    names = set(metric_names)
    return [row for row in rows if row.metric_name in names]


def _aggregate_metric_value(
    mapping: GarminWeeklyMetricMapping,
    rows: Sequence[GarminSourceMetricRecord],
) -> Optional[tuple[float, List[GarminSourceMetricRecord]]]:
    relevant_rows = _metric_rows_for_names(rows, mapping.source_metric_names)
    if not relevant_rows:
        return None

    if mapping.aggregation == "average":
        return (
            sum(row.value for row in relevant_rows) / len(relevant_rows),
            relevant_rows,
        )

    if mapping.aggregation == "sum":
        return (
            sum(row.value for row in relevant_rows),
            relevant_rows,
        )

    if mapping.aggregation == "count_distinct_activities":
        distinct_activity_rows: Dict[str, GarminSourceMetricRecord] = {}
        for row in relevant_rows:
            activity_id = _extract_activity_identity(row.observation_id)
            if activity_id is None:
                continue
            distinct_activity_rows.setdefault(activity_id, row)
        if not distinct_activity_rows:
            return None
        return float(len(distinct_activity_rows)), list(distinct_activity_rows.values())

    raise ValueError(f"Unsupported Garmin weekly aggregation: {mapping.aggregation}")


def build_garmin_weekly_rollup_rows(
    source_rows: Sequence[Any],
    *,
    person_id: str,
    mappings: Dict[str, GarminWeeklyMetricMapping],
) -> Dict[str, List[Dict[str, Any]]]:
    observations: List[Dict[str, Any]] = []
    health_metrics: List[Dict[str, Any]] = []

    rows_by_week: Dict[str, List[GarminSourceMetricRecord]] = {}
    normalized_source_rows: List[GarminSourceMetricRecord] = []
    for row in source_rows:
        if isinstance(row, GarminSourceMetricRecord):
            normalized_source_rows.append(row)
            continue
        coerced = _coerce_source_metric_row(row)
        if coerced is not None:
            normalized_source_rows.append(coerced)

    for row in normalized_source_rows:
        rows_by_week.setdefault(week_start_monday(row.metric_date), []).append(row)

    for week_start in sorted(rows_by_week):
        week_rows = rows_by_week[week_start]
        week_end = (date.fromisoformat(week_start) + timedelta(days=6)).isoformat()

        for metric_key, mapping in mappings.items():
            aggregate_result = _aggregate_metric_value(mapping, week_rows)
            if aggregate_result is None:
                continue

            value, contributing_rows = aggregate_result
            contributing_metric_ids = sorted({row.metric_id for row in contributing_rows})
            contributing_observation_ids = sorted(
                {row.observation_id for row in contributing_rows}
            )
            document_id = _build_rollup_document_id(person_id, week_start)
            observation_id = _build_rollup_observation_id(person_id, week_start, metric_key)
            metric_id = _build_rollup_metric_id(person_id, week_start, metric_key)
            notes = _compact_json(
                {
                    "aggregation": mapping.aggregation,
                    "source_metric_ids": contributing_metric_ids,
                    "source_observation_ids": contributing_observation_ids,
                    "week_end": week_end,
                }
            )

            observations.append(
                {
                    "observation_id": observation_id,
                    "person_id": person_id,
                    "document_id": document_id,
                    "observed_at": week_start,
                    "source": WEEKLY_ROLLUP_SOURCE,
                    "taxonomy": mapping.taxonomy,
                    "observation_type": "weekly_rollup",
                    "raw_label": mapping.display_name,
                    "raw_value": _format_numeric_raw_value(value),
                    "normalized_label": mapping.display_name,
                    "parsed_value": value,
                    "unit": mapping.unit,
                    "source_location": (
                        f"week_start={week_start};week_end={week_end};aggregation={mapping.aggregation}"
                    ),
                    "confidence": 1.0,
                    "conversion_status": "converted",
                    "raw_text": "",
                    "surrounding_text": "",
                    "failure_reason": "",
                    "notes": notes,
                }
            )
            health_metrics.append(
                {
                    "metric_id": metric_id,
                    "person_id": person_id,
                    "document_id": document_id,
                    "observation_id": observation_id,
                    "metric_date": week_start,
                    "source": WEEKLY_ROLLUP_SOURCE,
                    "category": mapping.category,
                    "metric_name": mapping.display_name,
                    "value": value,
                    "text_value": "",
                    "unit": mapping.unit,
                    "reference_low": None,
                    "reference_high": None,
                    "status": "tracked",
                    "notes": notes,
                }
            )

    observations.sort(key=lambda row: row["observation_id"])
    health_metrics.sort(key=lambda row: row["metric_id"])
    return {
        "observations": observations,
        "health_metrics": health_metrics,
    }


def delete_existing_weekly_rollup_rows(
    client: Any,
    *,
    project_id: str,
    dataset: str,
    table_name: str,
    person_id: str,
    week_start_dates: Sequence[str],
    query_job_config_factory: Optional[
        Callable[[str, Sequence[str], str], Any]
    ] = None,
) -> None:
    if not week_start_dates:
        return

    date_field = "metric_date" if table_name == "health_metric" else "observed_at"
    query = (
        f"DELETE FROM `{project_id}.{dataset}.{table_name}` "
        "WHERE person_id = @person_id "
        f"AND {date_field} IN UNNEST(@week_start_dates) "
        "AND source = @source"
    )
    config_factory = query_job_config_factory or _default_delete_query_job_config_factory
    client.query(
        query,
        job_config=config_factory(person_id, week_start_dates, WEEKLY_ROLLUP_SOURCE),
    ).result()


def load_weekly_rollup_rows_to_bigquery(
    client: Any,
    *,
    project_id: str,
    dataset: str,
    observation_rows: Sequence[Dict[str, Any]],
    health_metric_rows: Sequence[Dict[str, Any]],
    person_id: str,
    replace_existing: bool,
    delete_query_job_config_factory: Optional[
        Callable[[str, Sequence[str], str], Any]
    ] = None,
) -> None:
    week_start_dates = sorted(
        {str(row["metric_date"]) for row in health_metric_rows}
    )

    if replace_existing:
        delete_existing_weekly_rollup_rows(
            client,
            project_id=project_id,
            dataset=dataset,
            table_name="health_metric",
            person_id=person_id,
            week_start_dates=week_start_dates,
            query_job_config_factory=delete_query_job_config_factory,
        )
        delete_existing_weekly_rollup_rows(
            client,
            project_id=project_id,
            dataset=dataset,
            table_name="observation",
            person_id=person_id,
            week_start_dates=week_start_dates,
            query_job_config_factory=delete_query_job_config_factory,
        )

    # insert_rows uses staging load + INSERT SELECT, not streaming inserts.
    insert_rows(
        client,
        project_id=project_id,
        dataset=dataset,
        table_name="observation",
        rows=observation_rows,
        person_id=person_id,
        document_id=f"garmin_weekly_rollup_{week_start_dates[0] if week_start_dates else 'none'}",
    )
    insert_rows(
        client,
        project_id=project_id,
        dataset=dataset,
        table_name="health_metric",
        rows=health_metric_rows,
        person_id=person_id,
        document_id=f"garmin_weekly_rollup_{week_start_dates[0] if week_start_dates else 'none'}",
    )


def generate_garmin_weekly_rollup(
    *,
    environment_config_path: str | Path,
    person_id: str,
    start_date: str,
    end_date: str,
    output_observations_csv_path: str | Path,
    output_health_metrics_csv_path: str | Path,
    load_to_bigquery: bool,
    replace_existing: bool,
    client: Optional[Any] = None,
    view_exists_query_job_config_factory: Optional[Callable[[str], Any]] = None,
    metrics_query_job_config_factory: Optional[
        Callable[[str, str, str, str], Any]
    ] = None,
    delete_query_job_config_factory: Optional[
        Callable[[str, Sequence[str], str], Any]
    ] = None,
) -> Dict[str, Any]:
    parsed_start_date = parse_iso_date(start_date, field_name="start_date")
    parsed_end_date = parse_iso_date(end_date, field_name="end_date")
    if parsed_end_date < parsed_start_date:
        raise ValueError("end_date must be on or after start_date.")

    repo_root = Path(__file__).resolve().parents[3]
    mapping_path = repo_root / "config/metric_mappings/garmin_weekly_rollup_metrics.yaml"
    mappings = load_weekly_metric_mappings(mapping_path)

    environment_config = load_environment_config(environment_config_path)
    project_id = environment_config["gcp"]["project_id"]
    dataset = environment_config["bigquery"]["dataset"]
    bigquery_client = client or create_bigquery_client(project_id)

    source_rows = fetch_garmin_source_metrics(
        bigquery_client,
        project_id=project_id,
        dataset=dataset,
        person_id=person_id,
        start_date=parsed_start_date,
        end_date=parsed_end_date,
        view_exists_query_job_config_factory=view_exists_query_job_config_factory,
        metrics_query_job_config_factory=metrics_query_job_config_factory,
    )

    rollup_rows = build_garmin_weekly_rollup_rows(
        source_rows,
        person_id=person_id,
        mappings=mappings,
    )
    write_csv(
        rollup_rows["observations"],
        OBSERVATION_FIELDS,
        output_observations_csv_path,
    )
    write_csv(
        rollup_rows["health_metrics"],
        HEALTH_METRIC_FIELDS,
        output_health_metrics_csv_path,
    )

    if load_to_bigquery:
        load_weekly_rollup_rows_to_bigquery(
            bigquery_client,
            project_id=project_id,
            dataset=dataset,
            observation_rows=rollup_rows["observations"],
            health_metric_rows=rollup_rows["health_metrics"],
            person_id=person_id,
            replace_existing=replace_existing,
            delete_query_job_config_factory=delete_query_job_config_factory,
        )

    return {
        "project_id": project_id,
        "dataset": dataset,
        "source_rows_read": len(source_rows),
        "weekly_observations_created": len(rollup_rows["observations"]),
        "weekly_health_metrics_created": len(rollup_rows["health_metrics"]),
        "load_to_bigquery": load_to_bigquery,
        "replace_existing": replace_existing,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    try:
        generate_garmin_weekly_rollup(
            environment_config_path=args.environment_config,
            person_id=args.person_id,
            start_date=args.start_date,
            end_date=args.end_date,
            output_observations_csv_path=args.output_observations_csv,
            output_health_metrics_csv_path=args.output_health_metrics_csv,
            load_to_bigquery=args.load_to_bigquery,
            replace_existing=args.replace_existing,
        )
    except RuntimeError as exc:
        parser.exit(status=2, message=f"error: {exc}\n")
    return 0

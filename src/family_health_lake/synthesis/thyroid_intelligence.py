from __future__ import annotations

import argparse
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from family_health_lake.utils import get_row_value, normalize_id_component

from family_health_lake.ingestion.bigquery_csv_loader import (
    create_bigquery_client,
    load_environment_config,
)


THYROID_TAXONOMY = "medical_lab_reports"
THYROID_CATEGORY = "thyroid"
THYROID_METRIC_NAMES = (
    "TSH",
    "Free T4",
    "Free T3",
    "Total T3",
    "Total T4",
    "Anti-TPO Antibody",
    "Anti-Tg Antibody",
)
STREAMING_BUFFER_ERROR_SNIPPET = "would affect rows in the streaming buffer"
TABLE_SYNC_CONFIG = {
    "metric_trend": {
        "id_field": "trend_id",
        "field_specs": [
            ("trend_id", "STRING"),
            ("person_id", "STRING"),
            ("taxonomy", "STRING"),
            ("category", "STRING"),
            ("metric_name", "STRING"),
            ("trend_type", "STRING"),
            ("trend_summary", "STRING"),
            ("trend_status", "STRING"),
            ("start_date", "DATE"),
            ("end_date", "DATE"),
            ("related_metric_ids", "ARRAY<STRING>"),
            ("source_document_ids", "ARRAY<STRING>"),
        ],
    },
    "alert": {
        "id_field": "alert_id",
        "field_specs": [
            ("alert_id", "STRING"),
            ("person_id", "STRING"),
            ("taxonomy", "STRING"),
            ("category", "STRING"),
            ("alert_type", "STRING"),
            ("severity", "STRING"),
            ("message", "STRING"),
            ("status", "STRING"),
            ("related_metric_ids", "ARRAY<STRING>"),
            ("related_trend_ids", "ARRAY<STRING>"),
            ("source_document_ids", "ARRAY<STRING>"),
        ],
    },
    "insight": {
        "id_field": "insight_id",
        "field_specs": [
            ("insight_id", "STRING"),
            ("person_id", "STRING"),
            ("taxonomy", "STRING"),
            ("category", "STRING"),
            ("insight_type", "STRING"),
            ("summary", "STRING"),
            ("insight_status", "STRING"),
            ("supporting_metric_ids", "ARRAY<STRING>"),
            ("supporting_trend_ids", "ARRAY<STRING>"),
            ("supporting_alert_ids", "ARRAY<STRING>"),
            ("source_document_ids", "ARRAY<STRING>"),
        ],
    },
}


def _field_specs_for_table(table_name: str) -> List[tuple[str, str]]:
    return list(TABLE_SYNC_CONFIG[table_name]["field_specs"])


def _field_names_for_table(table_name: str) -> List[str]:
    return [
        field_name for field_name, _field_type in _field_specs_for_table(table_name)
    ]


@dataclass(frozen=True)
class HealthMetricRecord:
    metric_id: str
    person_id: str
    document_id: str
    metric_date: str
    category: str
    metric_name: str
    status: str


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate thyroid metric_trend, alert, and insight rows from BigQuery health_metric data."
    )
    parser.add_argument("--environment-config", required=True)
    parser.add_argument("--person-id", required=True)
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--replace-existing", action="store_true")
    return parser


def _make_thyroid_intelligence_id(
    prefix: str,
    person_id: str,
    document_id: str,
    suffix: str,
) -> str:
    return f"{prefix}_{person_id}_{document_id}_{suffix}"


def _default_metric_query_job_config_factory(
    person_id: str,
    document_id: str,
    metric_names: Sequence[str],
) -> Any:
    try:
        from google.cloud import bigquery  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-bigquery is required for thyroid synthesis. Install the bigquery extra before running this CLI."
        ) from exc

    return bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("person_id", "STRING", person_id),
            bigquery.ScalarQueryParameter("document_id", "STRING", document_id),
            bigquery.ArrayQueryParameter("metric_names", "STRING", list(metric_names)),
        ]
    )


def _default_delete_job_config_factory(document_id: str, person_id: str) -> Any:
    try:
        from google.cloud import bigquery  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-bigquery is required for thyroid synthesis. Install the bigquery extra before running this CLI."
        ) from exc

    return bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("document_id", "STRING", document_id),
            bigquery.ScalarQueryParameter("person_id", "STRING", person_id),
        ]
    )


def _default_insert_job_config_factory(
    table_name: str,
    row: Dict[str, Any],
) -> Any:
    try:
        from google.cloud import bigquery  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-bigquery is required for thyroid synthesis. Install the bigquery extra before running this CLI."
        ) from exc

    parameters = []
    for field_name, field_type in _field_specs_for_table(table_name):
        value = row.get(field_name)
        if field_type == "ARRAY<STRING>":
            parameters.append(
                bigquery.ArrayQueryParameter(field_name, "STRING", list(value or []))
            )
        else:
            parameters.append(
                bigquery.ScalarQueryParameter(field_name, field_type, value)
            )

    return bigquery.QueryJobConfig(query_parameters=parameters)


def _default_existing_row_query_job_config_factory(row_ids: Sequence[str]) -> Any:
    try:
        from google.cloud import bigquery  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-bigquery is required for thyroid synthesis. Install the bigquery extra before running this CLI."
        ) from exc

    return bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("row_ids", "STRING", list(row_ids)),
        ]
    )


def fetch_thyroid_metrics(
    client: Any,
    *,
    project_id: str,
    dataset: str,
    person_id: str,
    document_id: str,
    query_job_config_factory: Optional[
        Callable[[str, str, Sequence[str]], Any]
    ] = None,
) -> List[HealthMetricRecord]:
    query = (
        f"SELECT metric_id, person_id, document_id, metric_date, category, metric_name, status "
        f"FROM `{project_id}.{dataset}.health_metric` "
        "WHERE person_id = @person_id "
        "AND document_id = @document_id "
        "AND metric_name IN UNNEST(@metric_names) "
        "ORDER BY metric_date DESC, metric_id ASC"
    )
    config_factory = query_job_config_factory or _default_metric_query_job_config_factory
    query_job = client.query(
        query,
        job_config=config_factory(person_id, document_id, THYROID_METRIC_NAMES),
    )
    rows = query_job.result()
    return [
        HealthMetricRecord(
            metric_id=str(get_row_value(row, "metric_id")),
            person_id=str(get_row_value(row, "person_id")),
            document_id=str(get_row_value(row, "document_id")),
            metric_date=str(get_row_value(row, "metric_date")),
            category=str(get_row_value(row, "category") or THYROID_CATEGORY),
            metric_name=str(get_row_value(row, "metric_name")),
            status=str(get_row_value(row, "status") or ""),
        )
        for row in rows
    ]


def select_latest_metric_by_name(
    metrics: Sequence[HealthMetricRecord],
) -> Dict[str, HealthMetricRecord]:
    latest_by_name: Dict[str, HealthMetricRecord] = {}
    sorted_metrics = sorted(metrics, key=lambda record: record.metric_id)
    sorted_metrics = sorted(
        sorted_metrics,
        key=lambda record: record.metric_date,
        reverse=True,
    )
    for metric in sorted_metrics:
        latest_by_name.setdefault(metric.metric_name, metric)
    return latest_by_name


def build_thyroid_intelligence_rows(
    metrics: Sequence[HealthMetricRecord],
    *,
    person_id: str,
    document_id: str,
) -> Dict[str, List[Dict[str, Any]]]:
    if not metrics:
        raise ValueError(
            f"No thyroid health_metric rows found for person_id='{person_id}' and document_id='{document_id}'."
        )

    latest_by_name = select_latest_metric_by_name(metrics)
    tsh_metric = latest_by_name.get("TSH")
    if tsh_metric is None:
        raise ValueError(
            f"No TSH health_metric row found for person_id='{person_id}' and document_id='{document_id}'."
        )

    trend_rows: List[Dict[str, Any]] = []
    alert_rows: List[Dict[str, Any]] = []
    insight_rows: List[Dict[str, Any]] = []

    if tsh_metric.status == "high":
        trend_id = _make_thyroid_intelligence_id(
            "trend",
            person_id,
            document_id,
            "thyroid_tsh_above_reference",
        )
        trend_rows.append(
            {
                "trend_id": trend_id,
                "person_id": person_id,
                "taxonomy": THYROID_TAXONOMY,
                "category": THYROID_CATEGORY,
                "metric_name": "TSH",
                "trend_type": "latest_status",
                "trend_summary": "TSH is above reference range on the latest available test.",
                "trend_status": "above_reference",
                "start_date": tsh_metric.metric_date,
                "end_date": tsh_metric.metric_date,
                "related_metric_ids": [tsh_metric.metric_id],
                "source_document_ids": [document_id],
            }
        )

        related_alert_metric_ids = [
            metric.metric_id
            for metric_name in ("TSH", "Free T4", "Free T3")
            if (metric := latest_by_name.get(metric_name)) is not None
        ]
        alert_id = _make_thyroid_intelligence_id(
            "alert",
            person_id,
            document_id,
            "thyroid_tsh_above_reference",
        )
        alert_rows.append(
            {
                "alert_id": alert_id,
                "person_id": person_id,
                "taxonomy": THYROID_TAXONOMY,
                "category": THYROID_CATEGORY,
                "alert_type": "metric_above_reference",
                "severity": "monitor",
                "message": "TSH is above reference range while FT4 and FT3 are in range.",
                "status": "active",
                "related_metric_ids": related_alert_metric_ids,
                "related_trend_ids": [trend_id],
                "source_document_ids": [document_id],
            }
        )

        supporting_metric_ids = [
            metric.metric_id
            for metric_name in (
                "TSH",
                "Free T4",
                "Free T3",
                "Anti-TPO Antibody",
                "Anti-Tg Antibody",
            )
            if (metric := latest_by_name.get(metric_name)) is not None
        ]
        insight_rows.append(
            {
                "insight_id": _make_thyroid_intelligence_id(
                    "insight",
                    person_id,
                    document_id,
                    "thyroid_status",
                ),
                "person_id": person_id,
                "taxonomy": THYROID_TAXONOMY,
                "category": THYROID_CATEGORY,
                "insight_type": "thyroid_status",
                "summary": "Thyroid is monitored but not fully optimized because TSH is above reference range while FT4 and FT3 are in range.",
                "insight_status": "active",
                "supporting_metric_ids": supporting_metric_ids,
                "supporting_trend_ids": [trend_id],
                "supporting_alert_ids": [alert_id],
                "source_document_ids": [document_id],
            }
        )

    return {
        "metric_trend_rows": trend_rows,
        "alert_rows": alert_rows,
        "insight_rows": insight_rows,
    }


def _is_streaming_buffer_mutation_error(exc: Exception) -> bool:
    return STREAMING_BUFFER_ERROR_SNIPPET in str(exc)


def _normalize_comparison_value(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return [_normalize_comparison_value(item) for item in value]
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def delete_existing_thyroid_rows_for_table(
    client: Any,
    *,
    project_id: str,
    dataset: str,
    table_name: str,
    document_id: str,
    person_id: str,
    query_job_config_factory: Optional[Callable[[str, str], Any]] = None,
) -> None:
    config_factory = query_job_config_factory or _default_delete_job_config_factory
    job_config = config_factory(document_id, person_id)
    query = (
        f"DELETE FROM `{project_id}.{dataset}.{table_name}` "
        "WHERE person_id = @person_id "
        f"AND taxonomy = '{THYROID_TAXONOMY}' "
        f"AND category = '{THYROID_CATEGORY}' "
        "AND @document_id IN UNNEST(source_document_ids)"
    )
    client.query(query, job_config=job_config).result()


def fetch_existing_rows_by_ids(
    client: Any,
    *,
    project_id: str,
    dataset: str,
    table_name: str,
    row_ids: Sequence[str],
    query_job_config_factory: Optional[Callable[[Sequence[str]], Any]] = None,
) -> List[Dict[str, Any]]:
    if not row_ids:
        return []

    field_names = _field_names_for_table(table_name)
    id_field = TABLE_SYNC_CONFIG[table_name]["id_field"]
    query = (
        f"SELECT {', '.join(field_names)} "
        f"FROM `{project_id}.{dataset}.{table_name}` "
        f"WHERE {id_field} IN UNNEST(@row_ids)"
    )
    config_factory = (
        query_job_config_factory or _default_existing_row_query_job_config_factory
    )
    query_job = client.query(query, job_config=config_factory(row_ids))
    rows = query_job.result()
    return [
        {
            field_name: _normalize_comparison_value(get_row_value(row, field_name))
            for field_name in field_names
        }
        for row in rows
    ]


def table_already_has_expected_rows(
    client: Any,
    *,
    project_id: str,
    dataset: str,
    table_name: str,
    rows: Sequence[Dict[str, Any]],
    existing_row_query_job_config_factory: Optional[Callable[[Sequence[str]], Any]] = None,
) -> bool:
    if not rows:
        return False

    field_names = _field_names_for_table(table_name)
    id_field = TABLE_SYNC_CONFIG[table_name]["id_field"]
    row_ids = [str(row[id_field]) for row in rows]
    existing_rows = fetch_existing_rows_by_ids(
        client,
        project_id=project_id,
        dataset=dataset,
        table_name=table_name,
        row_ids=row_ids,
        query_job_config_factory=existing_row_query_job_config_factory,
    )
    if len(existing_rows) != len(rows):
        return False

    existing_by_id = {str(row[id_field]): row for row in existing_rows}
    for row in rows:
        expected_row = {
            field_name: _normalize_comparison_value(row.get(field_name))
            for field_name in field_names
        }
        if existing_by_id.get(str(row[id_field])) != expected_row:
            return False
    return True


def insert_thyroid_rows_for_table(
    client: Any,
    *,
    project_id: str,
    dataset: str,
    table_name: str,
    rows: Sequence[Dict[str, Any]],
    query_job_config_factory: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
) -> None:
    if not rows:
        return

    field_names = _field_names_for_table(table_name)
    query = (
        f"INSERT INTO `{project_id}.{dataset}.{table_name}` "
        f"({', '.join(field_names)}) "
        f"VALUES ({', '.join(f'@{field_name}' for field_name in field_names)})"
    )
    config_factory = query_job_config_factory or _default_insert_job_config_factory
    for row in rows:
        client.query(
            query,
            job_config=config_factory(table_name, row),
        ).result()


def generate_thyroid_intelligence(
    *,
    environment_config_path: str | Path,
    person_id: str,
    document_id: str,
    replace_existing: bool,
    client: Optional[Any] = None,
    metric_query_job_config_factory: Optional[
        Callable[[str, str, Sequence[str]], Any]
    ] = None,
    delete_query_job_config_factory: Optional[Callable[[str, str], Any]] = None,
    insert_query_job_config_factory: Optional[
        Callable[[str, Dict[str, Any]], Any]
    ] = None,
    existing_row_query_job_config_factory: Optional[
        Callable[[Sequence[str]], Any]
    ] = None,
) -> Dict[str, Any]:
    environment_config = load_environment_config(environment_config_path)
    project_id = environment_config["gcp"]["project_id"]
    dataset = environment_config["bigquery"]["dataset"]
    bigquery_client = client or create_bigquery_client(project_id)

    metrics = fetch_thyroid_metrics(
        bigquery_client,
        project_id=project_id,
        dataset=dataset,
        person_id=person_id,
        document_id=document_id,
        query_job_config_factory=metric_query_job_config_factory,
    )
    rows = build_thyroid_intelligence_rows(
        metrics,
        person_id=person_id,
        document_id=document_id,
    )

    tables_already_synced = 0
    skipped_inserts: set[str] = set()

    if replace_existing:
        for table_name in ("metric_trend", "alert", "insight"):
            table_rows = rows[f"{table_name}_rows"]
            try:
                delete_existing_thyroid_rows_for_table(
                    bigquery_client,
                    project_id=project_id,
                    dataset=dataset,
                    table_name=table_name,
                    document_id=document_id,
                    person_id=person_id,
                    query_job_config_factory=delete_query_job_config_factory,
                )
            except Exception as exc:
                if not _is_streaming_buffer_mutation_error(exc):
                    raise
                if table_already_has_expected_rows(
                    bigquery_client,
                    project_id=project_id,
                    dataset=dataset,
                    table_name=table_name,
                    rows=table_rows,
                    existing_row_query_job_config_factory=existing_row_query_job_config_factory,
                ):
                    skipped_inserts.add(table_name)
                    tables_already_synced += 1
                    continue
                raise RuntimeError(
                    f"Cannot replace existing thyroid {table_name} rows yet because BigQuery is still buffering recent streamed rows for this document. "
                    "Wait a few minutes and retry `--replace-existing`."
                ) from exc

    for table_name, table_rows in (
        ("metric_trend", rows["metric_trend_rows"]),
        ("alert", rows["alert_rows"]),
        ("insight", rows["insight_rows"]),
    ):
        if table_name in skipped_inserts:
            continue
        insert_thyroid_rows_for_table(
            bigquery_client,
            project_id=project_id,
            dataset=dataset,
            table_name=table_name,
            rows=table_rows,
            query_job_config_factory=insert_query_job_config_factory,
        )

    return {
        "project_id": project_id,
        "dataset": dataset,
        "replace_existing": replace_existing,
        "health_metrics_read": len(metrics),
        "metric_trends_created": len(rows["metric_trend_rows"]),
        "alerts_created": len(rows["alert_rows"]),
        "insights_created": len(rows["insight_rows"]),
        "tables_already_synced": tables_already_synced,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    try:
        generate_thyroid_intelligence(
            environment_config_path=args.environment_config,
            person_id=args.person_id,
            document_id=args.document_id,
            replace_existing=args.replace_existing,
        )
    except RuntimeError as exc:
        parser.exit(status=2, message=f"error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from family_health_lake.ingestion.bigquery_csv_loader import (
    create_bigquery_client,
    insert_rows,
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
        "field_names": [
            "trend_id",
            "person_id",
            "taxonomy",
            "category",
            "metric_name",
            "trend_type",
            "trend_summary",
            "trend_status",
            "start_date",
            "end_date",
            "related_metric_ids",
            "source_document_ids",
        ],
    },
    "alert": {
        "id_field": "alert_id",
        "field_names": [
            "alert_id",
            "person_id",
            "taxonomy",
            "category",
            "alert_type",
            "severity",
            "message",
            "status",
            "related_metric_ids",
            "related_trend_ids",
            "source_document_ids",
        ],
    },
    "insight": {
        "id_field": "insight_id",
        "field_names": [
            "insight_id",
            "person_id",
            "taxonomy",
            "category",
            "insight_type",
            "summary",
            "insight_status",
            "supporting_metric_ids",
            "supporting_trend_ids",
            "supporting_alert_ids",
            "source_document_ids",
        ],
    },
}


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


def normalize_id_component(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    snake_case = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_value.lower()).strip("_")
    return re.sub(r"_+", "_", snake_case)


def _make_package_id(prefix: str, person_id: str, document_id: str, name: str) -> str:
    return "_".join(
        [
            prefix,
            normalize_id_component(person_id),
            normalize_id_component(document_id),
            normalize_id_component(name),
        ]
    )


def _get_row_value(row: Any, field_name: str) -> Any:
    if isinstance(row, dict):
        return row.get(field_name)
    try:
        return row[field_name]
    except (KeyError, TypeError, IndexError):
        return getattr(row, field_name)


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
            metric_id=str(_get_row_value(row, "metric_id")),
            person_id=str(_get_row_value(row, "person_id")),
            document_id=str(_get_row_value(row, "document_id")),
            metric_date=str(_get_row_value(row, "metric_date")),
            category=str(_get_row_value(row, "category") or THYROID_CATEGORY),
            metric_name=str(_get_row_value(row, "metric_name")),
            status=str(_get_row_value(row, "status") or ""),
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
        trend_id = _make_package_id(
            "trend",
            person_id,
            document_id,
            "thyroid_tsh_latest_status",
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
        alert_id = _make_package_id(
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
                "insight_id": _make_package_id(
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

    table_config = TABLE_SYNC_CONFIG[table_name]
    field_names = table_config["field_names"]
    id_field = table_config["id_field"]
    query = (
        f"SELECT {', '.join(field_names)} "
        f"FROM `{project_id}.{dataset}.{table_name}` "
        f"WHERE {id_field} IN UNNEST(@row_ids)"
    )
    config_factory = query_job_config_factory or _default_existing_row_query_job_config_factory
    query_job = client.query(
        query,
        job_config=config_factory(row_ids),
    )
    rows = query_job.result()
    return [
        {
            field_name: _normalize_comparison_value(_get_row_value(row, field_name))
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

    table_config = TABLE_SYNC_CONFIG[table_name]
    field_names = table_config["field_names"]
    id_field = table_config["id_field"]
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
        existing_row = existing_by_id.get(str(row[id_field]))
        if existing_row != expected_row:
            return False
    return True


def sync_thyroid_table(
    client: Any,
    *,
    project_id: str,
    dataset: str,
    table_name: str,
    rows: Sequence[Dict[str, Any]],
    document_id: str,
    person_id: str,
    replace_existing: bool,
    delete_query_job_config_factory: Optional[Callable[[str, str], Any]] = None,
    existing_row_query_job_config_factory: Optional[Callable[[Sequence[str]], Any]] = None,
) -> bool:
    if replace_existing:
        try:
            delete_existing_thyroid_rows_for_table(
                client,
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
                client,
                project_id=project_id,
                dataset=dataset,
                table_name=table_name,
                rows=rows,
                existing_row_query_job_config_factory=existing_row_query_job_config_factory,
            ):
                return True
            raise RuntimeError(
                f"Cannot replace existing thyroid {table_name} rows yet because BigQuery is still buffering recent streamed rows for this document. "
                "Wait a few minutes and retry `--replace-existing`."
            ) from exc

    insert_rows(
        client,
        project_id=project_id,
        dataset=dataset,
        table_name=table_name,
        rows=rows,
    )
    return False


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
    existing_row_query_job_config_factory: Optional[Callable[[Sequence[str]], Any]] = None,
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

    already_synced_tables = 0
    for table_name, table_rows in (
        ("metric_trend", rows["metric_trend_rows"]),
        ("alert", rows["alert_rows"]),
        ("insight", rows["insight_rows"]),
    ):
        already_synced_tables += int(
            sync_thyroid_table(
                bigquery_client,
                project_id=project_id,
                dataset=dataset,
                table_name=table_name,
                rows=table_rows,
                document_id=document_id,
                person_id=person_id,
                replace_existing=replace_existing,
                delete_query_job_config_factory=delete_query_job_config_factory,
                existing_row_query_job_config_factory=existing_row_query_job_config_factory,
            )
        )

    return {
        "project_id": project_id,
        "dataset": dataset,
        "replace_existing": replace_existing,
        "health_metrics_read": len(metrics),
        "metric_trends_created": len(rows["metric_trend_rows"]),
        "alerts_created": len(rows["alert_rows"]),
        "insights_created": len(rows["insight_rows"]),
        "tables_already_synced": already_synced_tables,
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

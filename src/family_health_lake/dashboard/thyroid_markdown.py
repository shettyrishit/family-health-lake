from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from family_health_lake.ingestion.bigquery_csv_loader import (
    create_bigquery_client,
    load_environment_config,
)

from family_health_lake.utils import get_row_value


THYROID_DASHBOARD_CARD_FIELD_NAMES = [
    "person_id",
    "insight_id",
    "insight_summary",
    "insight_status",
    "alert_id",
    "alert_type",
    "alert_message",
    "alert_severity",
    "trend_id",
    "trend_summary",
    "trend_status",
    "document_id",
    "file_uri",
]
THYROID_DASHBOARD_TRACE_FIELD_NAMES = [
    "person_id",
    "insight_id",
    "alert_id",
    "trend_id",
    "metric_id",
    "metric_name",
    "value",
    "text_value",
    "unit",
    "reference_low",
    "reference_high",
    "metric_status",
    "observation_id",
    "raw_label",
    "raw_value",
    "normalized_label",
    "source_location",
    "document_id",
    "file_uri",
]
THYROID_DASHBOARD_FIELD_NAMES = THYROID_DASHBOARD_TRACE_FIELD_NAMES


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render a thyroid dashboard Markdown card from the BigQuery thyroid dashboard view."
    )
    parser.add_argument("--environment-config", required=True)
    parser.add_argument("--person-id", required=True)
    parser.add_argument("--output-md", required=True)
    return parser


def _default_query_job_config_factory(person_id: str) -> Any:
    try:
        from google.cloud import bigquery  # type: ignore
    except ImportError as exc:
        return None

    return bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("person_id", "STRING", person_id),
        ]
    )


def fetch_thyroid_dashboard_card_rows(
    client: Any,
    *,
    project_id: str,
    dataset: str,
    person_id: str,
    query_job_config_factory: Optional[Callable[[str], Any]] = None,
) -> List[Dict[str, Any]]:
    query = (
        f"SELECT {', '.join(THYROID_DASHBOARD_CARD_FIELD_NAMES)} "
        f"FROM `{project_id}.{dataset}.v_thyroid_dashboard_card` "
        "WHERE person_id = @person_id "
        "ORDER BY insight_id, alert_id, trend_id"
    )
    config_factory = query_job_config_factory or _default_query_job_config_factory
    query_job = client.query(query, job_config=config_factory(person_id))
    return [
        {
            field_name: get_row_value(row, field_name)
            for field_name in THYROID_DASHBOARD_CARD_FIELD_NAMES
        }
        for row in query_job.result()
    ]


def fetch_thyroid_dashboard_trace_rows(
    client: Any,
    *,
    project_id: str,
    dataset: str,
    person_id: str,
    query_job_config_factory: Optional[Callable[[str], Any]] = None,
) -> List[Dict[str, Any]]:
    query = (
        f"SELECT {', '.join(THYROID_DASHBOARD_TRACE_FIELD_NAMES)} "
        f"FROM `{project_id}.{dataset}.v_thyroid_dashboard_trace` "
        "WHERE person_id = @person_id "
        "ORDER BY metric_name, metric_id, observation_id"
    )
    config_factory = query_job_config_factory or _default_query_job_config_factory
    query_job = client.query(query, job_config=config_factory(person_id))
    return [
        {
            field_name: get_row_value(row, field_name)
            for field_name in THYROID_DASHBOARD_TRACE_FIELD_NAMES
        }
        for row in query_job.result()
    ]


def fetch_thyroid_dashboard_rows(
    client: Any,
    *,
    project_id: str,
    dataset: str,
    person_id: str,
    query_job_config_factory: Optional[Callable[[str], Any]] = None,
) -> List[Dict[str, Any]]:
    """Backward-compatible alias for the trace-detail dashboard rows."""
    return fetch_thyroid_dashboard_trace_rows(
        client,
        project_id=project_id,
        dataset=dataset,
        person_id=person_id,
        query_job_config_factory=query_job_config_factory,
    )


def _first_non_empty_value(rows: Sequence[Dict[str, Any]], field_name: str) -> str:
    for row in rows:
        value = row.get(field_name)
        if value not in (None, ""):
            return str(value)
    return ""


def _format_metric_value(row: Dict[str, Any]) -> str:
    text_value = row.get("text_value")
    if text_value not in (None, ""):
        return str(text_value)
    value = row.get("value")
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _format_reference_range(row: Dict[str, Any]) -> str:
    low = row.get("reference_low")
    high = row.get("reference_high")
    if low is None and high is None:
        return ""
    if low is None:
        return f"<= {high:g}" if isinstance(high, float) else f"<= {high}"
    if high is None:
        return f">= {low:g}" if isinstance(low, float) else f">= {low}"
    low_text = f"{low:g}" if isinstance(low, float) else str(low)
    high_text = f"{high:g}" if isinstance(high, float) else str(high)
    return f"{low_text} - {high_text}"


def dedupe_metric_rows(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    metric_rows: List[Dict[str, Any]] = []
    seen_metric_ids: set[str] = set()
    for row in rows:
        metric_id = str(row.get("metric_id") or "")
        if not metric_id or metric_id in seen_metric_ids:
            continue
        seen_metric_ids.add(metric_id)
        metric_rows.append(row)
    return metric_rows


def group_trace_rows_by_metric(
    rows: Sequence[Dict[str, Any]],
) -> List[tuple[Dict[str, Any], List[Dict[str, Any]]]]:
    metric_lookup: Dict[str, Dict[str, Any]] = {}
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    seen_signatures_by_metric: Dict[str, set[tuple[str, ...]]] = {}

    for row in rows:
        metric_id = str(row.get("metric_id") or "")
        if not metric_id:
            continue
        metric_lookup.setdefault(metric_id, row)
        grouped.setdefault(metric_id, [])
        seen_signatures_by_metric.setdefault(metric_id, set())

        signature = tuple(
            str(row.get(field_name) or "")
            for field_name in (
                "insight_id",
                "alert_id",
                "trend_id",
                "metric_id",
                "observation_id",
                "raw_label",
                "raw_value",
                "source_location",
                "document_id",
                "file_uri",
            )
        )
        if signature in seen_signatures_by_metric[metric_id]:
            continue
        seen_signatures_by_metric[metric_id].add(signature)
        grouped[metric_id].append(row)

    return [
        (metric_lookup[metric_id], grouped[metric_id])
        for metric_id in metric_lookup
    ]


def render_thyroid_dashboard_markdown(
    card_rows: Sequence[Dict[str, Any]],
    trace_rows: Sequence[Dict[str, Any]],
    *,
    person_id: str,
) -> str:
    lines = [f"# Thyroid Dashboard — {person_id}", ""]

    if not card_rows and not trace_rows:
        lines.extend(
            [
                "No thyroid dashboard rows found.",
                "",
            ]
        )
        return "\n".join(lines).rstrip() + "\n"

    lines.extend(
        [
            "## Insight Summary",
            _first_non_empty_value(card_rows, "insight_summary") or "No insight available.",
            "",
            f"Status: {_first_non_empty_value(card_rows, 'insight_status') or 'unknown'}",
            "",
            "## Alert Summary",
            _first_non_empty_value(card_rows, "alert_message") or "No alert available.",
            "",
            f"Type: {_first_non_empty_value(card_rows, 'alert_type') or 'n/a'}",
            f"Severity: {_first_non_empty_value(card_rows, 'alert_severity') or 'n/a'}",
            "",
            "## Trend Summary",
            _first_non_empty_value(card_rows, "trend_summary") or "No trend available.",
            "",
            f"Status: {_first_non_empty_value(card_rows, 'trend_status') or 'unknown'}",
            "",
            "## Key Metrics",
            "| Metric | Value | Unit | Reference Range | Status |",
            "| --- | --- | --- | --- | --- |",
        ]
    )

    for row in dedupe_metric_rows(trace_rows):
        lines.append(
            "| {metric} | {value} | {unit} | {reference_range} | {status} |".format(
                metric=row.get("metric_name") or "",
                value=_format_metric_value(row),
                unit=row.get("unit") or "",
                reference_range=_format_reference_range(row),
                status=row.get("metric_status") or "",
            )
        )

    lines.extend(["", "## Trace", ""])

    for metric_row, metric_trace_rows in group_trace_rows_by_metric(trace_rows):
        lines.append(f"### {metric_row.get('metric_name') or metric_row.get('metric_id')}")
        lines.append("")
        for trace_row in metric_trace_rows:
            lines.extend(
                [
                    f"- `insight_id`: {trace_row.get('insight_id') or ''}",
                    f"- `alert_id`: {trace_row.get('alert_id') or ''}",
                    f"- `trend_id`: {trace_row.get('trend_id') or ''}",
                    f"- `metric_id`: {trace_row.get('metric_id') or ''}",
                    f"- `observation_id`: {trace_row.get('observation_id') or ''}",
                    f"- `raw_label`: {trace_row.get('raw_label') or ''}",
                    f"- `raw_value`: {trace_row.get('raw_value') or ''}",
                    f"- `source_location`: {trace_row.get('source_location') or ''}",
                    f"- `document_id`: {trace_row.get('document_id') or ''}",
                    f"- `file_uri`: {trace_row.get('file_uri') or ''}",
                    "",
                ]
            )

    return "\n".join(lines).rstrip() + "\n"


def render_thyroid_dashboard_to_markdown(
    *,
    environment_config_path: str | Path,
    person_id: str,
    output_md_path: str | Path,
    client: Optional[Any] = None,
    query_job_config_factory: Optional[Callable[[str], Any]] = None,
) -> Dict[str, Any]:
    environment_config = load_environment_config(environment_config_path)
    project_id = environment_config["gcp"]["project_id"]
    dataset = environment_config["bigquery"]["dataset"]
    bigquery_client = client or create_bigquery_client(project_id)

    card_rows = fetch_thyroid_dashboard_card_rows(
        bigquery_client,
        project_id=project_id,
        dataset=dataset,
        person_id=person_id,
        query_job_config_factory=query_job_config_factory,
    )
    trace_rows = fetch_thyroid_dashboard_trace_rows(
        bigquery_client,
        project_id=project_id,
        dataset=dataset,
        person_id=person_id,
        query_job_config_factory=query_job_config_factory,
    )
    markdown = render_thyroid_dashboard_markdown(
        card_rows,
        trace_rows,
        person_id=person_id,
    )

    output_path = Path(output_md_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")

    return {
        "project_id": project_id,
        "dataset": dataset,
        "person_id": person_id,
        "output_md_path": str(output_path),
        "dashboard_card_rows_read": len(card_rows),
        "dashboard_trace_rows_read": len(trace_rows),
        "metric_rows_rendered": len(dedupe_metric_rows(trace_rows)),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    try:
        render_thyroid_dashboard_to_markdown(
            environment_config_path=args.environment_config,
            person_id=args.person_id,
            output_md_path=args.output_md,
        )
    except RuntimeError as exc:
        parser.exit(status=2, message=f"error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

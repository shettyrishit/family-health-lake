from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence


OBSERVATION_FIELDS = [
    "observation_id",
    "person_id",
    "document_id",
    "observed_at",
    "source",
    "taxonomy",
    "observation_type",
    "raw_label",
    "raw_value",
    "normalized_label",
    "parsed_value",
    "unit",
    "source_location",
    "confidence",
    "conversion_status",
    "raw_text",
    "surrounding_text",
    "failure_reason",
    "notes",
]

HEALTH_METRIC_FIELDS = [
    "metric_id",
    "person_id",
    "document_id",
    "observation_id",
    "metric_date",
    "source",
    "category",
    "metric_name",
    "value",
    "text_value",
    "unit",
    "reference_low",
    "reference_high",
    "status",
    "notes",
]

OBSERVATION_REQUIRED_FIELDS = {"observation_id", "person_id"}
HEALTH_METRIC_REQUIRED_FIELDS = {"metric_id", "person_id", "observation_id", "metric_date", "metric_name"}
FLOAT_FIELDS = {"parsed_value", "confidence", "value", "reference_low", "reference_high"}
DATE_FIELDS = {"observed_at", "metric_date"}


@dataclass(frozen=True)
class TableLoadConfig:
    table_name: str
    fieldnames: Sequence[str]
    required_fields: set[str]


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Load extracted observations and health metrics CSVs into BigQuery."
    )
    parser.add_argument("--environment-config", required=True)
    parser.add_argument("--observations-csv", required=True)
    parser.add_argument("--health-metrics-csv", required=True)
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--person-id", required=True)
    parser.add_argument("--replace-existing", action="store_true")
    return parser


def _strip_yaml_string(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _load_simple_yaml(path: Path) -> Dict[str, Any]:
    root: Dict[str, Any] = {}
    stack: List[tuple[int, Dict[str, Any]]] = [(-1, root)]

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()

        while stack and indent <= stack[-1][0]:
            stack.pop()
        current = stack[-1][1]

        if value == "":
            child: Dict[str, Any] = {}
            current[key] = child
            stack.append((indent, child))
        else:
            current[key] = _strip_yaml_string(value)

    return root


def load_environment_config(path: str | Path) -> Dict[str, Any]:
    config_path = Path(path)
    try:
        import yaml  # type: ignore
    except ImportError:
        config = _load_simple_yaml(config_path)
    else:
        with config_path.open("r", encoding="utf-8") as handle:
            config = yaml.safe_load(handle) or {}

    gcp = config.get("gcp") or {}
    bigquery = config.get("bigquery") or {}
    if not gcp.get("project_id"):
        raise ValueError(f"Missing gcp.project_id in environment config: {config_path}")
    if not bigquery.get("dataset"):
        raise ValueError(f"Missing bigquery.dataset in environment config: {config_path}")
    return config


def _normalize_csv_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped != "" else None


def _convert_field_value(field_name: str, value: Optional[str]) -> Any:
    if value is None:
        return None
    if field_name in FLOAT_FIELDS:
        return float(value)
    if field_name in DATE_FIELDS:
        return value
    return value


def load_csv_rows(
    csv_path: str | Path,
    *,
    config: TableLoadConfig,
    expected_person_id: str,
    expected_document_id: str,
) -> List[Dict[str, Any]]:
    path = Path(csv_path)
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"{config.table_name} CSV has no header row: {path}")

        missing_headers = [field for field in config.fieldnames if field not in reader.fieldnames]
        if missing_headers:
            raise ValueError(
                f"{config.table_name} CSV is missing required headers {missing_headers}: {path}"
            )

        rows: List[Dict[str, Any]] = []
        for row_index, raw_row in enumerate(reader, start=2):
            row: Dict[str, Any] = {}
            for field in config.fieldnames:
                normalized_value = _normalize_csv_value(raw_row.get(field))
                row[field] = _convert_field_value(field, normalized_value)

            for field in config.required_fields:
                if row.get(field) in (None, ""):
                    raise ValueError(
                        f"{config.table_name} CSV row {row_index} is missing required field '{field}'."
                    )

            row_person_id = row.get("person_id")
            row_document_id = row.get("document_id")
            if row_person_id != expected_person_id:
                raise ValueError(
                    f"{config.table_name} CSV row {row_index} has person_id '{row_person_id}', expected '{expected_person_id}'."
                )
            if row_document_id and row_document_id != expected_document_id:
                raise ValueError(
                    f"{config.table_name} CSV row {row_index} has document_id '{row_document_id}', expected '{expected_document_id}'."
                )

            rows.append(row)
    return rows


def create_bigquery_client(project_id: str):
    try:
        from google.cloud import bigquery  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-bigquery is required for BigQuery loading. Install the bigquery extra before running this CLI."
        ) from exc

    try:
        return bigquery.Client(project=project_id)
    except Exception as exc:
        raise RuntimeError(
            "Failed to create BigQuery client using Google Application Default Credentials. "
            "Run `gcloud auth application-default login` and retry. "
            f"The loader always uses project_id='{project_id}' from the environment config."
        ) from exc


def _default_query_job_config_factory(document_id: str, person_id: str):
    try:
        from google.cloud import bigquery  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-bigquery is required for BigQuery loading. Install the bigquery extra before running this CLI."
        ) from exc

    return bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("document_id", "STRING", document_id),
            bigquery.ScalarQueryParameter("person_id", "STRING", person_id),
        ]
    )


def delete_existing_rows(
    client: Any,
    *,
    project_id: str,
    dataset: str,
    table_name: str,
    document_id: str,
    person_id: str,
    query_job_config_factory: Optional[Callable[[str, str], Any]] = None,
) -> None:
    table_id = f"`{project_id}.{dataset}.{table_name}`"
    query = (
        f"DELETE FROM {table_id} "
        "WHERE document_id = @document_id AND person_id = @person_id"
    )
    config_factory = query_job_config_factory or _default_query_job_config_factory
    query_job = client.query(
        query,
        job_config=config_factory(document_id, person_id),
    )
    query_job.result()


def insert_rows(
    client: Any,
    *,
    project_id: str,
    dataset: str,
    table_name: str,
    rows: Sequence[Dict[str, Any]],
) -> None:
    if not rows:
        return
    table_id = f"{project_id}.{dataset}.{table_name}"
    errors = client.insert_rows_json(table_id, list(rows))
    if errors:
        raise RuntimeError(f"BigQuery insert failed for {table_name}: {errors}")


def load_extracted_csvs_to_bigquery(
    *,
    environment_config_path: str | Path,
    observations_csv_path: str | Path,
    health_metrics_csv_path: str | Path,
    document_id: str,
    person_id: str,
    replace_existing: bool,
    client: Optional[Any] = None,
    query_job_config_factory: Optional[Callable[[str, str], Any]] = None,
) -> Dict[str, Any]:
    environment_config = load_environment_config(environment_config_path)
    project_id = environment_config["gcp"]["project_id"]
    dataset = environment_config["bigquery"]["dataset"]
    bigquery_client = client or create_bigquery_client(project_id)

    observation_rows = load_csv_rows(
        observations_csv_path,
        config=TableLoadConfig(
            table_name="observation",
            fieldnames=OBSERVATION_FIELDS,
            required_fields=OBSERVATION_REQUIRED_FIELDS,
        ),
        expected_person_id=person_id,
        expected_document_id=document_id,
    )
    health_metric_rows = load_csv_rows(
        health_metrics_csv_path,
        config=TableLoadConfig(
            table_name="health_metric",
            fieldnames=HEALTH_METRIC_FIELDS,
            required_fields=HEALTH_METRIC_REQUIRED_FIELDS,
        ),
        expected_person_id=person_id,
        expected_document_id=document_id,
    )

    if replace_existing:
        delete_existing_rows(
            bigquery_client,
            project_id=project_id,
            dataset=dataset,
            table_name="health_metric",
            document_id=document_id,
            person_id=person_id,
            query_job_config_factory=query_job_config_factory,
        )
        delete_existing_rows(
            bigquery_client,
            project_id=project_id,
            dataset=dataset,
            table_name="observation",
            document_id=document_id,
            person_id=person_id,
            query_job_config_factory=query_job_config_factory,
        )

    insert_rows(
        bigquery_client,
        project_id=project_id,
        dataset=dataset,
        table_name="observation",
        rows=observation_rows,
    )
    insert_rows(
        bigquery_client,
        project_id=project_id,
        dataset=dataset,
        table_name="health_metric",
        rows=health_metric_rows,
    )

    return {
        "project_id": project_id,
        "dataset": dataset,
        "observations_loaded": len(observation_rows),
        "health_metrics_loaded": len(health_metric_rows),
        "replace_existing": replace_existing,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    load_extracted_csvs_to_bigquery(
        environment_config_path=args.environment_config,
        observations_csv_path=args.observations_csv,
        health_metrics_csv_path=args.health_metrics_csv,
        document_id=args.document_id,
        person_id=args.person_id,
        replace_existing=args.replace_existing,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

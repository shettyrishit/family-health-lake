from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from family_health_lake.utils import load_yaml_config, normalize_id_component


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


def load_environment_config(path: str | Path) -> Dict[str, Any]:
    config = load_yaml_config(path)
    gcp = config.get("gcp") or {}
    bigquery = config.get("bigquery") or {}
    if not gcp.get("project_id"):
        raise ValueError(f"Missing gcp.project_id in environment config: {path}")
    if not bigquery.get("dataset"):
        raise ValueError(f"Missing bigquery.dataset in environment config: {path}")
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
        try:
            return float(value)
        except ValueError:
            return None
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
            "google-cloud-bigquery is required for BigQuery operations. "
            "Install the local project extras with "
            "`python3 -m pip install -e \".[bigquery]\"` "
            "or use a virtual environment and install the same extra there."
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
            "google-cloud-bigquery is required for BigQuery operations. "
            "Install the local project extras with "
            "`python3 -m pip install -e \".[bigquery]\"` "
            "or use a virtual environment and install the same extra there."
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
    person_id: str,
    document_id: str,
) -> None:
    if not rows:
        return
    
    # BigQuery streaming inserts (insert_rows_json) can block DELETE during dev.
    # We switch to batch load using staging table + INSERT SELECT.
    
    safe_doc_id = normalize_id_component(document_id)
    staging_table_name = f"stg_{table_name}_{person_id}_{safe_doc_id}"
    staging_table_id = f"{project_id}.{dataset}.{staging_table_name}"
    final_table_id = f"{project_id}.{dataset}.{table_name}"
    
    from google.cloud import bigquery
    
    # 1. Load to staging table using batch load
    # We use WRITE_TRUNCATE to ensure staging is clean
    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    )
    
    # We need to use JSON load because we already have the rows as dicts
    # Alternatively, we could load from the CSV file directly, but load_csv_rows 
    # already did some validation and conversion.
    # To avoid streaming buffer, we use load_table_from_json
    load_job = client.load_table_from_json(list(rows), staging_table_id, job_config=job_config)
    load_job.result()
    
    # 2. Insert from staging into final using query job (DML)
    # This avoids the streaming buffer issue
    columns = ", ".join(rows[0].keys())
    query = f"INSERT INTO `{final_table_id}` ({columns}) SELECT {columns} FROM `{staging_table_id}`"
    
    query_job = client.query(query)
    query_job.result()
    
    # 3. Drop staging table
    client.delete_table(staging_table_id, not_found_ok=True)


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
        # Delete order: health_metric then observation
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

    # Insert order: observation then health_metric
    insert_rows(
        bigquery_client,
        project_id=project_id,
        dataset=dataset,
        table_name="observation",
        rows=observation_rows,
        person_id=person_id,
        document_id=document_id,
    )
    insert_rows(
        bigquery_client,
        project_id=project_id,
        dataset=dataset,
        table_name="health_metric",
        rows=health_metric_rows,
        person_id=person_id,
        document_id=document_id,
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
    try:
        load_extracted_csvs_to_bigquery(
            environment_config_path=args.environment_config,
            observations_csv_path=args.observations_csv,
            health_metrics_csv_path=args.health_metrics_csv,
            document_id=args.document_id,
            person_id=args.person_id,
            replace_existing=args.replace_existing,
        )
    except RuntimeError as exc:
        parser.exit(status=2, message=f"error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

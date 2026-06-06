import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add src to sys.path
REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from family_health_lake.utils import load_yaml_config

# Modes and their associated tables in deletion order
MODES = {
    "generated": [
        "insight",
        "alert",
        "metric_trend",
        "health_metric",
        "observation",
    ],
    "full-person": [
        "insight",
        "alert",
        "metric_trend",
        "health_metric",
        "observation",
        "source_document",
        "person",
    ],
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scrub BigQuery data for a specific person_id."
    )
    parser.add_argument(
        "--environment-config",
        required=True,
        help="Path to the environment config YAML file.",
    )
    parser.add_argument(
        "--person-id",
        required=True,
        help="The person_id to scrub data for.",
    )
    parser.add_argument(
        "--mode",
        choices=list(MODES.keys()),
        default="generated",
        help="Cleanup mode. 'generated' (default) deletes derived data. 'full-person' deletes everything.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually execute the deletions. If not passed, it's a dry run.",
    )
    parser.add_argument(
        "--confirm-person-id",
        help="Must match --person-id if --execute is passed.",
    )
    return parser


def get_bq_client(project_id: str) -> Any:
    from google.cloud import bigquery
    return bigquery.Client(project=project_id)


def scrub_person_data(
    *,
    config_path: str,
    person_id: str,
    mode: str,
    execute: bool,
    confirm_person_id: Optional[str],
    client: Optional[Any] = None,
) -> int:
    print(f"Mode: {mode}")
    
    if execute:
        if not confirm_person_id:
            print("Error: --confirm-person-id is required when --execute is passed.")
            return 1
        if confirm_person_id != person_id:
            print(f"Error: --confirm-person-id '{confirm_person_id}' does not match --person-id '{person_id}'.")
            return 1

    config = load_yaml_config(config_path)
    project_id = config.get("gcp", {}).get("project_id")
    dataset = config.get("bigquery", {}).get("dataset")

    if not project_id or not dataset:
        print(f"Error: project_id or dataset not found in {config_path}")
        return 1

    if client is None:
        client = get_bq_client(project_id)

    tables = MODES[mode]
    summary = []

    for table_name in tables:
        full_table_id = f"{project_id}.{dataset}.{table_name}"
        
        # Get count first
        count_query = f"SELECT COUNT(*) as cnt FROM `{full_table_id}` WHERE person_id = @person_id"
        from google.cloud import bigquery
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("person_id", "STRING", person_id),
            ]
        )
        
        query_job = client.query(count_query, job_config=job_config)
        results = list(query_job.result())
        count = results[0].cnt if results else 0
        
        print(f"Table {table_name}: {count} rows would be deleted" if not execute else f"Table {table_name}: deleting {count} rows")
        
        if execute and count > 0:
            delete_query = f"DELETE FROM `{full_table_id}` WHERE person_id = @person_id"
            delete_job = client.query(delete_query, job_config=job_config)
            delete_job.result()
            summary.append((table_name, count))
        elif not execute:
            summary.append((table_name, count))

    print("\n--- Summary ---")
    if execute:
        if not summary:
            print("No rows were deleted.")
        for table, count in summary:
            print(f"Deleted {count} rows from {table}")
    else:
        print("Dry run completed. No data was deleted.")
        for table, count in summary:
            print(f"Would delete {count} rows from {table}")
            
    return 0


def main():
    parser = build_parser()
    args = parser.parse_args()
    
    try:
        sys.exit(scrub_person_data(
            config_path=args.environment_config,
            person_id=args.person_id,
            mode=args.mode,
            execute=args.execute,
            confirm_person_id=args.confirm_person_id
        ))
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

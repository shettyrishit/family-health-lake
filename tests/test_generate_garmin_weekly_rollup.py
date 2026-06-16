import csv
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from family_health_lake.synthesis.garmin_weekly_rollup import (
    build_garmin_weekly_rollup_rows,
    generate_garmin_weekly_rollup,
    load_weekly_metric_mappings,
    week_start_monday,
)


ENVIRONMENT_CONFIG_PATH = REPO_ROOT / "config" / "environments" / "dev.yaml"
MAPPING_PATH = (
    REPO_ROOT
    / "config"
    / "metric_mappings"
    / "garmin_weekly_rollup_metrics.yaml"
)


class FakeQueryJob:
    def __init__(self, rows=None):
        self._rows = list(rows or [])

    def result(self):
        return self._rows


class FakeBigQueryClient:
    def __init__(self, source_rows, *, view_exists=True):
        self.source_rows = list(source_rows)
        self.view_exists = view_exists
        self.queries = []
        self.load_calls = []
        self.deleted_tables = []

    def query(self, query, job_config=None):
        self.queries.append({"query": query, "job_config": job_config})
        if "INFORMATION_SCHEMA.TABLES" in query:
            return FakeQueryJob([{"cnt": 1 if self.view_exists else 0}])
        if f"FROM `project-b01843b0-70b0-47d0-af0.health_os.v_garmin_daily_metrics`" in query:
            return FakeQueryJob(self.source_rows)
        if "FROM `project-b01843b0-70b0-47d0-af0.health_os.health_metric` hm" in query:
            return FakeQueryJob(self.source_rows)
        return FakeQueryJob()

    def load_table_from_json(self, rows, table_id, job_config=None):
        self.load_calls.append({"table_id": table_id, "rows": list(rows), "job_config": job_config})
        return FakeQueryJob()

    def delete_table(self, table_id, not_found_ok=False):
        self.deleted_tables.append(table_id)

    def insert_rows_json(self, table_id, rows):
        raise AssertionError("Garmin weekly rollup should not use streaming inserts.")


def fake_view_exists_query_job_config_factory(table_name):
    return {"table_name": table_name}


def fake_metrics_query_job_config_factory(person_id, start_date, end_date, source):
    return {
        "person_id": person_id,
        "start_date": start_date,
        "end_date": end_date,
        "source": source,
    }


def fake_delete_query_job_config_factory(person_id, week_start_dates, source):
    return {
        "person_id": person_id,
        "week_start_dates": list(week_start_dates),
        "source": source,
    }


def fake_source_rows():
    return [
        {
            "metric_id": "m_p001_2026-06-02_steps",
            "observation_id": "obs_p001_2026-06-02_steps",
            "person_id": "p001",
            "document_id": "doc_daily_1",
            "metric_date": "2026-06-02",
            "source": "garmin_connect_raw_json",
            "category": "training_activity",
            "metric_name": "Steps",
            "value": 10000.0,
            "unit": "steps/day",
            "observation_type": "daily_metric",
            "source_location": "file=daily_1.json",
            "notes": "",
            "raw_text": "",
        },
        {
            "metric_id": "m_p001_2026-06-03_steps",
            "observation_id": "obs_p001_2026-06-03_steps",
            "person_id": "p001",
            "document_id": "doc_daily_2",
            "metric_date": "2026-06-03",
            "source": "garmin_connect_raw_json",
            "category": "training_activity",
            "metric_name": "Steps",
            "value": 12000.0,
            "unit": "steps/day",
            "observation_type": "daily_metric",
            "source_location": "file=daily_2.json",
            "notes": "",
            "raw_text": "",
        },
        {
            "metric_id": "m_p001_2026-06-02_resting_hr",
            "observation_id": "obs_p001_2026-06-02_resting_hr",
            "person_id": "p001",
            "document_id": "doc_daily_3",
            "metric_date": "2026-06-02",
            "source": "garmin_connect_raw_json",
            "category": "recovery_sleep",
            "metric_name": "Resting HR",
            "value": 50.0,
            "unit": "bpm",
            "observation_type": "daily_metric",
            "source_location": "file=rhr_1.json",
            "notes": "",
            "raw_text": "",
        },
        {
            "metric_id": "m_p001_2026-06-03_resting_hr",
            "observation_id": "obs_p001_2026-06-03_resting_hr",
            "person_id": "p001",
            "document_id": "doc_daily_4",
            "metric_date": "2026-06-03",
            "source": "garmin_connect_raw_json",
            "category": "recovery_sleep",
            "metric_name": "Resting HR",
            "value": 54.0,
            "unit": "bpm",
            "observation_type": "daily_metric",
            "source_location": "file=rhr_2.json",
            "notes": "",
            "raw_text": "",
        },
        {
            "metric_id": "m_p001_2026-06-04_sleep_minutes",
            "observation_id": "obs_p001_2026-06-04_sleep_minutes",
            "person_id": "p001",
            "document_id": "doc_daily_5",
            "metric_date": "2026-06-04",
            "source": "garmin_connect_raw_json",
            "category": "recovery_sleep",
            "metric_name": "Sleep",
            "value": 420.0,
            "unit": "minutes/day",
            "observation_type": "daily_metric",
            "source_location": "file=sleep_1.json",
            "notes": "",
            "raw_text": "",
        },
        {
            "metric_id": "m_p001_2026-06-05_sleep_minutes",
            "observation_id": "obs_p001_2026-06-05_sleep_minutes",
            "person_id": "p001",
            "document_id": "doc_daily_6",
            "metric_date": "2026-06-05",
            "source": "garmin_connect_raw_json",
            "category": "recovery_sleep",
            "metric_name": "Sleep",
            "value": 480.0,
            "unit": "minutes/day",
            "observation_type": "daily_metric",
            "source_location": "file=sleep_2.json",
            "notes": "",
            "raw_text": "",
        },
        {
            "metric_id": "m_p001_2026-06-04_activity_duration_minutes",
            "observation_id": "obs_p001_2026-06-04_a1_activity_duration_minutes",
            "person_id": "p001",
            "document_id": "doc_activity_1",
            "metric_date": "2026-06-04",
            "source": "garmin_connect_raw_json",
            "category": "training_activity",
            "metric_name": "Activity Duration",
            "value": 30.0,
            "unit": "minutes",
            "observation_type": "activity",
            "source_location": "file=activity_1.json",
            "notes": "",
            "raw_text": "",
        },
        {
            "metric_id": "m_p001_2026-06-04_activity_distance_km",
            "observation_id": "obs_p001_2026-06-04_a1_activity_distance_km",
            "person_id": "p001",
            "document_id": "doc_activity_1",
            "metric_date": "2026-06-04",
            "source": "garmin_connect_raw_json",
            "category": "training_activity",
            "metric_name": "Activity Distance",
            "value": 5.0,
            "unit": "km",
            "observation_type": "activity",
            "source_location": "file=activity_1.json",
            "notes": "",
            "raw_text": "",
        },
        {
            "metric_id": "m_p001_2026-06-05_activity_duration_minutes",
            "observation_id": "obs_p001_2026-06-05_a2_activity_duration_minutes",
            "person_id": "p001",
            "document_id": "doc_activity_2",
            "metric_date": "2026-06-05",
            "source": "garmin_connect_raw_json",
            "category": "training_activity",
            "metric_name": "Activity Duration",
            "value": 45.0,
            "unit": "minutes",
            "observation_type": "activity",
            "source_location": "file=activity_2.json",
            "notes": "",
            "raw_text": "",
        },
    ]


class GarminWeeklyRollupTests(unittest.TestCase):
    def test_monday_week_start_calculation(self):
        self.assertEqual("2026-06-01", week_start_monday("2026-06-01"))
        self.assertEqual("2026-06-01", week_start_monday("2026-06-03"))
        self.assertEqual("2026-06-01", week_start_monday("2026-06-07"))

    def test_build_weekly_rollups_aggregates_expected_metrics(self):
        mappings = load_weekly_metric_mappings(MAPPING_PATH)
        rows = build_garmin_weekly_rollup_rows(
            fake_source_rows(),
            person_id="p001",
            mappings=mappings,
        )

        observations = rows["observations"]
        health_metrics = rows["health_metrics"]
        self.assertEqual(6, len(observations))
        self.assertEqual(6, len(health_metrics))

        metric_by_name = {row["metric_name"]: row for row in health_metrics}
        self.assertEqual(11000.0, metric_by_name["Average Steps"]["value"])
        self.assertEqual(52.0, metric_by_name["Average Resting HR"]["value"])
        self.assertEqual(450.0, metric_by_name["Average Sleep"]["value"])
        self.assertEqual(2.0, metric_by_name["Activity Count"]["value"])
        self.assertEqual(75.0, metric_by_name["Total Activity Duration"]["value"])
        self.assertEqual(5.0, metric_by_name["Total Activity Distance"]["value"])
        self.assertNotIn("Average HRV", metric_by_name)

    def test_weekly_rollup_ids_are_deterministic_and_traceable(self):
        mappings = load_weekly_metric_mappings(MAPPING_PATH)
        rows = build_garmin_weekly_rollup_rows(
            fake_source_rows(),
            person_id="p001",
            mappings=mappings,
        )

        observation_ids = {row["observation_id"] for row in rows["observations"]}
        self.assertIn(
            "obs_p001_2026-06-01_steps_avg_weekly_rollup",
            observation_ids,
        )
        metric_by_name = {row["metric_name"]: row for row in rows["health_metrics"]}
        self.assertEqual(
            "m_p001_2026-06-01_steps_avg_weekly_rollup",
            metric_by_name["Average Steps"]["metric_id"],
        )
        for metric in rows["health_metrics"]:
            self.assertIn(metric["observation_id"], observation_ids)

    def test_generate_rollup_prefers_view_when_present(self):
        client = FakeBigQueryClient(fake_source_rows(), view_exists=True)
        with TemporaryDirectory() as temp_dir:
            result = generate_garmin_weekly_rollup(
                environment_config_path=ENVIRONMENT_CONFIG_PATH,
                person_id="p001",
                start_date="2026-06-01",
                end_date="2026-06-07",
                output_observations_csv_path=Path(temp_dir) / "observations.csv",
                output_health_metrics_csv_path=Path(temp_dir) / "health_metric.csv",
                load_to_bigquery=False,
                replace_existing=False,
                client=client,
                view_exists_query_job_config_factory=fake_view_exists_query_job_config_factory,
                metrics_query_job_config_factory=fake_metrics_query_job_config_factory,
            )

        self.assertEqual(9, result["source_rows_read"])
        self.assertIn("INFORMATION_SCHEMA.TABLES", client.queries[0]["query"])
        self.assertIn(
            "FROM `project-b01843b0-70b0-47d0-af0.health_os.v_garmin_daily_metrics`",
            client.queries[1]["query"],
        )

    def test_generate_rollup_falls_back_to_join_when_view_missing(self):
        client = FakeBigQueryClient(fake_source_rows(), view_exists=False)
        with TemporaryDirectory() as temp_dir:
            generate_garmin_weekly_rollup(
                environment_config_path=ENVIRONMENT_CONFIG_PATH,
                person_id="p001",
                start_date="2026-06-01",
                end_date="2026-06-07",
                output_observations_csv_path=Path(temp_dir) / "observations.csv",
                output_health_metrics_csv_path=Path(temp_dir) / "health_metric.csv",
                load_to_bigquery=False,
                replace_existing=False,
                client=client,
                view_exists_query_job_config_factory=fake_view_exists_query_job_config_factory,
                metrics_query_job_config_factory=fake_metrics_query_job_config_factory,
            )

        self.assertIn(
            "FROM `project-b01843b0-70b0-47d0-af0.health_os.health_metric` hm",
            client.queries[1]["query"],
        )

    def test_load_to_bigquery_uses_non_streaming_batch_path(self):
        client = FakeBigQueryClient(fake_source_rows(), view_exists=True)
        with TemporaryDirectory() as temp_dir:
            observation_path = Path(temp_dir) / "observations.csv"
            health_metric_path = Path(temp_dir) / "health_metric.csv"
            result = generate_garmin_weekly_rollup(
                environment_config_path=ENVIRONMENT_CONFIG_PATH,
                person_id="p001",
                start_date="2026-06-01",
                end_date="2026-06-07",
                output_observations_csv_path=observation_path,
                output_health_metrics_csv_path=health_metric_path,
                load_to_bigquery=True,
                replace_existing=True,
                client=client,
                view_exists_query_job_config_factory=fake_view_exists_query_job_config_factory,
                metrics_query_job_config_factory=fake_metrics_query_job_config_factory,
                delete_query_job_config_factory=fake_delete_query_job_config_factory,
            )

            with observation_path.open("r", encoding="utf-8", newline="") as handle:
                observation_rows = list(csv.DictReader(handle))
            with health_metric_path.open("r", encoding="utf-8", newline="") as handle:
                health_metric_rows = list(csv.DictReader(handle))

        self.assertEqual(6, len(observation_rows))
        self.assertEqual(6, len(health_metric_rows))
        self.assertEqual(2, len(client.load_calls))
        self.assertEqual(2, len(client.deleted_tables))
        self.assertIn(
            "DELETE FROM `project-b01843b0-70b0-47d0-af0.health_os.health_metric`",
            client.queries[2]["query"],
        )
        self.assertIn(
            "DELETE FROM `project-b01843b0-70b0-47d0-af0.health_os.observation`",
            client.queries[3]["query"],
        )
        insert_queries = [entry["query"] for entry in client.queries if entry["query"].startswith("INSERT INTO `project-b01843b0-70b0-47d0-af0.health_os.")]
        self.assertEqual(2, len(insert_queries))
        self.assertTrue(result["load_to_bigquery"])


if __name__ == "__main__":
    unittest.main()

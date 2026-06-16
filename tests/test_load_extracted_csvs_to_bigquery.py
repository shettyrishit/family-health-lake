import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from family_health_lake.ingestion.bigquery_csv_loader import (
    HEALTH_METRIC_FIELDS,
    OBSERVATION_FIELDS,
    load_csv_rows,
    load_extracted_csvs_to_bigquery,
)


OBSERVATIONS_FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "observations_loader_fake.csv"
)
HEALTH_METRICS_FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "health_metrics_loader_fake.csv"
)
ENVIRONMENT_CONFIG_PATH = REPO_ROOT / "config" / "environments" / "dev.yaml"


class FakeQueryJob:
    def result(self):
        return None


class FakeBigQueryClient:
    def __init__(self):
        self.queries = []
        self.load_calls = []
        self.deleted_tables = []

    def query(self, query, job_config=None):
        self.queries.append({"query": query, "job_config": job_config})
        return FakeQueryJob()

    def load_table_from_json(self, rows, table_id, job_config=None):
        self.load_calls.append({"table_id": table_id, "rows": rows, "job_config": job_config})
        return FakeQueryJob()

    def delete_table(self, table_id, not_found_ok=False):
        self.deleted_tables.append(table_id)


def fake_query_job_config_factory(document_id, person_id):
    return {
        "document_id": document_id,
        "person_id": person_id,
    }


class LoadExtractedCsvsToBigQueryTests(unittest.TestCase):
    def test_load_csv_rows_uses_header_names_not_column_order(self):
        observation_rows = load_csv_rows(
            OBSERVATIONS_FIXTURE_PATH,
            config=type(
                "Config",
                (),
                {
                    "table_name": "observation",
                    "fieldnames": OBSERVATION_FIELDS,
                    "required_fields": {"observation_id", "person_id"},
                },
            )(),
            expected_person_id="p001",
            expected_document_id="doc_p001_lab_2026_04_25_tata_1mg_fake",
        )
        metric_rows = load_csv_rows(
            HEALTH_METRICS_FIXTURE_PATH,
            config=type(
                "Config",
                (),
                {
                    "table_name": "health_metric",
                    "fieldnames": HEALTH_METRIC_FIELDS,
                    "required_fields": {"metric_id", "person_id", "observation_id", "metric_date", "metric_name"},
                },
            )(),
            expected_person_id="p001",
            expected_document_id="doc_p001_lab_2026_04_25_tata_1mg_fake",
        )

        self.assertEqual(2, len(observation_rows))
        self.assertEqual("obs_p001_2026-04-25_tsh", observation_rows[0]["observation_id"])
        self.assertEqual(1, len(metric_rows))
        self.assertEqual("TSH", metric_rows[0]["metric_name"])
        self.assertEqual(6.264, metric_rows[0]["value"])

    def test_replace_existing_deletes_then_inserts(self):
        client = FakeBigQueryClient()

        result = load_extracted_csvs_to_bigquery(
            environment_config_path=ENVIRONMENT_CONFIG_PATH,
            observations_csv_path=OBSERVATIONS_FIXTURE_PATH,
            health_metrics_csv_path=HEALTH_METRICS_FIXTURE_PATH,
            document_id="doc_p001_lab_2026_04_25_tata_1mg_fake",
            person_id="p001",
            replace_existing=True,
            client=client,
            query_job_config_factory=fake_query_job_config_factory,
        )

        # 2 DELETE queries + 2 INSERT SELECT queries = 4
        self.assertEqual(4, len(client.queries))
        self.assertIn("DELETE FROM `project-b01843b0-70b0-47d0-af0.health_os.health_metric`", client.queries[0]["query"])
        self.assertIn("DELETE FROM `project-b01843b0-70b0-47d0-af0.health_os.observation`", client.queries[1]["query"])
        
        # INSERT SELECTs
        self.assertIn("INSERT INTO `project-b01843b0-70b0-47d0-af0.health_os.observation`", client.queries[2]["query"])
        self.assertIn("INSERT INTO `project-b01843b0-70b0-47d0-af0.health_os.health_metric`", client.queries[3]["query"])

        self.assertEqual(2, len(client.load_calls))
        self.assertIn("stg_observation_p001_doc_p001_lab_2026_04_25_tata_1mg_fake", client.load_calls[0]["table_id"])
        self.assertIn("stg_health_metric_p001_doc_p001_lab_2026_04_25_tata_1mg_fake", client.load_calls[1]["table_id"])
        
        self.assertEqual(2, len(client.deleted_tables))
        self.assertIn("stg_observation_p001_doc_p001_lab_2026_04_25_tata_1mg_fake", client.deleted_tables[0])
        self.assertIn("stg_health_metric_p001_doc_p001_lab_2026_04_25_tata_1mg_fake", client.deleted_tables[1])

        observation_schema = client.load_calls[0]["job_config"].schema
        metric_schema = client.load_calls[1]["job_config"].schema
        observation_field_types = {field.name: field.field_type for field in observation_schema}
        metric_field_types = {field.name: field.field_type for field in metric_schema}
        self.assertEqual("DATE", observation_field_types["observed_at"])
        self.assertIn(observation_field_types["parsed_value"], {"FLOAT", "FLOAT64"})
        self.assertEqual("DATE", metric_field_types["metric_date"])
        self.assertIn(metric_field_types["reference_low"], {"FLOAT", "FLOAT64"})
        self.assertIn(metric_field_types["reference_high"], {"FLOAT", "FLOAT64"})
        
        self.assertEqual(2, result["observations_loaded"])
        self.assertEqual(1, result["health_metrics_loaded"])

    def test_missing_required_field_raises_clear_error(self):
        with TemporaryDirectory() as temp_dir:
            bad_metrics_csv = Path(temp_dir) / "bad_health_metric.csv"
            bad_metrics_csv.write_text(
                "metric_name,person_id,document_id,observation_id,metric_date,source,category,value,text_value,unit,reference_low,reference_high,status,notes\n"
                "TSH,p001,doc_p001_lab_2026_04_25_tata_1mg_fake,obs_p001_2026-04-25_tsh,2026-04-25,tata_1mg,thyroid,6.264,,µIU/mL,0.35,4.94,high,reference_range=0.35 - 4.94\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "missing required headers"):
                load_extracted_csvs_to_bigquery(
                    environment_config_path=ENVIRONMENT_CONFIG_PATH,
                    observations_csv_path=OBSERVATIONS_FIXTURE_PATH,
                    health_metrics_csv_path=bad_metrics_csv,
                    document_id="doc_p001_lab_2026_04_25_tata_1mg_fake",
                    person_id="p001",
                    replace_existing=False,
                    client=FakeBigQueryClient(),
                    query_job_config_factory=fake_query_job_config_factory,
                )


if __name__ == "__main__":
    unittest.main()

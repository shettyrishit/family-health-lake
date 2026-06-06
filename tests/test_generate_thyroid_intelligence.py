import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from family_health_lake.synthesis.thyroid_intelligence import (
    HealthMetricRecord,
    build_thyroid_intelligence_rows,
    generate_thyroid_intelligence,
)


ENVIRONMENT_CONFIG_PATH = REPO_ROOT / "config" / "environments" / "dev.yaml"


class FakeQueryJob:
    def __init__(self, rows=None):
        self._rows = list(rows or [])

    def result(self):
        return self._rows


class FakeBigQueryClient:
    def __init__(self, metric_rows, *, existing_rows_by_table=None, delete_errors_by_table=None):
        self.metric_rows = list(metric_rows)
        self.existing_rows_by_table = existing_rows_by_table or {}
        self.delete_errors_by_table = delete_errors_by_table or {}
        self.queries = []
        self.insert_calls = []

    def query(self, query, job_config=None):
        self.queries.append({"query": query, "job_config": job_config})
        if "FROM `project-b01843b0-70b0-47d0-af0.health_os.health_metric`" in query:
            return FakeQueryJob(self.metric_rows)
        for table_name in ("metric_trend", "alert", "insight"):
            table_ref = f"`project-b01843b0-70b0-47d0-af0.health_os.{table_name}`"
            if f"DELETE FROM {table_ref}" in query:
                error = self.delete_errors_by_table.get(table_name)
                if error is not None:
                    raise error
                return FakeQueryJob()
            if f"FROM {table_ref}" in query:
                return FakeQueryJob(self.existing_rows_by_table.get(table_name, []))
        return FakeQueryJob()

    def insert_rows_json(self, table_id, rows):
        self.insert_calls.append({"table_id": table_id, "rows": rows})
        return []


def fake_metric_query_job_config_factory(person_id, document_id, metric_names):
    return {
        "person_id": person_id,
        "document_id": document_id,
        "metric_names": list(metric_names),
    }


def fake_delete_query_job_config_factory(document_id, person_id):
    return {
        "document_id": document_id,
        "person_id": person_id,
    }


def fake_existing_row_query_job_config_factory(row_ids):
    return {
        "row_ids": list(row_ids),
    }


class ThyroidIntelligenceTests(unittest.TestCase):
    def test_build_rows_for_high_tsh_creates_trend_alert_and_insight(self):
        rows = build_thyroid_intelligence_rows(
            [
                HealthMetricRecord(
                    metric_id="m_p001_2026-04-25_tsh",
                    person_id="p001",
                    document_id="doc_p001_lab_2026_04_25_tata_1mg_fake",
                    metric_date="2026-04-25",
                    category="thyroid",
                    metric_name="TSH",
                    status="high",
                ),
                HealthMetricRecord(
                    metric_id="m_p001_2026-04-25_free_t4",
                    person_id="p001",
                    document_id="doc_p001_lab_2026_04_25_tata_1mg_fake",
                    metric_date="2026-04-25",
                    category="thyroid",
                    metric_name="Free T4",
                    status="normal",
                ),
                HealthMetricRecord(
                    metric_id="m_p001_2026-04-25_free_t3",
                    person_id="p001",
                    document_id="doc_p001_lab_2026_04_25_tata_1mg_fake",
                    metric_date="2026-04-25",
                    category="thyroid",
                    metric_name="Free T3",
                    status="normal",
                ),
                HealthMetricRecord(
                    metric_id="m_p001_2026-04-25_anti_tpo_antibody",
                    person_id="p001",
                    document_id="doc_p001_lab_2026_04_25_tata_1mg_fake",
                    metric_date="2026-04-25",
                    category="thyroid",
                    metric_name="Anti-TPO Antibody",
                    status="normal",
                ),
            ],
            person_id="p001",
            document_id="doc_p001_lab_2026_04_25_tata_1mg_fake",
        )

        self.assertEqual(1, len(rows["metric_trend_rows"]))
        self.assertEqual(1, len(rows["alert_rows"]))
        self.assertEqual(1, len(rows["insight_rows"]))

        trend = rows["metric_trend_rows"][0]
        alert = rows["alert_rows"][0]
        insight = rows["insight_rows"][0]

        self.assertEqual("above_reference", trend["trend_status"])
        self.assertEqual(
            "TSH is above reference range on the latest available test.",
            trend["trend_summary"],
        )
        self.assertEqual(["m_p001_2026-04-25_tsh"], trend["related_metric_ids"])
        self.assertEqual(
            [
                "m_p001_2026-04-25_tsh",
                "m_p001_2026-04-25_free_t4",
                "m_p001_2026-04-25_free_t3",
            ],
            alert["related_metric_ids"],
        )
        self.assertEqual([trend["trend_id"]], alert["related_trend_ids"])
        self.assertEqual([alert["alert_id"]], insight["supporting_alert_ids"])
        self.assertEqual([trend["trend_id"]], insight["supporting_trend_ids"])
        self.assertEqual(
            [
                "m_p001_2026-04-25_tsh",
                "m_p001_2026-04-25_free_t4",
                "m_p001_2026-04-25_free_t3",
                "m_p001_2026-04-25_anti_tpo_antibody",
            ],
            insight["supporting_metric_ids"],
        )

    def test_build_rows_for_non_high_tsh_returns_no_rows(self):
        rows = build_thyroid_intelligence_rows(
            [
                HealthMetricRecord(
                    metric_id="m_p001_2026-04-25_tsh",
                    person_id="p001",
                    document_id="doc_p001_lab_2026_04_25_tata_1mg_fake",
                    metric_date="2026-04-25",
                    category="thyroid",
                    metric_name="TSH",
                    status="normal",
                )
            ],
            person_id="p001",
            document_id="doc_p001_lab_2026_04_25_tata_1mg_fake",
        )

        self.assertEqual([], rows["metric_trend_rows"])
        self.assertEqual([], rows["alert_rows"])
        self.assertEqual([], rows["insight_rows"])

    def test_generate_thyroid_intelligence_replaces_existing_then_inserts(self):
        metric_rows = [
            {
                "metric_id": "m_p001_2026-04-25_tsh",
                "person_id": "p001",
                "document_id": "doc_p001_lab_2026_04_25_tata_1mg_fake",
                "metric_date": "2026-04-25",
                "category": "thyroid",
                "metric_name": "TSH",
                "status": "high",
            },
            {
                "metric_id": "m_p001_2026-04-25_free_t4",
                "person_id": "p001",
                "document_id": "doc_p001_lab_2026_04_25_tata_1mg_fake",
                "metric_date": "2026-04-25",
                "category": "thyroid",
                "metric_name": "Free T4",
                "status": "normal",
            },
            {
                "metric_id": "m_p001_2026-04-25_free_t3",
                "person_id": "p001",
                "document_id": "doc_p001_lab_2026_04_25_tata_1mg_fake",
                "metric_date": "2026-04-25",
                "category": "thyroid",
                "metric_name": "Free T3",
                "status": "normal",
            },
        ]
        client = FakeBigQueryClient(metric_rows)

        result = generate_thyroid_intelligence(
            environment_config_path=ENVIRONMENT_CONFIG_PATH,
            person_id="p001",
            document_id="doc_p001_lab_2026_04_25_tata_1mg_fake",
            replace_existing=True,
            client=client,
            metric_query_job_config_factory=fake_metric_query_job_config_factory,
            delete_query_job_config_factory=fake_delete_query_job_config_factory,
        )

        self.assertEqual(4, len(client.queries))
        self.assertIn("FROM `project-b01843b0-70b0-47d0-af0.health_os.health_metric`", client.queries[0]["query"])
        self.assertIn("DELETE FROM `project-b01843b0-70b0-47d0-af0.health_os.metric_trend`", client.queries[1]["query"])
        self.assertIn("DELETE FROM `project-b01843b0-70b0-47d0-af0.health_os.alert`", client.queries[2]["query"])
        self.assertIn("DELETE FROM `project-b01843b0-70b0-47d0-af0.health_os.insight`", client.queries[3]["query"])
        self.assertEqual(
            {
                "person_id": "p001",
                "document_id": "doc_p001_lab_2026_04_25_tata_1mg_fake",
                "metric_names": [
                    "TSH",
                    "Free T4",
                    "Free T3",
                    "Total T3",
                    "Total T4",
                    "Anti-TPO Antibody",
                    "Anti-Tg Antibody",
                ],
            },
            client.queries[0]["job_config"],
        )
        self.assertEqual(
            {
                "document_id": "doc_p001_lab_2026_04_25_tata_1mg_fake",
                "person_id": "p001",
            },
            client.queries[1]["job_config"],
        )
        self.assertEqual(3, len(client.insert_calls))
        self.assertEqual("project-b01843b0-70b0-47d0-af0.health_os.metric_trend", client.insert_calls[0]["table_id"])
        self.assertEqual("project-b01843b0-70b0-47d0-af0.health_os.alert", client.insert_calls[1]["table_id"])
        self.assertEqual("project-b01843b0-70b0-47d0-af0.health_os.insight", client.insert_calls[2]["table_id"])
        self.assertEqual(3, result["health_metrics_read"])
        self.assertEqual(1, result["metric_trends_created"])
        self.assertEqual(1, result["alerts_created"])
        self.assertEqual(1, result["insights_created"])
        self.assertEqual(0, result["tables_already_synced"])

    def test_generate_thyroid_intelligence_skips_insert_when_streaming_buffer_rows_match(self):
        metric_rows = [
            {
                "metric_id": "m_p001_2026-04-25_tsh",
                "person_id": "p001",
                "document_id": "doc_p001_lab_2026_04_25_tata_1mg_fake",
                "metric_date": "2026-04-25",
                "category": "thyroid",
                "metric_name": "TSH",
                "status": "high",
            },
            {
                "metric_id": "m_p001_2026-04-25_free_t4",
                "person_id": "p001",
                "document_id": "doc_p001_lab_2026_04_25_tata_1mg_fake",
                "metric_date": "2026-04-25",
                "category": "thyroid",
                "metric_name": "Free T4",
                "status": "normal",
            },
            {
                "metric_id": "m_p001_2026-04-25_free_t3",
                "person_id": "p001",
                "document_id": "doc_p001_lab_2026_04_25_tata_1mg_fake",
                "metric_date": "2026-04-25",
                "category": "thyroid",
                "metric_name": "Free T3",
                "status": "normal",
            },
        ]
        expected_rows = build_thyroid_intelligence_rows(
            [
                HealthMetricRecord(**row) for row in metric_rows
            ],
            person_id="p001",
            document_id="doc_p001_lab_2026_04_25_tata_1mg_fake",
        )
        streaming_error = RuntimeError(
            "UPDATE or DELETE statement over table project.dataset.table would affect rows in the streaming buffer, which is not supported"
        )
        client = FakeBigQueryClient(
            metric_rows,
            existing_rows_by_table={
                "metric_trend": expected_rows["metric_trend_rows"],
                "alert": expected_rows["alert_rows"],
                "insight": expected_rows["insight_rows"],
            },
            delete_errors_by_table={
                "metric_trend": streaming_error,
                "alert": streaming_error,
                "insight": streaming_error,
            },
        )

        result = generate_thyroid_intelligence(
            environment_config_path=ENVIRONMENT_CONFIG_PATH,
            person_id="p001",
            document_id="doc_p001_lab_2026_04_25_tata_1mg_fake",
            replace_existing=True,
            client=client,
            metric_query_job_config_factory=fake_metric_query_job_config_factory,
            delete_query_job_config_factory=fake_delete_query_job_config_factory,
            existing_row_query_job_config_factory=fake_existing_row_query_job_config_factory,
        )

        self.assertEqual(7, len(client.queries))
        self.assertEqual(0, len(client.insert_calls))
        self.assertEqual(3, result["tables_already_synced"])

    def test_generate_thyroid_intelligence_raises_when_streaming_buffer_rows_do_not_match(self):
        metric_rows = [
            {
                "metric_id": "m_p001_2026-04-25_tsh",
                "person_id": "p001",
                "document_id": "doc_p001_lab_2026_04_25_tata_1mg_fake",
                "metric_date": "2026-04-25",
                "category": "thyroid",
                "metric_name": "TSH",
                "status": "high",
            },
            {
                "metric_id": "m_p001_2026-04-25_free_t4",
                "person_id": "p001",
                "document_id": "doc_p001_lab_2026_04_25_tata_1mg_fake",
                "metric_date": "2026-04-25",
                "category": "thyroid",
                "metric_name": "Free T4",
                "status": "normal",
            },
            {
                "metric_id": "m_p001_2026-04-25_free_t3",
                "person_id": "p001",
                "document_id": "doc_p001_lab_2026_04_25_tata_1mg_fake",
                "metric_date": "2026-04-25",
                "category": "thyroid",
                "metric_name": "Free T3",
                "status": "normal",
            },
        ]
        client = FakeBigQueryClient(
            metric_rows,
            existing_rows_by_table={"metric_trend": []},
            delete_errors_by_table={
                "metric_trend": RuntimeError(
                    "UPDATE or DELETE statement over table project.dataset.table would affect rows in the streaming buffer, which is not supported"
                )
            },
        )

        with self.assertRaisesRegex(RuntimeError, "Wait a few minutes and retry"):
            generate_thyroid_intelligence(
                environment_config_path=ENVIRONMENT_CONFIG_PATH,
                person_id="p001",
                document_id="doc_p001_lab_2026_04_25_tata_1mg_fake",
                replace_existing=True,
                client=client,
                metric_query_job_config_factory=fake_metric_query_job_config_factory,
                delete_query_job_config_factory=fake_delete_query_job_config_factory,
                existing_row_query_job_config_factory=fake_existing_row_query_job_config_factory,
            )


if __name__ == "__main__":
    unittest.main()

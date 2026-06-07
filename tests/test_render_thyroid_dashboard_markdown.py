import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from family_health_lake.dashboard.thyroid_markdown import (
    dedupe_metric_rows,
    render_thyroid_dashboard_markdown,
)


def make_card_row(**overrides):
    row = {
        "person_id": "p001",
        "insight_id": "insight_p001_doc_demo_thyroid_status",
        "insight_summary": "Thyroid is monitored but not fully optimized because TSH is above reference range while FT4 and FT3 are in range.",
        "insight_status": "active",
        "alert_id": "alert_p001_doc_demo_thyroid_tsh_above_reference",
        "alert_type": "metric_above_reference",
        "alert_message": "TSH is above reference range while FT4 and FT3 are in range.",
        "alert_severity": "monitor",
        "trend_id": "trend_p001_doc_demo_thyroid_tsh_above_reference",
        "trend_summary": "TSH is above reference range on the latest available test.",
        "trend_status": "above_reference",
        "document_id": "doc_demo",
        "file_uri": "gs://bucket/raw/doc_demo.pdf",
    }
    row.update(overrides)
    return row


def make_trace_row(**overrides):
    row = {
        "person_id": "p001",
        "insight_id": "insight_p001_doc_demo_thyroid_status",
        "alert_id": "alert_p001_doc_demo_thyroid_tsh_above_reference",
        "trend_id": "trend_p001_doc_demo_thyroid_tsh_above_reference",
        "metric_id": "m_p001_2026-04-25_tsh",
        "metric_name": "TSH",
        "value": 6.264,
        "text_value": "",
        "unit": "uIU/mL",
        "reference_low": 0.35,
        "reference_high": 4.94,
        "metric_status": "high",
        "observation_id": "obs_p001_2026-04-25_tsh",
        "raw_label": "TSH, Ultra Sensitive",
        "raw_value": "6.264",
        "normalized_label": "TSH",
        "source_location": "page=1 line=14",
        "document_id": "doc_demo",
        "file_uri": "gs://bucket/raw/doc_demo.pdf",
    }
    row.update(overrides)
    return row


class RenderThyroidDashboardMarkdownTests(unittest.TestCase):
    def test_renders_insight_section(self):
        markdown = render_thyroid_dashboard_markdown(
            [make_card_row()],
            [make_trace_row()],
            person_id="p001",
        )

        self.assertIn("# Thyroid Dashboard — p001", markdown)
        self.assertIn("## Insight Summary", markdown)
        self.assertIn("Thyroid is monitored but not fully optimized", markdown)
        self.assertNotIn("Coach Recommendation", markdown)

    def test_renders_metric_table(self):
        markdown = render_thyroid_dashboard_markdown(
            [make_card_row()],
            [
                make_trace_row(),
                make_trace_row(
                    metric_id="m_p001_2026-04-25_free_t4",
                    metric_name="Free T4",
                    value=1.2,
                    unit="ng/dL",
                    reference_low=0.89,
                    reference_high=1.76,
                    metric_status="normal",
                    observation_id="obs_p001_2026-04-25_free_t4",
                    raw_label="Free T4",
                    raw_value="1.20",
                    normalized_label="Free T4",
                    source_location="page=1 line=15",
                ),
            ],
            person_id="p001",
        )

        self.assertIn("## Key Metrics", markdown)
        self.assertIn("| Metric | Value | Unit | Reference Range | Status |", markdown)
        self.assertIn("| TSH | 6.264 | uIU/mL | 0.35 - 4.94 | high |", markdown)
        self.assertIn("| Free T4 | 1.2 | ng/dL | 0.89 - 1.76 | normal |", markdown)

    def test_renders_trace_section(self):
        markdown = render_thyroid_dashboard_markdown(
            [make_card_row()],
            [make_trace_row()],
            person_id="p001",
        )

        self.assertIn("## Trace", markdown)
        self.assertIn("### TSH", markdown)
        self.assertIn("`insight_id`: insight_p001_doc_demo_thyroid_status", markdown)
        self.assertIn("`metric_id`: m_p001_2026-04-25_tsh", markdown)
        self.assertIn("`observation_id`: obs_p001_2026-04-25_tsh", markdown)
        self.assertIn("`file_uri`: gs://bucket/raw/doc_demo.pdf", markdown)

    def test_dedupes_duplicate_metric_rows_by_metric_id(self):
        rows = [
            make_trace_row(),
            make_trace_row(),
            make_trace_row(
                metric_id="m_p001_2026-04-25_free_t3",
                metric_name="Free T3",
                value=3.1,
                unit="pg/mL",
                reference_low=2.3,
                reference_high=4.2,
                metric_status="normal",
                observation_id="obs_p001_2026-04-25_free_t3",
                raw_label="Free T3",
                raw_value="3.10",
                normalized_label="Free T3",
                source_location="page=1 line=16",
            ),
        ]

        deduped_rows = dedupe_metric_rows(rows)
        markdown = render_thyroid_dashboard_markdown(
            [make_card_row()],
            rows,
            person_id="p001",
        )

        self.assertEqual(2, len(deduped_rows))
        self.assertEqual(1, markdown.count("| TSH | 6.264 | uIU/mL | 0.35 - 4.94 | high |"))

    def test_does_not_include_coach_recommendation_section(self):
        markdown = render_thyroid_dashboard_markdown(
            [make_card_row()],
            [make_trace_row()],
            person_id="p001",
        )

        self.assertNotIn("Coach Recommendation", markdown)
        self.assertNotIn("## Coach", markdown)


if __name__ == "__main__":
    unittest.main()

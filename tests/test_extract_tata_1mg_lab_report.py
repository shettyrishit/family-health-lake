from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from family_health_lake.extraction.tata_1mg_lab_report import (
    extract_report_data,
    normalize_id_component,
    parse_numeric_value,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "tata_1mg_lab_report_fake.txt"
MAPPING_PATH = (
    REPO_ROOT
    / "config"
    / "metric_mappings"
    / "tata_1mg_lab_metrics.yaml"
)


def load_fake_pages():
    page_texts = []
    current_page = None
    current_lines = []

    for raw_line in FIXTURE_PATH.read_text(encoding="utf-8").splitlines():
        if raw_line.startswith("=== Page "):
            if current_page is not None:
                page_texts.append(
                    {"page_number": current_page, "text": "\n".join(current_lines)}
                )
            current_page = int(raw_line.replace("=== Page ", "").replace(" ===", ""))
            current_lines = []
            continue

        current_lines.append(raw_line)

    if current_page is not None:
        page_texts.append({"page_number": current_page, "text": "\n".join(current_lines)})

    return page_texts


class ExtractTata1mgLabReportTests(unittest.TestCase):
    def setUp(self):
        self.extraction = extract_report_data(
            page_texts=load_fake_pages(),
            person_id="p001",
            document_id="doc_p001_lab_2026_04_25_tata_1mg_fake",
            metric_date="2026-04-25",
            mapping_path=MAPPING_PATH,
        )

    def test_mapped_metric_extraction_and_traceability(self):
        observations = self.extraction["observations"]
        health_metrics = self.extraction["health_metrics"]

        self.assertEqual(3, len(observations))
        self.assertEqual(3, len(health_metrics))

        observation_ids = {row["observation_id"] for row in observations}
        self.assertIn("obs_p001_2026-04-25_tsh", observation_ids)
        self.assertIn("obs_p001_2026-04-25_free_t4", observation_ids)
        self.assertIn("obs_p001_2026-04-25_lipoprotein_a", observation_ids)

        metric_by_name = {row["metric_name"]: row for row in health_metrics}
        self.assertEqual("m_p001_2026-04-25_tsh", metric_by_name["TSH"]["metric_id"])
        self.assertEqual(
            "obs_p001_2026-04-25_tsh",
            metric_by_name["TSH"]["observation_id"],
        )
        self.assertEqual("high", metric_by_name["TSH"]["status"])
        self.assertEqual("normal", metric_by_name["Free T4"]["status"])

        for metric in health_metrics:
            self.assertIn(metric["observation_id"], observation_ids)

    def test_comparator_value_parsing_and_preservation(self):
        parsed = parse_numeric_value("> 1000.00")
        self.assertEqual(">", parsed.comparator)
        self.assertEqual(1000.0, parsed.parsed_value)
        self.assertEqual(">1000.00", parsed.text_value)

        lpa_metric = next(
            row for row in self.extraction["health_metrics"] if row["metric_name"] == "Lipoprotein(a)"
        )
        lpa_observation = next(
            row for row in self.extraction["observations"] if row["normalized_label"] == "Lipoprotein(a)"
        )
        self.assertEqual(">1000.00", lpa_metric["text_value"])
        self.assertEqual(1000.0, lpa_metric["value"])
        self.assertEqual("> 1000.00", lpa_observation["raw_value"])

    def test_unconverted_capture_and_report_counts(self):
        unconverted = self.extraction["unconverted_observations"]
        report = self.extraction["report"]

        self.assertEqual(2, len(unconverted))
        self.assertEqual(1, report["unconverted_observations_count"])
        self.assertEqual(1, report["unidentified_count"])
        self.assertEqual(3, report["skipped_lines_count"])
        self.assertEqual(3, report["mapped_metrics_found"])
        self.assertEqual(3, report["health_metrics_created"])

        reverse_t3 = next(row for row in unconverted if row["raw_label"] == "Reverse T3")
        self.assertEqual("unconverted", reverse_t3["conversion_status"])
        self.assertEqual("medical_lab_reports", reverse_t3["taxonomy"])

        unidentified = next(
            row for row in unconverted if row["conversion_status"] == "unidentified"
        )
        self.assertEqual("unidentified", unidentified["taxonomy"])

    def test_normalize_id_component(self):
        self.assertEqual("tsh", normalize_id_component("TSH"))
        self.assertEqual("free_t4", normalize_id_component("Free T4"))
        self.assertEqual("lipoprotein_a", normalize_id_component("Lipoprotein(a)"))


if __name__ == "__main__":
    unittest.main()

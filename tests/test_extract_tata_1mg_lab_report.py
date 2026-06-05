import sys
import unittest
from pathlib import Path

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
DUPLICATE_RANGE_FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "tata_1mg_lab_report_duplicates_and_ranges_fake.txt"
)
MAPPING_PATH = (
    REPO_ROOT
    / "config"
    / "metric_mappings"
    / "tata_1mg_lab_metrics.yaml"
)


def load_pages_from_fixture(fixture_path: Path):
    page_texts = []
    current_page = None
    current_lines = []

    for raw_line in fixture_path.read_text(encoding="utf-8").splitlines():
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


def load_fake_pages():
    return load_pages_from_fixture(FIXTURE_PATH)


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
        self.assertEqual(0, report["duplicate_observations_skipped"])
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


class ExtractTata1mgDeduplicationAndRangeTests(unittest.TestCase):
    def setUp(self):
        self.extraction = extract_report_data(
            page_texts=load_pages_from_fixture(DUPLICATE_RANGE_FIXTURE_PATH),
            person_id="p001",
            document_id="doc_p001_lab_2026_04_25_tata_1mg_duplicate_fake",
            metric_date="2026-04-25",
            mapping_path=MAPPING_PATH,
        )

    def test_duplicate_ferritin_rows_emit_one_metric(self):
        observations = self.extraction["observations"]
        health_metrics = self.extraction["health_metrics"]
        report = self.extraction["report"]

        ferritin_observations = [
            row for row in observations if row["normalized_label"] == "Ferritin"
        ]
        ferritin_metrics = [
            row for row in health_metrics if row["metric_name"] == "Ferritin"
        ]

        self.assertEqual(2, len(ferritin_observations))
        self.assertEqual(1, len(ferritin_metrics))
        self.assertEqual(1, report["duplicate_observations_skipped"])
        self.assertEqual("obs_p001_2026-04-25_ferritin", ferritin_metrics[0]["observation_id"])

    def test_split_line_reference_ranges_and_statuses(self):
        metric_by_name = {
            row["metric_name"]: row for row in self.extraction["health_metrics"]
        }

        vitamin_b12 = metric_by_name["Vitamin B12"]
        self.assertEqual(398.0, vitamin_b12["value"])
        self.assertEqual(187.0, vitamin_b12["reference_low"])
        self.assertEqual(833.0, vitamin_b12["reference_high"])
        self.assertEqual("normal", vitamin_b12["status"])

        ferritin = metric_by_name["Ferritin"]
        self.assertEqual(41.7, ferritin["value"])
        self.assertEqual(21.81, ferritin["reference_low"])
        self.assertEqual(274.66, ferritin["reference_high"])
        self.assertEqual("normal", ferritin["status"])

        lipoprotein_a = metric_by_name["Lipoprotein(a)"]
        self.assertEqual(43.5, lipoprotein_a["value"])
        self.assertIsNone(lipoprotein_a["reference_low"])
        self.assertEqual(30.0, lipoprotein_a["reference_high"])
        self.assertEqual("high", lipoprotein_a["status"])

        hdl = metric_by_name["HDL Cholesterol"]
        self.assertEqual(50.0, hdl["value"])
        self.assertEqual(39.5, hdl["reference_low"])
        self.assertIsNone(hdl["reference_high"])
        self.assertEqual("normal", hdl["status"])

    def test_duplicate_fixture_report_counts(self):
        report = self.extraction["report"]

        self.assertEqual(5, report["mapped_metrics_found"])
        self.assertEqual(4, report["health_metrics_created"])
        self.assertEqual(1, report["duplicate_observations_skipped"])
        self.assertEqual(0, report["unconverted_observations_count"])
        self.assertEqual(0, report["unidentified_count"])


if __name__ == "__main__":
    unittest.main()

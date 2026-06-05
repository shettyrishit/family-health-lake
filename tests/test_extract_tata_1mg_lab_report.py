import sys
import unittest
import csv
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from family_health_lake.extraction.tata_1mg_lab_report import (
    HEALTH_METRIC_FIELDS,
    OBSERVATION_FIELDS,
    extract_report_data,
    normalize_id_component,
    parse_numeric_value,
    write_csv,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "tata_1mg_lab_report_fake.txt"
DUPLICATE_RANGE_FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "tata_1mg_lab_report_duplicates_and_ranges_fake.txt"
)
UNMAPPED_NOISE_FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "tata_1mg_lab_report_unmapped_and_noise_fake.txt"
)
TSH_SPLIT_FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "tata_1mg_lab_report_tsh_split_fake.txt"
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
        self.assertEqual(1, report["unmapped_lab_result_count"])
        self.assertEqual(1, report["unidentified_count"])
        self.assertEqual(0, report["skipped_noise_count"])
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
        self.assertEqual(0, report["unmapped_lab_result_count"])
        self.assertEqual(0, report["unidentified_count"])
        self.assertEqual(0, report["skipped_noise_count"])


class ExtractTata1mgUnmappedAndNoiseTests(unittest.TestCase):
    def setUp(self):
        self.extraction = extract_report_data(
            page_texts=load_pages_from_fixture(UNMAPPED_NOISE_FIXTURE_PATH),
            person_id="p001",
            document_id="doc_p001_lab_2026_04_25_tata_1mg_unmapped_fake",
            metric_date="2026-04-25",
            mapping_path=MAPPING_PATH,
        )

    def test_unmapped_lab_rows_become_unconverted_medical_lab_reports(self):
        unconverted = self.extraction["unconverted_observations"]

        hemoglobin = next(row for row in unconverted if row["raw_label"] == "Hemoglobin")
        self.assertEqual("medical_lab_reports", hemoglobin["taxonomy"])
        self.assertEqual("lab_result", hemoglobin["observation_type"])
        self.assertEqual("unconverted", hemoglobin["conversion_status"])
        self.assertEqual("raw_label_not_mapped", hemoglobin["failure_reason"])
        self.assertEqual("Hemoglobin 13.4 g/dL 13.0 - 17.0", hemoglobin["raw_text"])
        self.assertIn("Comment:", hemoglobin["surrounding_text"])
        self.assertIn("Neutrophils 45.2 % 40 - 80", hemoglobin["surrounding_text"])

        neutrophils = next(row for row in unconverted if row["raw_label"] == "Neutrophils")
        self.assertEqual("medical_lab_reports", neutrophils["taxonomy"])
        self.assertEqual("unconverted", neutrophils["conversion_status"])
        self.assertEqual("raw_label_not_mapped", neutrophils["failure_reason"])

    def test_noise_lines_are_skipped(self):
        unconverted_text = "\n".join(
            row["raw_text"] for row in self.extraction["unconverted_observations"]
        )
        self.assertNotIn("Customer Name", unconverted_text)
        self.assertNotIn("Comment:", unconverted_text)
        self.assertNotIn("Page 11 of 39", unconverted_text)

    def test_report_counts_for_unmapped_and_noise(self):
        report = self.extraction["report"]

        self.assertEqual(3, report["unconverted_observations_count"])
        self.assertEqual(3, report["unmapped_lab_result_count"])
        self.assertEqual(0, report["unidentified_count"])
        self.assertEqual(4, report["skipped_noise_count"])


class ExtractTata1mgTshTests(unittest.TestCase):
    def test_tsh_split_across_lines_is_mapped(self):
        extraction = extract_report_data(
            page_texts=load_pages_from_fixture(TSH_SPLIT_FIXTURE_PATH),
            person_id="p001",
            document_id="doc_p001_lab_2026_04_25_tata_1mg_tsh_fake",
            metric_date="2026-04-25",
            mapping_path=MAPPING_PATH,
        )

        metric_by_name = {
            row["metric_name"]: row for row in extraction["health_metrics"]
        }
        tsh = metric_by_name["TSH"]

        self.assertEqual(6.264, tsh["value"])
        self.assertEqual("µIU/mL", tsh["unit"])
        self.assertEqual(0.35, tsh["reference_low"])
        self.assertEqual(4.94, tsh["reference_high"])
        self.assertEqual("high", tsh["status"])


class ExtractTata1mgCsvWritingTests(unittest.TestCase):
    def test_csv_round_trip_with_quotes_commas_and_newlines(self):
        observation_rows = [
            {
                "observation_id": "obs_p001_2026-04-25_demo",
                "person_id": "p001",
                "document_id": "doc_demo",
                "observed_at": "2026-04-25",
                "source": "tata_1mg",
                "taxonomy": "medical_lab_reports",
                "observation_type": "lab_result",
                "raw_label": 'Hemoglobin, "Hb"',
                "raw_value": "13.4",
                "normalized_label": "Hemoglobin",
                "parsed_value": 13.4,
                "unit": "g/dL",
                "source_location": "page=1;line=3",
                "confidence": 0.7,
                "conversion_status": "unconverted",
                "raw_text": 'Hemoglobin, "Hb"\n13.4 g/dL',
                "surrounding_text": "Previous line\nHemoglobin, \"Hb\"\nNext line",
                "failure_reason": "raw_label_not_mapped",
                "notes": 'contains, commas "quotes"\nand newlines',
            },
            {
                "observation_id": "obs_p001_2026-04-25_demo_2",
                "person_id": "p001",
                "document_id": "doc_demo",
                "observed_at": "2026-04-25",
                "source": "tata_1mg",
                "taxonomy": "medical_lab_reports",
                "observation_type": "lab_result",
                "raw_label": "Neutrophils",
                "raw_value": "45.2",
                "normalized_label": "Neutrophils",
                "parsed_value": 45.2,
                "unit": "%",
                "source_location": "page=1;line=4",
                "confidence": 0.7,
                "conversion_status": "unconverted",
                "raw_text": "Neutrophils 45.2 %",
                "surrounding_text": "A, B, C",
                "failure_reason": "raw_label_not_mapped",
                "notes": 'simple "quoted" note',
            },
        ]
        metric_rows = [
            {
                "metric_id": "m_p001_2026-04-25_tsh",
                "person_id": "p001",
                "document_id": "doc_demo",
                "observation_id": "obs_p001_2026-04-25_tsh",
                "metric_date": "2026-04-25",
                "source": "tata_1mg",
                "category": "thyroid",
                "metric_name": "TSH",
                "value": 6.264,
                "text_value": "",
                "unit": "µIU/mL",
                "reference_low": 0.35,
                "reference_high": 4.94,
                "status": "high",
                "notes": 'mapped from "TSH, Ultra Sensitive"\nrange nearby',
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            observations_path = Path(temp_dir) / "observations.csv"
            metrics_path = Path(temp_dir) / "health_metric.csv"
            write_csv(observation_rows, OBSERVATION_FIELDS, observations_path)
            write_csv(metric_rows, HEALTH_METRIC_FIELDS, metrics_path)

            observation_lines = observations_path.read_text(encoding="utf-8").splitlines()
            metric_lines = metrics_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(3, len(observation_lines))
            self.assertEqual(2, len(metric_lines))

            with observations_path.open("r", encoding="utf-8", newline="") as handle:
                read_observations = list(csv.DictReader(handle))
            with metrics_path.open("r", encoding="utf-8", newline="") as handle:
                read_metrics = list(csv.DictReader(handle))

            self.assertEqual(2, len(read_observations))
            self.assertEqual(1, len(read_metrics))
            self.assertEqual(
                'Hemoglobin, "Hb" 13.4 g/dL',
                read_observations[0]["raw_text"],
            )
            self.assertEqual(
                'Previous line Hemoglobin, "Hb" Next line',
                read_observations[0]["surrounding_text"],
            )
            self.assertEqual(
                'contains, commas "quotes" and newlines',
                read_observations[0]["notes"],
            )
            self.assertEqual(
                'mapped from "TSH, Ultra Sensitive" range nearby',
                read_metrics[0]["notes"],
            )


if __name__ == "__main__":
    unittest.main()

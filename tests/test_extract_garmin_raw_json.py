import json
import shutil
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from family_health_lake.extraction.garmin_raw_json import (
    extract_garmin_raw_json,
    load_metric_mappings,
    validate_garmin_wrapper,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "garmin_raw_json"
MAPPING_PATH = (
    REPO_ROOT
    / "config"
    / "metric_mappings"
    / "garmin_raw_json_metrics.yaml"
)


def load_fixture(name: str):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


class ExtractGarminRawJsonTests(unittest.TestCase):
    def test_wrapper_validation_requires_expected_wrapper_shape(self):
        invalid_payload = load_fixture("invalid_wrapper_fake.json")

        with self.assertRaisesRegex(ValueError, "missing required fields"):
            validate_garmin_wrapper(
                invalid_payload,
                file_path=FIXTURE_DIR / "invalid_wrapper_fake.json",
            )

    def test_unsupported_category_is_warned_and_skipped(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            shutil.copy2(
                FIXTURE_DIR / "unsupported_body_battery_fake.json",
                temp_path / "unsupported_body_battery_fake.json",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                extraction = extract_garmin_raw_json(
                    input_dir=temp_path,
                    person_id="p001",
                    document_id="doc_p001_garmin_raw_2026_06_10_fake",
                    mapping_path=MAPPING_PATH,
                )

        self.assertEqual([], extraction["observations"])
        self.assertEqual([], extraction["health_metrics"])
        self.assertIn("unsupported Garmin category 'body_battery'", stdout.getvalue())
        self.assertEqual(
            "unsupported_category:body_battery",
            extraction["discovery_report"][0]["skip_reason"],
        )

    def test_daily_metric_extraction_and_deterministic_ids(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            shutil.copy2(
                FIXTURE_DIR / "daily_activity_summary_fake.json",
                temp_path / "daily_activity_summary_fake.json",
            )
            shutil.copy2(
                FIXTURE_DIR / "resting_heart_rate_nested_fake.json",
                temp_path / "resting_heart_rate_fake.json",
            )
            shutil.copy2(
                FIXTURE_DIR / "sleep_fake.json",
                temp_path / "sleep_fake.json",
            )
            shutil.copy2(
                FIXTURE_DIR / "hrv_fake.json",
                temp_path / "hrv_fake.json",
            )

            extraction = extract_garmin_raw_json(
                input_dir=temp_path,
                person_id="p001",
                document_id="doc_p001_garmin_raw_2026_06_10_fake",
                mapping_path=MAPPING_PATH,
            )

        observations = extraction["observations"]
        health_metrics = extraction["health_metrics"]
        self.assertEqual(4, len(observations))
        self.assertEqual(4, len(health_metrics))

        observation_ids = {row["observation_id"] for row in observations}
        self.assertIn("obs_p001_2026-06-10_steps", observation_ids)
        self.assertIn("obs_p001_2026-06-10_resting_hr", observation_ids)
        self.assertIn("obs_p001_2026-06-10_sleep_minutes", observation_ids)
        self.assertIn("obs_p001_2026-06-10_hrv_avg", observation_ids)

        metric_by_name = {row["metric_name"]: row for row in health_metrics}
        self.assertEqual("m_p001_2026-06-10_steps", metric_by_name["Steps"]["metric_id"])
        self.assertEqual(
            "obs_p001_2026-06-10_steps",
            metric_by_name["Steps"]["observation_id"],
        )
        self.assertEqual(12345.0, metric_by_name["Steps"]["value"])
        self.assertEqual(46.0, metric_by_name["Resting HR"]["value"])
        self.assertEqual(480.0, metric_by_name["Sleep"]["value"])
        self.assertEqual(57.5, metric_by_name["HRV Average"]["value"])

    def test_activity_metric_extraction_and_traceability(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            shutil.copy2(
                FIXTURE_DIR / "activities_fake.json",
                temp_path / "activities_fake.json",
            )

            extraction = extract_garmin_raw_json(
                input_dir=temp_path,
                person_id="p001",
                document_id="doc_p001_garmin_raw_2026_06_10_fake",
                mapping_path=MAPPING_PATH,
            )

        observations = extraction["observations"]
        health_metrics = extraction["health_metrics"]
        self.assertEqual(2, len(observations))
        self.assertEqual(2, len(health_metrics))

        observation_ids = {row["observation_id"] for row in observations}
        self.assertIn(
            "obs_p001_2026-06-10_987654_activity_duration_minutes",
            observation_ids,
        )
        self.assertIn(
            "obs_p001_2026-06-10_987654_activity_distance_km",
            observation_ids,
        )

        metric_by_name = {row["metric_name"]: row for row in health_metrics}
        self.assertEqual(61.0, metric_by_name["Activity Duration"]["value"])
        self.assertEqual(5.025, metric_by_name["Activity Distance"]["value"])

        for metric in health_metrics:
            self.assertIn(metric["observation_id"], observation_ids)

    def test_category_alias_and_heart_rates_are_supported(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            alias_payload = load_fixture("daily_activity_summary_fake.json")
            alias_payload["category"] = "daily_summary"
            (temp_path / "daily_summary_fake.json").write_text(
                json.dumps(alias_payload),
                encoding="utf-8",
            )
            shutil.copy2(
                FIXTURE_DIR / "heart_rates_fake.json",
                temp_path / "heart_rates_fake.json",
            )

            extraction = extract_garmin_raw_json(
                input_dir=temp_path,
                person_id="p001",
                document_id="doc_p001_garmin_raw_2026_06_10_fake",
                mapping_path=MAPPING_PATH,
            )

        metric_by_name = {row["metric_name"]: row for row in extraction["health_metrics"]}
        self.assertEqual(12345.0, metric_by_name["Steps"]["value"])
        self.assertEqual(42.0, metric_by_name["Min HR"]["value"])
        self.assertEqual(164.0, metric_by_name["Max HR"]["value"])
        self.assertEqual(70.0, metric_by_name["Average HR"]["value"])

    def test_discovery_report_includes_clear_skip_reason_for_empty_hrv(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            shutil.copy2(
                FIXTURE_DIR / "hrv_empty_fake.json",
                temp_path / "hrv_empty_fake.json",
            )
            discovery_path = temp_path / "discovery.json"

            extraction = extract_garmin_raw_json(
                input_dir=temp_path,
                person_id="p001",
                document_id="doc_p001_garmin_raw_2026_06_10_fake",
                mapping_path=MAPPING_PATH,
                discovery_report_path=discovery_path,
            )
            self.assertEqual([], extraction["health_metrics"])
            self.assertTrue(discovery_path.exists())
            discovery_report = json.loads(discovery_path.read_text(encoding="utf-8"))
            self.assertEqual("hrv", discovery_report[0]["category"])
            self.assertEqual("dict", discovery_report[0]["raw_payload_type"])
            self.assertEqual(["category", "entries"], discovery_report[0]["raw_payload_top_level_keys"])
            self.assertEqual(1, discovery_report[0]["detected_record_count"])
            self.assertEqual("skipped", discovery_report[0]["extraction_status"])
            self.assertEqual("no_daily_hrv_values_found", discovery_report[0]["skip_reason"])

    def test_metric_mappings_include_expected_keys(self):
        mappings = load_metric_mappings(MAPPING_PATH)

        self.assertEqual("Steps", mappings["steps"].display_name)
        self.assertEqual("training_activity", mappings["steps"].taxonomy)
        self.assertEqual("Resting HR", mappings["resting_hr"].display_name)
        self.assertEqual("recovery_sleep", mappings["sleep_minutes"].taxonomy)
        self.assertEqual("Average HR", mappings["avg_hr"].display_name)
        self.assertEqual("Min HR", mappings["min_hr"].display_name)
        self.assertEqual("Max HR", mappings["max_hr"].display_name)


if __name__ == "__main__":
    unittest.main()

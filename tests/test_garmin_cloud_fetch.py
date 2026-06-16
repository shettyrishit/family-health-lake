import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from family_health_lake.ingestion.garmin_cloud_fetch import (
    build_gcs_blob_name,
    build_local_output_path,
    fetch_garmin_to_gcs,
    load_garmin_environment_config,
)


class FakeBlob:
    def __init__(self, name):
        self.name = name
        self.uploads = []

    def upload_from_filename(self, filename, content_type=None):
        self.uploads.append({"filename": filename, "content_type": content_type})


class FakeBucket:
    def __init__(self, name):
        self.name = name
        self.blobs = {}

    def blob(self, blob_name):
        blob = self.blobs.get(blob_name)
        if blob is None:
            blob = FakeBlob(blob_name)
            self.blobs[blob_name] = blob
        return blob


class FakeStorageClient:
    def __init__(self):
        self.buckets = {}

    def bucket(self, bucket_name):
        bucket = self.buckets.get(bucket_name)
        if bucket is None:
            bucket = FakeBucket(bucket_name)
            self.buckets[bucket_name] = bucket
        return bucket


class FakeGarminClient:
    def get_rhr_day(self, day):
        return {"calendarDate": day, "value": 48}

    def get_heart_rates(self, day):
        return {"calendarDate": day, "heartRateValues": [[1, 60], [2, 65]]}

    def get_user_summary(self, day):
        return {"calendarDate": day, "totalSteps": 10000}

    def get_steps_data(self, day):
        return [{"calendarDate": day, "steps": 10000}]

    def get_sleep_data(self, day):
        return {"calendarDate": day, "sleepTimeSeconds": 28800}

    def get_hrv_data(self, day):
        return {"calendarDate": day, "lastNightAvg": 60}

    def get_activities(self, start, limit):
        if start > 0:
            return []
        return [
            {
                "activityId": 1,
                "activityDate": "2026-06-10",
                "activityName": "Morning Run",
            },
            {
                "activityId": 2,
                "activityDate": "2026-06-16",
                "activityName": "Evening Walk",
            },
        ]


class GarminCloudFetchTests(unittest.TestCase):
    def test_build_local_output_path_matches_spike_convention(self):
        path = build_local_output_path(
            output_dir="outputs/garmin_fetch",
            person_id="p001",
            start_date="2026-06-10",
            end_date="2026-06-16",
            category="sleep",
        )

        self.assertEqual(
            Path(
                "outputs/garmin_fetch/person_id=p001/provider=garmin/"
                "date_range=2026-06-10_2026-06-16/sleep.json"
            ),
            path,
        )

    def test_build_gcs_blob_name_matches_spike_convention(self):
        blob_name = build_gcs_blob_name(
            raw_prefix="raw/",
            person_id="p001",
            start_date="2026-06-10",
            end_date="2026-06-16",
            category="activities",
        )

        self.assertEqual(
            "raw/person_id=p001/wearables/provider=garmin/"
            "source=python_garminconnect/date_range=2026-06-10_2026-06-16/activities.json",
            blob_name,
        )

    def test_load_garmin_environment_config_reads_project_and_bucket(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "dev.yaml"
            config_path.write_text(
                "gcp:\n"
                "  project_id: test-project\n"
                "storage:\n"
                "  raw_bucket: raw-bucket\n"
                "  raw_prefix: raw/\n",
                encoding="utf-8",
            )

            config = load_garmin_environment_config(config_path)

        self.assertEqual("test-project", config.project_id)
        self.assertEqual("raw-bucket", config.raw_bucket)
        self.assertEqual("raw/", config.raw_prefix)

    def test_fetch_garmin_to_gcs_writes_json_and_uses_fake_gcs_client(self):
        fake_storage_client = FakeStorageClient()
        fake_garmin_client = FakeGarminClient()

        previous_email = os.environ.get("GARMIN_EMAIL")
        previous_password = os.environ.get("GARMIN_PASSWORD")
        os.environ["GARMIN_EMAIL"] = "fake@example.com"
        os.environ["GARMIN_PASSWORD"] = "fake-password"

        try:
            with TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                config_path = temp_path / "dev.yaml"
                config_path.write_text(
                    "gcp:\n"
                    "  project_id: test-project\n"
                    "storage:\n"
                    "  raw_bucket: raw-bucket\n"
                    "  raw_prefix: raw/\n",
                    encoding="utf-8",
                )
                output_dir = temp_path / "outputs" / "garmin_fetch"

                results = fetch_garmin_to_gcs(
                    environment_config_path=config_path,
                    person_id="p001",
                    start_date_str="2026-06-10",
                    end_date_str="2026-06-16",
                    garmin_email_env="GARMIN_EMAIL",
                    garmin_password_env="GARMIN_PASSWORD",
                    token_dir=temp_path / ".garminconnect",
                    output_dir=output_dir,
                    upload_to_gcs=True,
                    garmin_client=fake_garmin_client,
                    storage_client=fake_storage_client,
                    fetched_at="2026-06-16T12:34:56Z",
                )

                success_categories = {result.category for result in results if result.success}
                self.assertEqual(
                    {
                        "resting_heart_rate",
                        "heart_rates",
                        "daily_activity_summary",
                        "sleep",
                        "hrv",
                        "activities",
                    },
                    success_categories,
                )

                sleep_path = (
                    output_dir
                    / "person_id=p001"
                    / "provider=garmin"
                    / "date_range=2026-06-10_2026-06-16"
                    / "sleep.json"
                )
                self.assertTrue(sleep_path.exists())

                sleep_document = json.loads(sleep_path.read_text(encoding="utf-8"))
                self.assertEqual("p001", sleep_document["person_id"])
                self.assertEqual("garmin", sleep_document["provider"])
                self.assertEqual("python_garminconnect", sleep_document["source"])
                self.assertEqual("sleep", sleep_document["category"])
                self.assertEqual("2026-06-10", sleep_document["start_date"])
                self.assertEqual("2026-06-16", sleep_document["end_date"])
                self.assertEqual("2026-06-16T12:34:56Z", sleep_document["fetched_at"])

                bucket = fake_storage_client.buckets["raw-bucket"]
                expected_blob_name = (
                    "raw/person_id=p001/wearables/provider=garmin/"
                    "source=python_garminconnect/date_range=2026-06-10_2026-06-16/sleep.json"
                )
                self.assertIn(expected_blob_name, bucket.blobs)
                self.assertEqual(
                    "application/json",
                    bucket.blobs[expected_blob_name].uploads[0]["content_type"],
                )
        finally:
            if previous_email is None:
                os.environ.pop("GARMIN_EMAIL", None)
            else:
                os.environ["GARMIN_EMAIL"] = previous_email

            if previous_password is None:
                os.environ.pop("GARMIN_PASSWORD", None)
            else:
                os.environ["GARMIN_PASSWORD"] = previous_password


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import sys

# Add src and scripts to sys.path
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"
SCRIPTS_PATH = REPO_ROOT
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))
if str(SCRIPTS_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_PATH))

from scripts.admin.scrub_person_bigquery_data import scrub_person_data, build_parser

class TestScrubPersonBigQueryData(unittest.TestCase):
    def setUp(self):
        self.config_path = str(REPO_ROOT / "config" / "environments" / "dev.yaml")
        self.person_id = "p001"

    def test_default_mode_is_generated(self):
        parser = build_parser()
        args = parser.parse_args(["--environment-config", "dev.yaml", "--person-id", "p001"])
        self.assertEqual(args.mode, "generated")

    @patch("scripts.admin.scrub_person_bigquery_data.load_yaml_config")
    def test_generated_mode_table_list(self, mock_load_config):
        mock_load_config.return_value = {
            "gcp": {"project_id": "test-project"},
            "bigquery": {"dataset": "test_dataset"}
        }
        mock_client = MagicMock()
        # Mocking counts for 5 tables
        mock_job = MagicMock()
        mock_job.result.return_value = [MagicMock(cnt=0)]
        mock_client.query.return_value = mock_job
        
        scrub_person_data(
            config_path="dev.yaml",
            person_id=self.person_id,
            mode="generated",
            execute=False,
            confirm_person_id=None,
            client=mock_client
        )
        
        # Check that it queried all 5 tables in 'generated' mode
        self.assertEqual(mock_client.query.call_count, 5)
        
        # Verify call order (first call's query string)
        calls = mock_client.query.call_args_list
        self.assertIn("FROM `test-project.test_dataset.insight`", calls[0][0][0])
        self.assertIn("FROM `test-project.test_dataset.observation`", calls[4][0][0])

    @patch("scripts.admin.scrub_person_bigquery_data.load_yaml_config")
    def test_full_person_mode_table_list(self, mock_load_config):
        mock_load_config.return_value = {
            "gcp": {"project_id": "test-project"},
            "bigquery": {"dataset": "test_dataset"}
        }
        mock_client = MagicMock()
        mock_job = MagicMock()
        mock_job.result.return_value = [MagicMock(cnt=0)]
        mock_client.query.return_value = mock_job
        
        scrub_person_data(
            config_path="dev.yaml",
            person_id=self.person_id,
            mode="full-person",
            execute=False,
            confirm_person_id=None,
            client=mock_client
        )
        
        # Check that it queried all 7 tables in 'full-person' mode
        self.assertEqual(mock_client.query.call_count, 7)
        self.assertIn("FROM `test-project.test_dataset.person`", mock_client.query.call_args_list[6][0][0])

    @patch("scripts.admin.scrub_person_bigquery_data.load_yaml_config")
    def test_dry_run_does_not_execute_deletes(self, mock_load_config):
        mock_load_config.return_value = {
            "gcp": {"project_id": "test-project"},
            "bigquery": {"dataset": "test_dataset"}
        }
        mock_client = MagicMock()
        mock_job = MagicMock()
        mock_job.result.return_value = [MagicMock(cnt=10)] # Pretend there are rows
        mock_client.query.return_value = mock_job
        
        scrub_person_data(
            config_path="dev.yaml",
            person_id=self.person_id,
            mode="generated",
            execute=False,
            confirm_person_id=None,
            client=mock_client
        )
        
        # Should only have called SELECT COUNT, not DELETE
        # 5 tables * 1 query each
        self.assertEqual(mock_client.query.call_count, 5)
        for call in mock_client.query.call_args_list:
            self.assertIn("SELECT COUNT(*)", call[0][0])
            self.assertNotIn("DELETE", call[0][0])

    @patch("scripts.admin.scrub_person_bigquery_data.load_yaml_config")
    def test_execute_requires_matching_confirm_person_id(self, mock_load_config):
        # Mismatch
        res = scrub_person_data(
            config_path="dev.yaml",
            person_id="p001",
            mode="generated",
            execute=True,
            confirm_person_id="p002",
            client=MagicMock()
        )
        self.assertEqual(res, 1)
        
        # Missing
        res = scrub_person_data(
            config_path="dev.yaml",
            person_id="p001",
            mode="generated",
            execute=True,
            confirm_person_id=None,
            client=MagicMock()
        )
        self.assertEqual(res, 1)

    @patch("scripts.admin.scrub_person_bigquery_data.load_yaml_config")
    def test_execute_successful_flow(self, mock_load_config):
        mock_load_config.return_value = {
            "gcp": {"project_id": "test-project"},
            "bigquery": {"dataset": "test_dataset"}
        }
        mock_client = MagicMock()
        mock_job = MagicMock()
        mock_job.result.return_value = [MagicMock(cnt=10)]
        mock_client.query.return_value = mock_job
        
        res = scrub_person_data(
            config_path="dev.yaml",
            person_id="p001",
            mode="generated",
            execute=True,
            confirm_person_id="p001",
            client=mock_client
        )
        self.assertEqual(res, 0)
        
        # 5 tables * 2 queries (COUNT and DELETE) = 10 calls
        self.assertEqual(mock_client.query.call_count, 10)
        
        # Check that DELETE was called
        delete_calls = [call for call in mock_client.query.call_args_list if "DELETE" in call[0][0]]
        self.assertEqual(len(delete_calls), 5)

if __name__ == "__main__":
    unittest.main()

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from family_health_lake.dashboard.thyroid_markdown import fetch_thyroid_dashboard_rows, THYROID_DASHBOARD_FIELD_NAMES

class TestThyroidDashboardFetcher(unittest.TestCase):
    def test_fetch_thyroid_dashboard_rows_calls_get_row_value(self):
        # Mock BigQuery client and row
        mock_client = MagicMock()
        mock_row = MagicMock()
        
        # Setup mock row to behave like a dict-like object
        # We need to provide values for all fields in THYROID_DASHBOARD_FIELD_NAMES 
        # that get_row_value might try to access.
        row_data = {field: f"val_{field}" for field in THYROID_DASHBOARD_FIELD_NAMES}
        
        mock_row.get.side_effect = lambda key, default=None: row_data.get(key, default)
        mock_row.__getitem__.side_effect = lambda key: row_data[key]
        
        mock_query_job = MagicMock()
        mock_query_job.result.return_value = [mock_row]
        mock_client.query.return_value = mock_query_job
        
        # Call the function
        rows = fetch_thyroid_dashboard_rows(
            mock_client, 
            project_id="test-project", 
            dataset="test-dataset", 
            person_id="p001"
        )
        
        # Verify result
        self.assertEqual(len(rows), 1)
        # Check a specific field
        self.assertEqual(rows[0]["metric_id"], "val_metric_id")
        
        # Verify query was called
        self.assertTrue(mock_client.query.called)

if __name__ == "__main__":
    unittest.main()

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import local_backend


class LocalBackendMetadataTests(unittest.TestCase):
    def test_metadata_includes_optional_dependency_extras(self):
        metadata = local_backend._metadata_contents()

        self.assertIn("Provides-Extra: bigquery", metadata)
        self.assertIn(
            "Requires-Dist: google-cloud-bigquery>=3,<4; extra == 'bigquery'",
            metadata,
        )
        self.assertIn(
            "Requires-Dist: PyYAML>=6,<7; extra == 'bigquery'",
            metadata,
        )
        self.assertIn("Provides-Extra: garmin", metadata)
        self.assertIn(
            "Requires-Dist: garminconnect>=0.3.6,<0.4; extra == 'garmin'",
            metadata,
        )
        self.assertIn(
            "Requires-Dist: curl_cffi>=0.7,<1; extra == 'garmin'",
            metadata,
        )
        self.assertIn(
            "Requires-Dist: google-cloud-storage>=2,<4; extra == 'garmin'",
            metadata,
        )
        self.assertIn("Provides-Extra: pdf", metadata)
        self.assertIn("Provides-Extra: test", metadata)


if __name__ == "__main__":
    unittest.main()

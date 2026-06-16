from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from family_health_lake.spikes.garmin_cloud_fetch import main


if __name__ == "__main__":
    raise SystemExit(main())

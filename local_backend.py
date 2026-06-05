from __future__ import annotations

import base64
import csv
import hashlib
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parent
SRC_PATH = PROJECT_ROOT / "src"
NAME = "family-health-lake"
VERSION = "0.1.0"
SUMMARY = "Local extraction utilities for the family health lake."
PYTHON_REQUIRES = ">=3.9"
WHEEL_TAG = "py3-none-any"
DIST_NAME = NAME.replace("-", "_")
DIST_INFO_DIR = f"{DIST_NAME}-{VERSION}.dist-info"


def _supported_features() -> List[str]:
    return ["build_editable"]


def get_requires_for_build_wheel(config_settings=None) -> List[str]:
    return []


def get_requires_for_build_editable(config_settings=None) -> List[str]:
    return []


def _metadata_contents() -> str:
    return "\n".join(
        [
            "Metadata-Version: 2.1",
            f"Name: {NAME}",
            f"Version: {VERSION}",
            f"Summary: {SUMMARY}",
            f"Requires-Python: {PYTHON_REQUIRES}",
            "",
        ]
    )


def _wheel_contents() -> str:
    return "\n".join(
        [
            "Wheel-Version: 1.0",
            "Generator: local_backend",
            "Root-Is-Purelib: true",
            f"Tag: {WHEEL_TAG}",
            "",
        ]
    )


def _entry_points_contents() -> str:
    return "\n".join(
        [
            "[console_scripts]",
            "extract-tata-1mg-lab-report = family_health_lake.extraction.tata_1mg_lab_report:main",
            "",
        ]
    )


def _top_level_contents() -> str:
    return "family_health_lake\n"


def _dist_info_files() -> List[Tuple[str, bytes]]:
    return [
        (f"{DIST_INFO_DIR}/METADATA", _metadata_contents().encode("utf-8")),
        (f"{DIST_INFO_DIR}/WHEEL", _wheel_contents().encode("utf-8")),
        (f"{DIST_INFO_DIR}/entry_points.txt", _entry_points_contents().encode("utf-8")),
        (f"{DIST_INFO_DIR}/top_level.txt", _top_level_contents().encode("utf-8")),
    ]


def _record_line(path: str, data: bytes) -> Tuple[str, str, str]:
    digest = hashlib.sha256(data).digest()
    encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return path, f"sha256={encoded}", str(len(data))


def prepare_metadata_for_build_wheel(
    metadata_directory: str,
    config_settings=None,
    _metadata_directory=None,
) -> str:
    dist_info_path = Path(metadata_directory) / DIST_INFO_DIR
    dist_info_path.mkdir(parents=True, exist_ok=True)
    for relative_path, data in _dist_info_files():
        target = Path(metadata_directory) / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return DIST_INFO_DIR


def prepare_metadata_for_build_editable(
    metadata_directory: str,
    config_settings=None,
    _metadata_directory=None,
) -> str:
    return prepare_metadata_for_build_wheel(metadata_directory, config_settings, _metadata_directory)


def _wheel_filename() -> str:
    return f"{DIST_NAME}-{VERSION}-{WHEEL_TAG}.whl"


def _editable_files() -> List[Tuple[str, bytes]]:
    pth_contents = f"{SRC_PATH}\n".encode("utf-8")
    return [(f"{DIST_NAME}.pth", pth_contents)] + _dist_info_files()


def _build_wheel_archive(target_path: Path, files: Sequence[Tuple[str, bytes]]) -> None:
    record_rows: List[Tuple[str, str, str]] = []
    with zipfile.ZipFile(target_path, "w", compression=zipfile.ZIP_DEFLATED) as wheel_zip:
        for archive_path, data in files:
            wheel_zip.writestr(archive_path, data)
            record_rows.append(_record_line(archive_path, data))

        record_path = f"{DIST_INFO_DIR}/RECORD"
        lines = []
        for archive_path, digest, size in record_rows:
            lines.append(f"{archive_path},{digest},{size}")
        lines.append(f"{record_path},,")
        record_data = ("\n".join(lines) + "\n").encode("utf-8")
        wheel_zip.writestr(record_path, record_data)


def build_wheel(
    wheel_directory: str,
    config_settings=None,
    metadata_directory=None,
) -> str:
    target_path = Path(wheel_directory) / _wheel_filename()
    Path(wheel_directory).mkdir(parents=True, exist_ok=True)
    _build_wheel_archive(target_path, _editable_files())
    return target_path.name


def build_editable(
    wheel_directory: str,
    config_settings=None,
    metadata_directory=None,
) -> str:
    return build_wheel(wheel_directory, config_settings, metadata_directory)

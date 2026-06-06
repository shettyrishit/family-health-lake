from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional


def normalize_id_component(value: str) -> str:
    """Normalizes a string for use as an ID component (snake_case, ASCII)."""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    snake_case = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_value.lower()).strip("_")
    return re.sub(r"_+", "_", snake_case)


def strip_yaml_string(value: str) -> str:
    """Strips quotes and whitespace from a YAML string value."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def get_row_value(row: Any, field_name: str) -> Any:
    """Gets a value from a row object, which could be a dict, a BigQuery row, or an object."""
    if isinstance(row, dict):
        return row.get(field_name)
    try:
        # Try bracket access for BigQuery rows or similar
        return row[field_name]
    except (KeyError, TypeError, IndexError):
        # Fallback to attribute access
        return getattr(row, field_name, None)


def _load_simple_yaml(path: Path) -> Dict[str, Any]:
    """A minimal YAML-like parser for simple key-value pairs and nested maps."""
    root: Dict[str, Any] = {}
    stack: List[tuple[int, Dict[str, Any]]] = [(-1, root)]

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        if ":" not in stripped:
            continue
            
        key, value = stripped.split(":", 1)
        key = strip_yaml_string(key)
        value = strip_yaml_string(value)

        while stack and indent <= stack[-1][0]:
            stack.pop()
        current = stack[-1][1]

        if value == "":
            child: Dict[str, Any] = {}
            current[key] = child
            stack.append((indent, child))
        else:
            current[key] = value

    return root


def load_yaml_config(path: str | Path) -> Dict[str, Any]:
    """Loads a YAML configuration file, using PyYAML if available, otherwise a simple fallback."""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
        
    try:
        import yaml  # type: ignore
    except ImportError:
        return _load_simple_yaml(config_path)
    else:
        with config_path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

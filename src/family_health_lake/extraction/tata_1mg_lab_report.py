from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


OBSERVATION_FIELDS = [
    "observation_id",
    "person_id",
    "document_id",
    "observed_at",
    "source",
    "taxonomy",
    "observation_type",
    "raw_label",
    "raw_value",
    "normalized_label",
    "parsed_value",
    "unit",
    "source_location",
    "confidence",
    "conversion_status",
    "notes",
]

HEALTH_METRIC_FIELDS = [
    "metric_id",
    "person_id",
    "document_id",
    "observation_id",
    "metric_date",
    "source",
    "category",
    "metric_name",
    "value",
    "text_value",
    "unit",
    "reference_low",
    "reference_high",
    "status",
    "notes",
]

VALUE_RE = re.compile(
    r"(?P<comparator><=|>=|<|>)?\s*(?P<number>\d+(?:,\d{3})*(?:\.\d+)?)"
)
RANGE_RE = re.compile(
    r"(?P<low>\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(?P<high>\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
LAB_RESULT_SIGNAL_RE = re.compile(
    r"(<|>|%|mg/dL|ng/dL|pg/mL|IU/mL|U/L|µIU/mL|mL/min/1\.73m2|[0-9]+\.[0-9]+\s*(?:-|–)\s*[0-9]+\.[0-9]+)",
    re.IGNORECASE,
)
UNIT_CLEANUP_RE = re.compile(r"^[\s:;,-]+|[\s:;,-]+$")


@dataclass(frozen=True)
class PageLine:
    page_number: int
    line_number: int
    text: str


@dataclass(frozen=True)
class ParsedValue:
    raw_value: str
    parsed_value: Optional[float]
    comparator: Optional[str]
    text_value: Optional[str]


def normalize_id_component(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    snake_case = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_value.lower()).strip("_")
    return re.sub(r"_+", "_", snake_case)


def parse_numeric_value(raw_value: str) -> ParsedValue:
    cleaned = " ".join(raw_value.strip().split())
    match = re.fullmatch(
        r"(?P<comparator><=|>=|<|>)?\s*(?P<number>\d+(?:,\d{3})*(?:\.\d+)?)",
        cleaned,
    )
    if not match:
        return ParsedValue(
            raw_value=cleaned,
            parsed_value=None,
            comparator=None,
            text_value=None,
        )

    comparator = match.group("comparator")
    number_text = match.group("number").replace(",", "")
    parsed_value = float(number_text)
    text_value = f"{comparator or ''}{number_text}" if comparator else None
    return ParsedValue(
        raw_value=cleaned,
        parsed_value=parsed_value,
        comparator=comparator,
        text_value=text_value,
    )


def _strip_yaml_string(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _load_metric_mappings_without_yaml(mapping_path: Path) -> Dict[str, Any]:
    source = ""
    taxonomy = ""
    metrics: Dict[str, Dict[str, str]] = {}
    current_metric: Optional[str] = None

    for raw_line in mapping_path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()

        if indent == 0:
            if stripped == "metrics:":
                continue
            key, value = stripped.split(":", 1)
            if key == "source":
                source = _strip_yaml_string(value)
            elif key == "taxonomy":
                taxonomy = _strip_yaml_string(value)
        elif indent == 2 and stripped.endswith(":"):
            current_metric = _strip_yaml_string(stripped[:-1])
            metrics[current_metric] = {}
        elif indent == 4 and current_metric:
            key, value = stripped.split(":", 1)
            metrics[current_metric][key.strip()] = _strip_yaml_string(value)

    return {"source": source, "taxonomy": taxonomy, "metrics": metrics}


def load_metric_mappings(mapping_path: str | Path) -> Dict[str, Any]:
    path = Path(mapping_path)
    try:
        import yaml  # type: ignore
    except ImportError:
        return _load_metric_mappings_without_yaml(path)

    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)

    return loaded or {"source": "", "taxonomy": "", "metrics": {}}


def extract_pdf_text_by_page(pdf_path: str | Path) -> List[Dict[str, Any]]:
    try:
        import fitz  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "PyMuPDF is required for PDF extraction. Install dependencies before running the CLI."
        ) from exc

    pages: List[Dict[str, Any]] = []
    document = fitz.open(str(pdf_path))
    try:
        for page_index, page in enumerate(document, start=1):
            pages.append({"page_number": page_index, "text": page.get_text("text") or ""})
    finally:
        document.close()

    return pages


def _iter_page_lines(page_texts: Sequence[Dict[str, Any]]) -> List[PageLine]:
    lines: List[PageLine] = []
    for page in page_texts:
        page_number = int(page["page_number"])
        for line_number, raw_line in enumerate(str(page.get("text", "")).splitlines(), start=1):
            text = " ".join(raw_line.split())
            if text:
                lines.append(PageLine(page_number=page_number, line_number=line_number, text=text))
    return lines


def _find_mapping_label(text: str, metric_specs: Dict[str, Dict[str, str]]) -> Optional[str]:
    lowered = text.casefold()
    for raw_label in sorted(metric_specs, key=len, reverse=True):
        if raw_label.casefold() in lowered:
            return raw_label
    return None


def _extract_reference_range(text: str) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    match = RANGE_RE.search(text)
    if not match:
        return None, None, None

    range_text = match.group(0)
    return float(match.group("low")), float(match.group("high")), range_text


def _find_measurement_value_match(text: str) -> Optional[re.Match[str]]:
    range_match = RANGE_RE.search(text)
    range_start = range_match.start() if range_match else None

    for match in VALUE_RE.finditer(text):
        token_start = match.start("comparator") if match.group("comparator") else match.start("number")
        token_end = match.end("number")

        if range_start is not None and token_start >= range_start:
            continue

        preceding_char = text[token_start - 1] if token_start > 0 else ""
        following_char = text[token_end] if token_end < len(text) else ""

        if preceding_char.isalpha():
            continue
        if following_char.isalpha() and not preceding_char.isspace():
            continue

        return match

    return None


def _extract_label_and_value(text: str) -> Optional[Dict[str, Any]]:
    value_match = _find_measurement_value_match(text)
    if not value_match:
        return None

    label = text[: value_match.start()].strip(" :-")
    if not re.search(r"[A-Za-z]{2,}", label):
        return None

    raw_value = value_match.group(0).strip()
    parsed_value = parse_numeric_value(raw_value)
    reference_low, reference_high, reference_range_text = _extract_reference_range(
        text[value_match.end() :]
    )

    unit_end = len(text)
    if reference_range_text:
        range_match = RANGE_RE.search(text[value_match.end() :])
        if range_match:
            unit_end = value_match.end() + range_match.start()

    unit = UNIT_CLEANUP_RE.sub("", text[value_match.end() :unit_end]).strip()
    return {
        "label": label,
        "parsed_value": parsed_value,
        "unit": unit or None,
        "reference_low": reference_low,
        "reference_high": reference_high,
        "reference_range_text": reference_range_text,
    }


def _build_observation_row(
    *,
    observation_id: str,
    person_id: str,
    document_id: str,
    observed_at: str,
    source: str,
    taxonomy: str,
    observation_type: str,
    raw_label: str,
    raw_value: str,
    normalized_label: str,
    parsed_value: Optional[float],
    unit: Optional[str],
    source_location: str,
    confidence: float,
    conversion_status: str,
    notes: str,
) -> Dict[str, Any]:
    return {
        "observation_id": observation_id,
        "person_id": person_id,
        "document_id": document_id,
        "observed_at": observed_at,
        "source": source,
        "taxonomy": taxonomy,
        "observation_type": observation_type,
        "raw_label": raw_label,
        "raw_value": raw_value,
        "normalized_label": normalized_label,
        "parsed_value": parsed_value,
        "unit": unit or "",
        "source_location": source_location,
        "confidence": confidence,
        "conversion_status": conversion_status,
        "notes": notes,
    }


def _make_deterministic_id(
    prefix: str,
    person_id: str,
    metric_date: str,
    name: str,
    seen_ids: Dict[str, int],
) -> str:
    base = f"{prefix}_{person_id}_{metric_date}_{normalize_id_component(name)}"
    count = seen_ids.get(base, 0) + 1
    seen_ids[base] = count
    if count == 1:
        return base
    return f"{base}_{count}"


def extract_mapped_observations(
    page_texts: Sequence[Dict[str, Any]],
    mappings: Dict[str, Any],
    *,
    person_id: str,
    document_id: str,
    metric_date: str,
    observation_id_tracker: Dict[str, int],
    warnings: List[str],
) -> Tuple[List[Dict[str, Any]], set[Tuple[int, int]], List[Dict[str, Any]]]:
    metric_specs = mappings.get("metrics", {})
    source = mappings.get("source", "")
    taxonomy = mappings.get("taxonomy", "")
    lines = _iter_page_lines(page_texts)

    observations: List[Dict[str, Any]] = []
    mapped_records: List[Dict[str, Any]] = []
    used_lines: set[Tuple[int, int]] = set()

    for index, line in enumerate(lines):
        if (line.page_number, line.line_number) in used_lines:
            continue

        raw_label = _find_mapping_label(line.text, metric_specs)
        if not raw_label:
            continue

        candidate_lines = [line]
        if index + 1 < len(lines):
            next_line = lines[index + 1]
            if next_line.page_number == line.page_number and next_line.line_number == line.line_number + 1:
                candidate_lines.append(next_line)

        parsed_row: Optional[Dict[str, Any]] = None
        consumed_lines = 1
        for candidate_count in (1, 2):
            candidate_text = " ".join(item.text for item in candidate_lines[:candidate_count])
            label_position = candidate_text.casefold().find(raw_label.casefold())
            if label_position < 0:
                continue
            trailing_text = candidate_text[label_position + len(raw_label) :]
            parsed_candidate = _extract_label_and_value(f"{raw_label} {trailing_text}")
            if parsed_candidate:
                parsed_row = parsed_candidate
                consumed_lines = candidate_count
                break

        if not parsed_row:
            warnings.append(
                f"Found mapped label '{raw_label}' on page {line.page_number}, line {line.line_number}, but could not parse a value."
            )
            continue

        metric_spec = metric_specs[raw_label]
        standard_name = metric_spec["standard_name"]
        observation_id = _make_deterministic_id(
            "obs",
            person_id,
            metric_date,
            standard_name,
            observation_id_tracker,
        )
        source_location = f"page={line.page_number};line={line.line_number}"
        if consumed_lines == 2:
            source_location = f"page={line.page_number};line={line.line_number}-{line.line_number + 1}"

        parsed_value: ParsedValue = parsed_row["parsed_value"]
        unit = metric_spec.get("unit") or parsed_row.get("unit")
        notes_parts = []
        if parsed_row.get("reference_range_text"):
            notes_parts.append(f"reference_range={parsed_row['reference_range_text']}")
        if raw_label != standard_name:
            notes_parts.append(f"mapped_from={raw_label}")

        observation = _build_observation_row(
            observation_id=observation_id,
            person_id=person_id,
            document_id=document_id,
            observed_at=metric_date,
            source=source,
            taxonomy=taxonomy,
            observation_type="lab_result",
            raw_label=raw_label,
            raw_value=parsed_value.raw_value,
            normalized_label=standard_name,
            parsed_value=parsed_value.parsed_value,
            unit=unit,
            source_location=source_location,
            confidence=1.0 if consumed_lines == 1 else 0.95,
            conversion_status="converted",
            notes="; ".join(notes_parts),
        )
        observations.append(observation)
        mapped_records.append(
            {
                "observation": observation,
                "metric_name": standard_name,
                "category": metric_spec["category"],
                "unit": unit or "",
                "reference_low": parsed_row["reference_low"],
                "reference_high": parsed_row["reference_high"],
                "text_value": parsed_value.text_value,
                "parsed_value": parsed_value.parsed_value,
            }
        )

        for consumed_line in candidate_lines[:consumed_lines]:
            used_lines.add((consumed_line.page_number, consumed_line.line_number))

    return observations, used_lines, mapped_records


def _determine_status(
    value: Optional[float], reference_low: Optional[float], reference_high: Optional[float]
) -> str:
    if value is None or reference_low is None or reference_high is None:
        return "tracked"
    if value < reference_low:
        return "low"
    if value > reference_high:
        return "high"
    return "normal"


def build_health_metrics(
    mapped_records: Sequence[Dict[str, Any]],
    *,
    person_id: str,
    document_id: str,
    metric_date: str,
    metric_id_tracker: Dict[str, int],
    source: str,
) -> List[Dict[str, Any]]:
    metrics: List[Dict[str, Any]] = []
    for record in mapped_records:
        observation = record["observation"]
        metric_name = record["metric_name"]
        metric_id = _make_deterministic_id(
            "m",
            person_id,
            metric_date,
            metric_name,
            metric_id_tracker,
        )
        metrics.append(
            {
                "metric_id": metric_id,
                "person_id": person_id,
                "document_id": document_id,
                "observation_id": observation["observation_id"],
                "metric_date": metric_date,
                "source": source,
                "category": record["category"],
                "metric_name": metric_name,
                "value": record["parsed_value"],
                "text_value": record["text_value"] or "",
                "unit": record["unit"],
                "reference_low": record["reference_low"],
                "reference_high": record["reference_high"],
                "status": _determine_status(
                    record["parsed_value"],
                    record["reference_low"],
                    record["reference_high"],
                ),
                "notes": observation["notes"],
            }
        )
    return metrics


def capture_unconverted_observations(
    page_texts: Sequence[Dict[str, Any]],
    mappings: Dict[str, Any],
    *,
    person_id: str,
    document_id: str,
    metric_date: str,
    used_lines: set[Tuple[int, int]],
    observation_id_tracker: Dict[str, int],
) -> Tuple[List[Dict[str, Any]], int]:
    metric_specs = mappings.get("metrics", {})
    source = mappings.get("source", "")
    taxonomy = mappings.get("taxonomy", "")
    lines = _iter_page_lines(page_texts)
    observations: List[Dict[str, Any]] = []
    skipped_lines_count = 0

    for line in lines:
        line_key = (line.page_number, line.line_number)
        if line_key in used_lines:
            continue

        if not LAB_RESULT_SIGNAL_RE.search(line.text):
            skipped_lines_count += 1
            continue

        matching_mapping_label = _find_mapping_label(line.text, metric_specs)
        extracted = _extract_label_and_value(line.text)

        if extracted:
            raw_label = matching_mapping_label or extracted["label"]
            normalized_label = extracted["label"]
            parsed_value: ParsedValue = extracted["parsed_value"]
            unit = extracted.get("unit")
            notes = []
            if extracted.get("reference_range_text"):
                notes.append(f"reference_range={extracted['reference_range_text']}")
            if matching_mapping_label:
                notes.append("mapped_label_present_but_not_converted")
            else:
                notes.append("no_mapping_found")

            observation_id = _make_deterministic_id(
                "obs",
                person_id,
                metric_date,
                normalized_label,
                observation_id_tracker,
            )
            observations.append(
                _build_observation_row(
                    observation_id=observation_id,
                    person_id=person_id,
                    document_id=document_id,
                    observed_at=metric_date,
                    source=source,
                    taxonomy=taxonomy,
                    observation_type="lab_result",
                    raw_label=raw_label,
                    raw_value=parsed_value.raw_value,
                    normalized_label=normalized_label,
                    parsed_value=parsed_value.parsed_value,
                    unit=unit,
                    source_location=f"page={line.page_number};line={line.line_number}",
                    confidence=0.65,
                    conversion_status="unconverted",
                    notes="; ".join(notes),
                )
            )
            continue

        value_match = VALUE_RE.search(line.text)
        if value_match:
            parsed_value = parse_numeric_value(value_match.group(0))
            observation_id = _make_deterministic_id(
                "obs",
                person_id,
                metric_date,
                f"unidentified_page_{line.page_number}_line_{line.line_number}",
                observation_id_tracker,
            )
            observations.append(
                _build_observation_row(
                    observation_id=observation_id,
                    person_id=person_id,
                    document_id=document_id,
                    observed_at=metric_date,
                    source=source,
                    taxonomy="unidentified",
                    observation_type="unknown_line",
                    raw_label=line.text,
                    raw_value=parsed_value.raw_value,
                    normalized_label="",
                    parsed_value=parsed_value.parsed_value,
                    unit="",
                    source_location=f"page={line.page_number};line={line.line_number}",
                    confidence=0.35,
                    conversion_status="unidentified",
                    notes="lab-like line could not be classified",
                )
            )
            continue

        skipped_lines_count += 1

    return observations, skipped_lines_count


def write_csv(
    rows: Sequence[Dict[str, Any]],
    fieldnames: Sequence[str],
    output_path: str | Path,
) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def write_extraction_report(report: Dict[str, Any], output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def extract_report_data(
    *,
    page_texts: Sequence[Dict[str, Any]],
    person_id: str,
    document_id: str,
    metric_date: str,
    mapping_path: str | Path,
) -> Dict[str, Any]:
    mappings = load_metric_mappings(mapping_path)
    warnings: List[str] = []
    observation_id_tracker: Dict[str, int] = {}
    metric_id_tracker: Dict[str, int] = {}

    observations, used_lines, mapped_records = extract_mapped_observations(
        page_texts,
        mappings,
        person_id=person_id,
        document_id=document_id,
        metric_date=metric_date,
        observation_id_tracker=observation_id_tracker,
        warnings=warnings,
    )
    health_metrics = build_health_metrics(
        mapped_records,
        person_id=person_id,
        document_id=document_id,
        metric_date=metric_date,
        metric_id_tracker=metric_id_tracker,
        source=mappings.get("source", ""),
    )
    unconverted_observations, skipped_lines_count = capture_unconverted_observations(
        page_texts,
        mappings,
        person_id=person_id,
        document_id=document_id,
        metric_date=metric_date,
        used_lines=used_lines,
        observation_id_tracker=observation_id_tracker,
    )

    unconverted_count = sum(
        1 for row in unconverted_observations if row["conversion_status"] == "unconverted"
    )
    unidentified_count = sum(
        1 for row in unconverted_observations if row["conversion_status"] == "unidentified"
    )
    report = {
        "total_pages_read": len(page_texts),
        "mapped_metrics_found": len(observations),
        "health_metrics_created": len(health_metrics),
        "unconverted_observations_count": unconverted_count,
        "unidentified_count": unidentified_count,
        "skipped_lines_count": skipped_lines_count,
        "warnings": warnings,
    }
    return {
        "observations": observations,
        "health_metrics": health_metrics,
        "unconverted_observations": unconverted_observations,
        "report": report,
    }


def _validate_iso_date(value: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise argparse.ArgumentTypeError("Dates must use YYYY-MM-DD format.")
    return value


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract mapped and unconverted observations from a Tata 1mg lab report PDF."
    )
    parser.add_argument("--pdf-path", required=True)
    parser.add_argument("--person-id", required=True)
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--metric-date", required=True, type=_validate_iso_date)
    parser.add_argument("--output-observations-csv", required=True)
    parser.add_argument("--output-health-metrics-csv", required=True)
    parser.add_argument("--output-unconverted-observations-csv", required=True)
    parser.add_argument("--output-extraction-report-json", required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[3]
    mapping_path = repo_root / "config/metric_mappings/tata_1mg_lab_metrics.yaml"
    page_texts = extract_pdf_text_by_page(args.pdf_path)
    extraction = extract_report_data(
        page_texts=page_texts,
        person_id=args.person_id,
        document_id=args.document_id,
        metric_date=args.metric_date,
        mapping_path=mapping_path,
    )

    write_csv(extraction["observations"], OBSERVATION_FIELDS, args.output_observations_csv)
    write_csv(
        extraction["health_metrics"],
        HEALTH_METRIC_FIELDS,
        args.output_health_metrics_csv,
    )
    write_csv(
        extraction["unconverted_observations"],
        OBSERVATION_FIELDS,
        args.output_unconverted_observations_csv,
    )
    write_extraction_report(extraction["report"], args.output_extraction_report_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

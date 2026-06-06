from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from io import StringIO
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from family_health_lake.utils import load_yaml_config, normalize_id_component


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
    "raw_text",
    "surrounding_text",
    "failure_reason",
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

MULTILINE_TEXT_FIELDS = {"raw_text", "surrounding_text", "notes"}

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
ONE_SIDED_RANGE_RE = re.compile(
    r"(?P<comparator><=|>=|<|>)\s*(?P<number>\d+(?:,\d{3})*(?:\.\d+)?)"
)
NOISE_PREFIXES = (
    "customer name",
    "comment:",
    "report date",
    "sample type",
    "this test has been performed at",
    "method",
)
NOISE_CONTAINS = (
    "page ",
    "report generated",
    "laboratory",
    "lab address",
    "reference lab",
)
KNOWN_UNITS = {
    "mg/dl",
    "ng/dl",
    "pg/ml",
    "iu/ml",
    "u/l",
    "µiu/ml",
    "ml/min/1.73m2",
    "%",
    "g/dl",
    "mili/cu.mm",
    "million/cu.mm",
    "lakhs/cu.mm",
    "cells/cu.mm",
    "fl",
    "pg",
}


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


@dataclass(frozen=True)
class ReferenceRange:
    low: Optional[float]
    high: Optional[float]
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class ValueContext:
    parsed_value: ParsedValue
    unit: Optional[str]
    reference_range: Optional[ReferenceRange]
    token_start: int
    token_end: int


@dataclass(frozen=True)
class UnmappedLabResultCandidate:
    raw_label: str
    parsed_value: ParsedValue
    unit: Optional[str]
    reference_low: Optional[float]
    reference_high: Optional[float]
    reference_range_text: Optional[str]
    last_consumed_offset: int
    failure_reason: str


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


def _normalize_label_for_matching(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-zA-Z0-9]+", "", ascii_value.casefold())


def load_metric_mappings(mapping_path: str | Path) -> Dict[str, Any]:
    return load_yaml_config(mapping_path)


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
    normalized_text = _normalize_label_for_matching(text)
    for raw_label in sorted(metric_specs, key=len, reverse=True):
        if _normalize_label_for_matching(raw_label) in normalized_text:
            return raw_label
    return None


def _extract_reference_range(text: str) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    parsed_range = _parse_reference_range(text)
    if not parsed_range:
        return None, None, None

    return parsed_range.low, parsed_range.high, parsed_range.text


def _parse_reference_range(text: str) -> Optional[ReferenceRange]:
    range_match = RANGE_RE.search(text)
    if range_match:
        return ReferenceRange(
            low=float(range_match.group("low")),
            high=float(range_match.group("high")),
            text=range_match.group(0),
            start=range_match.start(),
            end=range_match.end(),
        )

    one_sided_match = ONE_SIDED_RANGE_RE.search(text)
    if not one_sided_match:
        return None

    comparator = one_sided_match.group("comparator")
    number = float(one_sided_match.group("number").replace(",", ""))
    if comparator in {"<", "<="}:
        low = None
        high = number
    else:
        low = number
        high = None

    return ReferenceRange(
        low=low,
        high=high,
        text=one_sided_match.group(0),
        start=one_sided_match.start(),
        end=one_sided_match.end(),
    )


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


def _extract_value_context(text: str) -> Optional[ValueContext]:
    value_match = _find_measurement_value_match(text)
    if not value_match:
        return None

    token_start = value_match.start("comparator") if value_match.group("comparator") else value_match.start("number")
    token_end = value_match.end("number")
    raw_value = value_match.group(0).strip()
    parsed_value = parse_numeric_value(raw_value)
    remainder = text[token_end:]
    reference_range = _parse_reference_range(remainder)

    unit_end = len(text)
    if reference_range:
        unit_end = token_end + reference_range.start

    unit = UNIT_CLEANUP_RE.sub("", text[token_end:unit_end]).strip()
    return ValueContext(
        parsed_value=parsed_value,
        unit=unit or None,
        reference_range=reference_range,
        token_start=token_start,
        token_end=token_end,
    )


def _extract_label_and_value(text: str) -> Optional[Dict[str, Any]]:
    value_context = _extract_value_context(text)
    if not value_context:
        return None

    label = text[: value_context.token_start].strip(" :-")
    if not re.search(r"[A-Za-z]{2,}", label):
        return None

    reference_range = value_context.reference_range
    return {
        "label": label,
        "parsed_value": value_context.parsed_value,
        "unit": value_context.unit,
        "reference_low": reference_range.low if reference_range else None,
        "reference_high": reference_range.high if reference_range else None,
        "reference_range_text": reference_range.text if reference_range else None,
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
    raw_text: str = "",
    surrounding_text: str = "",
    failure_reason: str = "",
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
        "raw_text": raw_text,
        "surrounding_text": surrounding_text,
        "failure_reason": failure_reason,
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


def _is_metric_repeatable(metric_spec: Dict[str, Any]) -> bool:
    repeatable = metric_spec.get("repeatable", False)
    if isinstance(repeatable, bool):
        return repeatable
    if isinstance(repeatable, str):
        return repeatable.strip().lower() in {"1", "true", "yes", "y"}
    return bool(repeatable)


def _collect_candidate_lines(
    lines: Sequence[PageLine],
    start_index: int,
    metric_specs: Dict[str, Dict[str, Any]],
    max_lines: int = 6,
) -> List[PageLine]:
    anchor_line = lines[start_index]
    candidate_lines = [anchor_line]

    for next_line in lines[start_index + 1 :]:
        if len(candidate_lines) >= max_lines:
            break
        if next_line.page_number != anchor_line.page_number:
            break
        if next_line.line_number != candidate_lines[-1].line_number + 1:
            break
        if _find_mapping_label(next_line.text, metric_specs):
            break
        candidate_lines.append(next_line)

    return candidate_lines


def _build_raw_text(candidate_lines: Sequence[PageLine], last_consumed_offset: int) -> str:
    consumed_lines = candidate_lines[: last_consumed_offset + 1]
    return "\n".join(line.text for line in consumed_lines)


def _build_surrounding_text(lines: Sequence[PageLine], start_index: int, end_index: int) -> str:
    first_index = max(0, start_index - 1)
    last_index = min(len(lines) - 1, end_index + 1)
    return "\n".join(lines[index].text for index in range(first_index, last_index + 1))


def _looks_like_noise(text: str) -> bool:
    lowered = text.casefold()
    if lowered.startswith(NOISE_PREFIXES):
        return True
    if re.search(r"page\s+\d+\s+of\s+\d+", lowered):
        return True
    if any(token in lowered for token in NOISE_CONTAINS):
        return True
    if len(lowered.split()) >= 10 and not LAB_RESULT_SIGNAL_RE.search(text):
        return True
    return False


def _looks_like_plausible_lab_label(text: str) -> bool:
    label = text.strip(" :-")
    if not label or len(label) > 80:
        return False
    if _looks_like_noise(label):
        return False
    if not re.search(r"[A-Za-z]{2,}", label):
        return False
    if any(char in label for char in "@#[]{}"):
        return False
    if len(label.split()) > 6:
        return False
    return True


def _extract_unit_from_text(text: str) -> Optional[str]:
    cleaned = UNIT_CLEANUP_RE.sub("", text).strip()
    if not cleaned:
        return None
    lowered = cleaned.casefold()
    if lowered in {unit.casefold() for unit in KNOWN_UNITS}:
        return cleaned
    return None


def _parse_mapped_metric_window(
    raw_label: str,
    candidate_lines: Sequence[PageLine],
) -> Optional[Dict[str, Any]]:
    label_line = candidate_lines[0]
    label_position = label_line.text.casefold().find(raw_label.casefold())
    if label_position < 0:
        return None

    segments: List[Tuple[int, str]] = []
    trailing_text = label_line.text[label_position + len(raw_label) :].strip()
    if trailing_text:
        segments.append((0, trailing_text))

    for line_offset, candidate_line in enumerate(candidate_lines[1:], start=1):
        segments.append((line_offset, candidate_line.text))

    for segment_index, segment_text in segments:
        value_context = _extract_value_context(segment_text)
        if not value_context:
            continue

        reference_range = value_context.reference_range
        reference_line_offset = segment_index
        if not reference_range:
            for next_offset, next_text in segments:
                if next_offset <= segment_index:
                    continue
                reference_range = _parse_reference_range(next_text.strip())
                if reference_range:
                    reference_line_offset = next_offset
                    break

        return {
            "parsed_value": value_context.parsed_value,
            "unit": value_context.unit,
            "reference_low": reference_range.low if reference_range else None,
            "reference_high": reference_range.high if reference_range else None,
            "reference_range_text": reference_range.text if reference_range else None,
            "last_consumed_offset": max(segment_index, reference_line_offset),
        }

    return None


def _parse_unmapped_lab_result_window(
    candidate_lines: Sequence[PageLine],
) -> Optional[UnmappedLabResultCandidate]:
    label_line = candidate_lines[0].text.strip()
    same_line = _extract_label_and_value(label_line)
    if same_line and _looks_like_plausible_lab_label(same_line["label"]):
        parsed_value: ParsedValue = same_line["parsed_value"]
        return UnmappedLabResultCandidate(
            raw_label=same_line["label"],
            parsed_value=parsed_value,
            unit=same_line["unit"],
            reference_low=same_line["reference_low"],
            reference_high=same_line["reference_high"],
            reference_range_text=same_line["reference_range_text"],
            last_consumed_offset=0,
            failure_reason="raw_label_not_mapped",
        )

    if not _looks_like_plausible_lab_label(label_line):
        return None

    value_context: Optional[ValueContext] = None
    value_offset: Optional[int] = None
    reference_range: Optional[ReferenceRange] = None
    reference_offset: Optional[int] = None

    for line_offset, candidate_line in enumerate(candidate_lines[1:], start=1):
        value_context = _extract_value_context(candidate_line.text)
        if value_context:
            value_offset = line_offset
            reference_range = value_context.reference_range
            reference_offset = line_offset if reference_range else None
            break

    if not value_context or value_offset is None:
        return None

    if not reference_range:
        for line_offset, candidate_line in enumerate(candidate_lines[value_offset + 1 :], start=value_offset + 1):
            reference_range = _parse_reference_range(candidate_line.text)
            if reference_range:
                reference_offset = line_offset
                break

    last_consumed_offset = max(value_offset, reference_offset or value_offset)
    return UnmappedLabResultCandidate(
        raw_label=label_line.strip(" :-"),
        parsed_value=value_context.parsed_value,
        unit=value_context.unit or _extract_unit_from_text(candidate_lines[value_offset].text),
        reference_low=reference_range.low if reference_range else None,
        reference_high=reference_range.high if reference_range else None,
        reference_range_text=reference_range.text if reference_range else None,
        last_consumed_offset=last_consumed_offset,
        failure_reason="raw_label_not_mapped",
    )


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

        candidate_lines = _collect_candidate_lines(lines, index, metric_specs)
        parsed_row = _parse_mapped_metric_window(raw_label, candidate_lines)
        consumed_lines = (parsed_row["last_consumed_offset"] + 1) if parsed_row else 1

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
        elif consumed_lines > 2:
            source_location = f"page={line.page_number};line={line.line_number}-{line.line_number + consumed_lines - 1}"

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
            raw_text=_build_raw_text(candidate_lines, consumed_lines - 1),
            surrounding_text=_build_surrounding_text(lines, index, index + consumed_lines - 1),
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
                "repeatable": _is_metric_repeatable(metric_spec),
            }
        )

        for consumed_line in candidate_lines[:consumed_lines]:
            used_lines.add((consumed_line.page_number, consumed_line.line_number))

    return observations, used_lines, mapped_records


def _determine_status(
    value: Optional[float], reference_low: Optional[float], reference_high: Optional[float]
) -> str:
    if value is None:
        return "tracked"
    if reference_low is None and reference_high is None:
        return "tracked"
    if reference_low is not None and value < reference_low:
        return "low"
    if reference_high is not None and value > reference_high:
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
    warnings: List[str],
) -> Tuple[List[Dict[str, Any]], int]:
    metrics: List[Dict[str, Any]] = []
    seen_records: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}
    seen_signatures: Dict[Tuple[str, str, str, str], set[Tuple[Optional[float], str, str]]] = {}
    duplicate_observations_skipped = 0

    for record in mapped_records:
        observation = record["observation"]
        metric_name = record["metric_name"]
        metric_key = (person_id, document_id, metric_date, metric_name)
        duplicate_signature = (
            record["parsed_value"],
            record["text_value"] or "",
            record["unit"],
        )
        existing_record = seen_records.get(metric_key)
        is_repeatable = bool(record.get("repeatable"))
        metric_signatures = seen_signatures.setdefault(metric_key, set())

        if duplicate_signature in metric_signatures:
            duplicate_observations_skipped += 1
            continue
        if existing_record and not is_repeatable:
            duplicate_observations_skipped += 1
            warnings.append(
                f"Skipped conflicting duplicate for metric '{metric_name}' in document '{document_id}'. "
                f"Kept observation '{existing_record['observation']['observation_id']}' and skipped "
                f"'{observation['observation_id']}'."
            )
            continue

        metric_id = _make_deterministic_id(
            "m",
            person_id,
            metric_date,
            metric_name,
            metric_id_tracker,
        )
        metric_row = {
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
        metrics.append(metric_row)
        if not existing_record:
            seen_records[metric_key] = record
        metric_signatures.add(duplicate_signature)
    return metrics, duplicate_observations_skipped


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
    skipped_noise_count = 0

    line_index = 0
    while line_index < len(lines):
        line = lines[line_index]
        line_key = (line.page_number, line.line_number)
        if line_key in used_lines:
            line_index += 1
            continue

        if _looks_like_noise(line.text):
            skipped_lines_count += 1
            skipped_noise_count += 1
            line_index += 1
            continue

        candidate_lines = _collect_candidate_lines(lines, line_index, metric_specs, max_lines=3)
        unmapped_candidate = _parse_unmapped_lab_result_window(candidate_lines)
        if unmapped_candidate:
            last_index = line_index + unmapped_candidate.last_consumed_offset
            observation_id = _make_deterministic_id(
                "obs",
                person_id,
                metric_date,
                unmapped_candidate.raw_label,
                observation_id_tracker,
            )
            notes = []
            if unmapped_candidate.reference_range_text:
                notes.append(f"reference_range={unmapped_candidate.reference_range_text}")
            notes.append("no_mapping_found")
            observations.append(
                _build_observation_row(
                    observation_id=observation_id,
                    person_id=person_id,
                    document_id=document_id,
                    observed_at=metric_date,
                    source=source,
                    taxonomy=taxonomy,
                    observation_type="lab_result",
                    raw_label=unmapped_candidate.raw_label,
                    raw_value=unmapped_candidate.parsed_value.raw_value,
                    normalized_label=unmapped_candidate.raw_label,
                    parsed_value=unmapped_candidate.parsed_value.parsed_value,
                    unit=unmapped_candidate.unit,
                    source_location=f"page={line.page_number};line={line.line_number}-{candidate_lines[unmapped_candidate.last_consumed_offset].line_number}",
                    confidence=0.7 if unmapped_candidate.last_consumed_offset else 0.65,
                    conversion_status="unconverted",
                    raw_text=_build_raw_text(candidate_lines, unmapped_candidate.last_consumed_offset),
                    surrounding_text=_build_surrounding_text(lines, line_index, last_index),
                    failure_reason=unmapped_candidate.failure_reason,
                    notes="; ".join(notes),
                )
            )
            line_index = last_index + 1
            continue

        if not LAB_RESULT_SIGNAL_RE.search(line.text):
            skipped_lines_count += 1
            line_index += 1
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
                    raw_text=line.text,
                    surrounding_text=_build_surrounding_text(lines, line_index, line_index),
                    failure_reason="raw_label_not_mapped" if not matching_mapping_label else "",
                    notes="; ".join(notes),
                )
            )
            line_index += 1
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
                    raw_text=line.text,
                    surrounding_text=_build_surrounding_text(lines, line_index, line_index),
                    failure_reason="unable_to_classify",
                    notes="lab-like line could not be classified",
                )
            )
            line_index += 1
            continue

        skipped_lines_count += 1
        line_index += 1

    return observations, skipped_lines_count, skipped_noise_count


def write_csv(
    rows: Sequence[Dict[str, Any]],
    fieldnames: Sequence[str],
    output_path: str | Path,
) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            quoting=csv.QUOTE_MINIMAL,
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(_sanitize_row_for_csv(row, fieldnames))


def _normalize_csv_text(value: Any) -> str:
    text = "" if value is None else str(value)
    return " ".join(text.replace("\r", " ").replace("\n", " ").split())


def _sanitize_row_for_csv(
    row: Dict[str, Any],
    fieldnames: Sequence[str],
) -> Dict[str, Any]:
    sanitized: Dict[str, Any] = {}
    for field in fieldnames:
        value = row.get(field, "")
        if field in MULTILINE_TEXT_FIELDS:
            sanitized[field] = _normalize_csv_text(value)
        else:
            sanitized[field] = "" if value is None else value
    return sanitized


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
        warnings=warnings,
    )
    duplicate_observations_skipped = health_metrics[1]
    health_metrics_rows = health_metrics[0]
    unconverted_observations, skipped_lines_count, skipped_noise_count = capture_unconverted_observations(
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
    unmapped_lab_result_count = sum(
        1
        for row in unconverted_observations
        if row["conversion_status"] == "unconverted"
        and row["failure_reason"] == "raw_label_not_mapped"
        and row["taxonomy"] == mappings.get("taxonomy", "")
    )
    unidentified_count = sum(
        1 for row in unconverted_observations if row["conversion_status"] == "unidentified"
    )
    report = {
        "total_pages_read": len(page_texts),
        "mapped_metrics_found": len(observations),
        "health_metrics_created": len(health_metrics_rows),
        "unconverted_observations_count": unconverted_count,
        "unmapped_lab_result_count": unmapped_lab_result_count,
        "unidentified_count": unidentified_count,
        "skipped_noise_count": skipped_noise_count,
        "duplicate_observations_skipped": duplicate_observations_skipped,
        "skipped_lines_count": skipped_lines_count,
        "warnings": warnings,
    }
    return {
        "observations": observations,
        "health_metrics": health_metrics_rows,
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

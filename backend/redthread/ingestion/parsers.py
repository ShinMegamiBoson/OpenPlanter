"""File parsers for CSV, JSON, and XLSX with a unified ParseResult interface.

Provides parse_file() as the single entry point. Implementations:
- CSV: csv.DictReader with chardet encoding detection, BOM handling
- JSON: Supports both JSON array of objects and JSON Lines
- XLSX: openpyxl in read-only mode, first row as headers

Best-effort parsing: malformed rows produce warnings, don't abort.
File size guard: rejects files > 50 MB.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import chardet
import openpyxl

# 50 MB in bytes
_MAX_FILE_SIZE = 50 * 1024 * 1024

_SUPPORTED_TYPES = {"csv", "json", "xlsx"}


@dataclass
class ParseResult:
    """Result of parsing a data file.

    Attributes:
        rows: List of column:value dicts (one per parsed row).
        column_names: Ordered list of column/field names.
        row_count: Number of successfully parsed rows.
        warnings: Validation issues encountered during parsing.
        file_type: The type of file that was parsed (csv/json/xlsx).
    """

    rows: list[dict[str, Any]]
    column_names: list[str]
    row_count: int
    warnings: list[str] = field(default_factory=list)
    file_type: str = ""


def parse_file(path: Path, file_type: str) -> ParseResult:
    """Parse a data file and return a ParseResult.

    Args:
        path: Path to the file on disk.
        file_type: One of 'csv', 'json', 'xlsx'.

    Returns:
        ParseResult with rows, column_names, row_count, warnings.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the file type is unsupported or the file exceeds 50 MB.
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    file_type = file_type.lower().strip()

    if file_type not in _SUPPORTED_TYPES:
        raise ValueError(
            f"Unsupported file type: '{file_type}'. "
            f"Supported types: {', '.join(sorted(_SUPPORTED_TYPES))}"
        )

    # File size guard
    file_size = path.stat().st_size
    if file_size > _MAX_FILE_SIZE:
        raise ValueError(
            f"File size ({file_size / (1024 * 1024):.1f} MB) exceeds the 50 MB limit."
        )

    if file_type == "csv":
        return _parse_csv(path)
    elif file_type == "json":
        return _parse_json(path)
    elif file_type == "xlsx":
        return _parse_xlsx(path)

    # Unreachable, but satisfies type checker
    raise ValueError(f"Unsupported file type: '{file_type}'")  # pragma: no cover


# ---------------------------------------------------------------------------
# CSV Parser
# ---------------------------------------------------------------------------


def _detect_encoding(raw_bytes: bytes) -> str:
    """Detect the encoding of raw bytes using chardet.

    Returns a safe encoding string. Falls back to 'utf-8' if detection fails.
    """
    # Check for UTF-8 BOM
    if raw_bytes[:3] == b"\xef\xbb\xbf":
        return "utf-8-sig"

    result = chardet.detect(raw_bytes)
    encoding = result.get("encoding")
    if encoding is None:
        return "utf-8"
    # Normalize common aliases
    enc_lower = encoding.lower()
    if enc_lower in ("ascii", "utf-8", "utf8"):
        return "utf-8"
    return encoding


def _parse_csv(path: Path) -> ParseResult:
    """Parse a CSV file with encoding detection and best-effort row handling."""
    raw_bytes = path.read_bytes()

    # Empty file check
    if len(raw_bytes.strip()) == 0:
        return ParseResult(
            rows=[],
            column_names=[],
            row_count=0,
            warnings=["File is empty"],
            file_type="csv",
        )

    encoding = _detect_encoding(raw_bytes)
    text = raw_bytes.decode(encoding, errors="replace")

    # Sniff delimiter
    try:
        sample = text[:8192]
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    fieldnames = reader.fieldnames

    if not fieldnames:
        return ParseResult(
            rows=[],
            column_names=[],
            row_count=0,
            warnings=["File is empty or has no header row"],
            file_type="csv",
        )

    # Clean up fieldnames (strip whitespace, BOM remnants)
    column_names = [name.strip().lstrip("\ufeff") for name in fieldnames]

    rows: list[dict[str, Any]] = []
    warnings: list[str] = []

    for row_idx, row in enumerate(reader, start=2):  # data rows start at line 2
        # DictReader with restkey/restval handles mismatched columns
        # Check for extra or missing fields
        if reader.restkey in row:  # type: ignore[operator]
            warnings.append(
                f"Row {row_idx}: has extra columns (expected {len(column_names)} columns)"
            )
        if None in row.values():
            # Some columns are None => row has fewer columns than header
            warnings.append(
                f"Row {row_idx}: has fewer columns than header (expected {len(column_names)})"
            )

        # Re-map the row to use cleaned column names
        cleaned: dict[str, Any] = {}
        for orig_name, clean_name in zip(fieldnames, column_names):
            cleaned[clean_name] = row.get(orig_name, "")
        rows.append(cleaned)

    return ParseResult(
        rows=rows,
        column_names=column_names,
        row_count=len(rows),
        warnings=warnings,
        file_type="csv",
    )


# ---------------------------------------------------------------------------
# JSON Parser
# ---------------------------------------------------------------------------


def _parse_json(path: Path) -> ParseResult:
    """Parse a JSON file (array of objects or JSON Lines).

    Tries JSON array first, then falls back to JSON Lines.
    """
    raw_bytes = path.read_bytes()

    # Empty file check
    if len(raw_bytes.strip()) == 0:
        return ParseResult(
            rows=[],
            column_names=[],
            row_count=0,
            warnings=["File is empty"],
            file_type="json",
        )

    encoding = _detect_encoding(raw_bytes)
    text = raw_bytes.decode(encoding, errors="replace").strip()

    # Try parsing as a JSON array first
    if text.startswith("["):
        return _parse_json_array(text)

    # Try parsing as a single JSON object
    if text.startswith("{") and "\n" not in text:
        return _parse_json_array(f"[{text}]")

    # Fall back to JSON Lines
    return _parse_json_lines(text)


def _parse_json_array(text: str) -> ParseResult:
    """Parse a JSON array of objects."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return ParseResult(
            rows=[],
            column_names=[],
            row_count=0,
            warnings=[f"Failed to parse JSON: {e}"],
            file_type="json",
        )

    if not isinstance(data, list):
        return ParseResult(
            rows=[],
            column_names=[],
            row_count=0,
            warnings=["JSON root is not an array and not a JSON Lines file"],
            file_type="json",
        )

    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    all_keys: set[str] = set()
    first_keys: set[str] | None = None

    for idx, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            warnings.append(f"Row {idx}: not an object, skipped")
            continue
        rows.append(dict(item))
        keys = set(item.keys())
        all_keys.update(keys)
        if first_keys is None:
            first_keys = keys
        elif keys != first_keys:
            warnings.append(
                f"Row {idx}: schema differs from first row "
                f"(extra: {keys - first_keys}, missing: {first_keys - keys})"
            )

    # Use ordered union of all keys as column_names, preserving first-seen order
    column_names = _ordered_keys(rows)

    return ParseResult(
        rows=rows,
        column_names=column_names,
        row_count=len(rows),
        warnings=warnings,
        file_type="json",
    )


def _parse_json_lines(text: str) -> ParseResult:
    """Parse JSON Lines (one object per line)."""
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    first_keys: set[str] | None = None

    for line_num, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue

        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            warnings.append(f"Line {line_num}: malformed JSON, skipped")
            continue

        if not isinstance(obj, dict):
            warnings.append(f"Line {line_num}: not an object, skipped")
            continue

        rows.append(dict(obj))
        keys = set(obj.keys())
        if first_keys is None:
            first_keys = keys
        elif keys != first_keys:
            warnings.append(
                f"Line {line_num}: schema differs from first row "
                f"(extra: {keys - first_keys}, missing: {first_keys - keys})"
            )

    if not rows and warnings:
        # All lines were malformed
        return ParseResult(
            rows=[],
            column_names=[],
            row_count=0,
            warnings=warnings,
            file_type="json",
        )

    column_names = _ordered_keys(rows)

    return ParseResult(
        rows=rows,
        column_names=column_names,
        row_count=len(rows),
        warnings=warnings,
        file_type="json",
    )


def _ordered_keys(rows: list[dict[str, Any]]) -> list[str]:
    """Extract ordered unique keys from a list of dicts, preserving first-seen order."""
    seen: set[str] = set()
    result: list[str] = []
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                result.append(key)
    return result


# ---------------------------------------------------------------------------
# XLSX Parser
# ---------------------------------------------------------------------------


def _parse_xlsx(path: Path) -> ParseResult:
    """Parse an XLSX file using openpyxl in read-only mode.

    First row is treated as headers. Empty rows produce warnings.
    """
    try:
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    except Exception as e:
        return ParseResult(
            rows=[],
            column_names=[],
            row_count=0,
            warnings=[f"Failed to open XLSX file: {e}"],
            file_type="xlsx",
        )

    try:
        ws = wb.active
        if ws is None:
            return ParseResult(
                rows=[],
                column_names=[],
                row_count=0,
                warnings=["XLSX file has no active sheet"],
                file_type="xlsx",
            )

        rows_iter = ws.iter_rows()

        # Read header row
        try:
            header_row = next(rows_iter)
        except StopIteration:
            return ParseResult(
                rows=[],
                column_names=[],
                row_count=0,
                warnings=["File is empty or has no header row"],
                file_type="xlsx",
            )

        column_names = [
            str(cell.value).strip() if cell.value is not None else f"column_{i}"
            for i, cell in enumerate(header_row, start=1)
        ]

        rows: list[dict[str, Any]] = []
        warnings: list[str] = []

        for row_idx, row in enumerate(rows_iter, start=2):
            values = [cell.value for cell in row]

            # Check for empty row (all values are None)
            if all(v is None for v in values):
                warnings.append(f"Row {row_idx}: empty row, skipped")
                continue

            row_dict: dict[str, Any] = {}
            for col_name, value in zip(column_names, values):
                row_dict[col_name] = value
            rows.append(row_dict)

        return ParseResult(
            rows=rows,
            column_names=column_names,
            row_count=len(rows),
            warnings=warnings,
            file_type="xlsx",
        )
    finally:
        wb.close()

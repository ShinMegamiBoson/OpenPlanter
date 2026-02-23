"""Tests for redthread.ingestion.parsers — file parsers for CSV, JSON, XLSX.

TDD: These tests were written before the implementation.
Covers: ParseResult dataclass, parse_file() dispatcher, CSV/JSON/XLSX parsers,
encoding detection, file size guard, best-effort parsing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from redthread.ingestion.parsers import ParseResult, parse_file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_file(path: Path, content: str | bytes, mode: str = "w") -> Path:
    """Write content to a file and return the path."""
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# CSV Parser
# ---------------------------------------------------------------------------


class TestCSVWellFormed:
    """Parse well-formed CSV returns correct rows and column names."""

    def test_parse_csv_basic(self, tmp_path: Path):
        """Standard CSV with header row."""
        csv_path = _write_file(
            tmp_path / "data.csv",
            "name,amount,date\nAlice,1000,2024-01-01\nBob,2500,2024-01-02\n",
        )
        result = parse_file(csv_path, "csv")

        assert isinstance(result, ParseResult)
        assert result.file_type == "csv"
        assert result.row_count == 2
        assert result.column_names == ["name", "amount", "date"]
        assert len(result.rows) == 2
        assert result.rows[0]["name"] == "Alice"
        assert result.rows[0]["amount"] == "1000"
        assert result.rows[1]["name"] == "Bob"
        assert result.warnings == []

    def test_parse_csv_with_bom(self, tmp_path: Path):
        """CSV with UTF-8 BOM encoding succeeds."""
        bom = b"\xef\xbb\xbf"
        csv_content = bom + "name,value\nTest,42\n".encode("utf-8")
        csv_path = _write_file(tmp_path / "bom.csv", csv_content, mode="wb")

        result = parse_file(csv_path, "csv")
        assert result.row_count == 1
        assert result.column_names == ["name", "value"]
        assert result.rows[0]["name"] == "Test"
        assert result.warnings == []


class TestCSVInconsistentColumns:
    """Parse CSV with inconsistent column counts produces warnings but still parses valid rows."""

    def test_inconsistent_columns_produce_warnings(self, tmp_path: Path):
        """Rows with wrong number of columns produce warnings but valid rows are kept."""
        csv_path = _write_file(
            tmp_path / "messy.csv",
            "a,b,c\n1,2,3\n4,5\n6,7,8\n",
        )
        result = parse_file(csv_path, "csv")

        # Should still parse what it can
        assert result.row_count >= 2  # at least the well-formed rows
        assert len(result.warnings) > 0  # should have warnings about row 2


class TestCSVNonUTF8:
    """File with non-UTF-8 encoding is detected and parsed correctly."""

    def test_latin1_encoding(self, tmp_path: Path):
        """Latin-1 encoded CSV is detected and parsed."""
        csv_content = "name,city\nJos\xe9,S\xe3o Paulo\n".encode("latin-1")
        csv_path = _write_file(tmp_path / "latin.csv", csv_content, mode="wb")

        result = parse_file(csv_path, "csv")
        assert result.row_count == 1
        # The name should contain the accented characters
        assert "Jos" in result.rows[0]["name"]


# ---------------------------------------------------------------------------
# JSON Parser
# ---------------------------------------------------------------------------


class TestJSONArray:
    """Parse JSON array returns correct rows."""

    def test_json_array(self, tmp_path: Path):
        """JSON file with array of objects."""
        data = [
            {"name": "Alice", "amount": 1000},
            {"name": "Bob", "amount": 2500},
        ]
        json_path = _write_file(tmp_path / "data.json", json.dumps(data))

        result = parse_file(json_path, "json")
        assert result.file_type == "json"
        assert result.row_count == 2
        assert set(result.column_names) == {"name", "amount"}
        assert result.rows[0]["name"] == "Alice"
        assert result.rows[1]["amount"] == 2500
        assert result.warnings == []


class TestJSONLines:
    """Parse JSON Lines format returns correct rows."""

    def test_jsonl(self, tmp_path: Path):
        """JSON Lines (one object per line) format."""
        lines = '{"name":"Alice","amount":1000}\n{"name":"Bob","amount":2500}\n'
        jsonl_path = _write_file(tmp_path / "data.json", lines)

        result = parse_file(jsonl_path, "json")
        assert result.row_count == 2
        assert result.rows[0]["name"] == "Alice"
        assert result.rows[1]["name"] == "Bob"


class TestJSONMalformed:
    """Malformed JSON produces warning, returns parseable rows."""

    def test_jsonl_with_bad_line(self, tmp_path: Path):
        """JSON Lines with one malformed line still parses valid lines."""
        lines = '{"name":"Alice"}\nnot valid json\n{"name":"Bob"}\n'
        jsonl_path = _write_file(tmp_path / "bad.json", lines)

        result = parse_file(jsonl_path, "json")
        # Should parse the 2 valid lines
        assert result.row_count == 2
        assert len(result.warnings) > 0

    def test_completely_malformed_json(self, tmp_path: Path):
        """Completely malformed JSON returns zero rows with warning."""
        json_path = _write_file(tmp_path / "broken.json", "this is not json at all")

        result = parse_file(json_path, "json")
        assert result.row_count == 0
        assert len(result.warnings) > 0


class TestJSONMixedSchemas:
    """JSON with mixed schemas across rows produces warnings."""

    def test_mixed_schemas_produce_warnings(self, tmp_path: Path):
        """Objects with different keys produce schema inconsistency warnings."""
        data = [
            {"name": "Alice", "amount": 1000},
            {"name": "Bob", "city": "NYC"},
        ]
        json_path = _write_file(tmp_path / "mixed.json", json.dumps(data))

        result = parse_file(json_path, "json")
        assert result.row_count == 2
        assert len(result.warnings) > 0  # warning about mixed schemas


# ---------------------------------------------------------------------------
# XLSX Parser
# ---------------------------------------------------------------------------


class TestXLSXParse:
    """Parse XLSX returns correct rows from first sheet."""

    def test_parse_xlsx_basic(self, tmp_path: Path):
        """Basic XLSX file with header row."""
        # We need to create a real XLSX file using openpyxl
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["name", "amount", "date"])
        ws.append(["Alice", 1000, "2024-01-01"])
        ws.append(["Bob", 2500, "2024-01-02"])
        xlsx_path = tmp_path / "data.xlsx"
        wb.save(str(xlsx_path))

        result = parse_file(xlsx_path, "xlsx")
        assert result.file_type == "xlsx"
        assert result.row_count == 2
        assert result.column_names == ["name", "amount", "date"]
        assert result.rows[0]["name"] == "Alice"
        assert result.rows[0]["amount"] == 1000
        assert result.rows[1]["name"] == "Bob"

    def test_parse_xlsx_with_empty_rows(self, tmp_path: Path):
        """XLSX with empty rows produces warnings."""
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["name", "amount"])
        ws.append(["Alice", 1000])
        ws.append([None, None])  # empty row
        ws.append(["Bob", 2500])
        xlsx_path = tmp_path / "empty_rows.xlsx"
        wb.save(str(xlsx_path))

        result = parse_file(xlsx_path, "xlsx")
        # Should parse non-empty rows
        assert result.row_count == 2
        assert len(result.warnings) > 0  # warning about empty row


# ---------------------------------------------------------------------------
# File Size Guard
# ---------------------------------------------------------------------------


class TestFileSizeGuard:
    """File > 50 MB rejected with clear error message."""

    def test_oversized_file_raises(self, tmp_path: Path):
        """Files over 50 MB raise ValueError with clear message."""
        # Create a file that reports > 50 MB
        big_path = tmp_path / "big.csv"
        big_path.write_text("a,b\n")

        # Monkey-patch Path.stat to report 60 MB
        import unittest.mock as mock
        import os

        fake_stat = os.stat_result((0o100644, 0, 0, 0, 0, 0, 60 * 1024 * 1024, 0, 0, 0))
        with mock.patch.object(Path, "stat", return_value=fake_stat):
            with pytest.raises(ValueError, match="50 MB"):
                parse_file(big_path, "csv")


# ---------------------------------------------------------------------------
# Empty File
# ---------------------------------------------------------------------------


class TestEmptyFile:
    """Empty file returns zero rows with a warning."""

    def test_empty_csv(self, tmp_path: Path):
        """Empty CSV file returns zero rows."""
        csv_path = _write_file(tmp_path / "empty.csv", "")

        result = parse_file(csv_path, "csv")
        assert result.row_count == 0
        assert len(result.warnings) > 0

    def test_empty_json(self, tmp_path: Path):
        """Empty JSON file returns zero rows."""
        json_path = _write_file(tmp_path / "empty.json", "")

        result = parse_file(json_path, "json")
        assert result.row_count == 0
        assert len(result.warnings) > 0


# ---------------------------------------------------------------------------
# Unsupported / Edge Cases
# ---------------------------------------------------------------------------


class TestUnsupportedFileType:
    """Unsupported file type raises ValueError."""

    def test_unsupported_type(self, tmp_path: Path):
        """Unsupported file type raises ValueError."""
        txt_path = _write_file(tmp_path / "data.txt", "hello")

        with pytest.raises(ValueError, match="[Uu]nsupported"):
            parse_file(txt_path, "txt")


class TestFileNotFound:
    """Non-existent file raises FileNotFoundError."""

    def test_nonexistent_file(self, tmp_path: Path):
        """Missing file raises FileNotFoundError."""
        fake_path = tmp_path / "nonexistent.csv"

        with pytest.raises(FileNotFoundError):
            parse_file(fake_path, "csv")

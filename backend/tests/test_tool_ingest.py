"""Tests for redthread.agent.tools.ingest — file ingestion agent tool.

TDD: These tests were written before the implementation.
The ingest_file tool is a plain async function (NOT decorated with @tool)
that takes dataset_repo as dependency injection.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from redthread.agent.tools.ingest import ingest_file
from redthread.db.graph import NetworkXGraphDB
from redthread.db.repositories import DatasetRepo, InvestigationRepo
from redthread.db.sqlite import SQLiteDB


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite_db(tmp_path: Path) -> SQLiteDB:
    """Create a fresh SQLiteDB instance."""
    db_path = tmp_path / "test.db"
    return SQLiteDB(str(db_path))


@pytest.fixture
def graph_db(tmp_path: Path) -> NetworkXGraphDB:
    """Create a fresh NetworkXGraphDB instance."""
    graph_path = tmp_path / "test_graph.json"
    return NetworkXGraphDB(str(graph_path))


@pytest.fixture
def inv_repo(sqlite_db: SQLiteDB, graph_db: NetworkXGraphDB) -> InvestigationRepo:
    return InvestigationRepo(sqlite_db, graph_db)


@pytest.fixture
def dataset_repo(sqlite_db: SQLiteDB, graph_db: NetworkXGraphDB) -> DatasetRepo:
    return DatasetRepo(sqlite_db, graph_db)


@pytest.fixture
def investigation(inv_repo: InvestigationRepo) -> dict:
    """Create an investigation for use by tests."""
    return inv_repo.create(title="Test Investigation")


def _write_file(path: Path, content: str | bytes, mode: str = "w") -> Path:
    """Helper to write a file."""
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Ingest CSV
# ---------------------------------------------------------------------------


class TestIngestCSV:
    """Ingest a CSV file creates dataset and records in DB."""

    async def test_ingest_csv_creates_dataset_and_records(
        self,
        tmp_path: Path,
        dataset_repo: DatasetRepo,
        investigation: dict,
    ):
        """Ingesting a CSV creates a Dataset record and stores all rows as Records."""
        csv_path = _write_file(
            tmp_path / "transactions.csv",
            "name,amount,date\nAlice,1000,2024-01-01\nBob,2500,2024-01-02\n",
        )

        result_json = await ingest_file(
            dataset_repo=dataset_repo,
            file_path=str(csv_path),
            investigation_id=investigation["id"],
            description="Test transactions",
        )

        result = json.loads(result_json)
        assert result["status"] == "success"
        assert result["filename"] == "transactions.csv"
        assert result["row_count"] == 2
        assert result["column_names"] == ["name", "amount", "date"]
        assert result["warnings"] == []

        # Verify records exist in DB
        datasets = dataset_repo.get_by_investigation(investigation["id"])
        assert len(datasets) == 1
        ds = datasets[0]
        assert ds["filename"] == "transactions.csv"
        assert ds["file_type"] == "csv"
        assert ds["row_count"] == 2

        records = dataset_repo.get_records(ds["id"])
        assert len(records) == 2


class TestIngestSummary:
    """Ingest returns summary with correct row count and column names."""

    async def test_summary_includes_all_fields(
        self,
        tmp_path: Path,
        dataset_repo: DatasetRepo,
        investigation: dict,
    ):
        """Summary JSON includes filename, row_count, column_names, file_type."""
        csv_path = _write_file(
            tmp_path / "data.csv",
            "x,y\n1,2\n3,4\n5,6\n",
        )

        result_json = await ingest_file(
            dataset_repo=dataset_repo,
            file_path=str(csv_path),
            investigation_id=investigation["id"],
        )

        result = json.loads(result_json)
        assert "filename" in result
        assert "row_count" in result
        assert "column_names" in result
        assert "file_type" in result
        assert "dataset_id" in result
        assert result["row_count"] == 3
        assert result["file_type"] == "csv"


class TestIngestWithWarnings:
    """Ingest file with validation warnings includes warnings in response."""

    async def test_warnings_included_in_response(
        self,
        tmp_path: Path,
        dataset_repo: DatasetRepo,
        investigation: dict,
    ):
        """CSV with inconsistent columns produces warnings in the result."""
        csv_path = _write_file(
            tmp_path / "messy.csv",
            "a,b,c\n1,2,3\n4,5\n6,7,8\n",
        )

        result_json = await ingest_file(
            dataset_repo=dataset_repo,
            file_path=str(csv_path),
            investigation_id=investigation["id"],
        )

        result = json.loads(result_json)
        assert result["status"] == "success"
        assert len(result["warnings"]) > 0


class TestIngestUnsupportedType:
    """Ingest unsupported file type returns error message."""

    async def test_unsupported_extension(
        self,
        tmp_path: Path,
        dataset_repo: DatasetRepo,
        investigation: dict,
    ):
        """File with unsupported extension returns error, not an exception."""
        txt_path = _write_file(tmp_path / "data.txt", "hello")

        result_json = await ingest_file(
            dataset_repo=dataset_repo,
            file_path=str(txt_path),
            investigation_id=investigation["id"],
        )

        result = json.loads(result_json)
        assert result["status"] == "error"
        assert "unsupported" in result["message"].lower() or "Unsupported" in result["message"]


class TestIngestNonexistentFile:
    """Ingest nonexistent file returns error message."""

    async def test_file_not_found(
        self,
        tmp_path: Path,
        dataset_repo: DatasetRepo,
        investigation: dict,
    ):
        """Missing file returns an error, not an exception."""
        result_json = await ingest_file(
            dataset_repo=dataset_repo,
            file_path=str(tmp_path / "nonexistent.csv"),
            investigation_id=investigation["id"],
        )

        result = json.loads(result_json)
        assert result["status"] == "error"
        assert "not found" in result["message"].lower() or "File not found" in result["message"]


class TestIngestRecordsRetrievable:
    """Ingested records are retrievable from DatasetRepo."""

    async def test_records_retrievable_after_ingest(
        self,
        tmp_path: Path,
        dataset_repo: DatasetRepo,
        investigation: dict,
    ):
        """After ingesting, all records can be retrieved and have correct data."""
        json_data = json.dumps([
            {"name": "Alice", "amount": 1000},
            {"name": "Bob", "amount": 2500},
            {"name": "Carol", "amount": 750},
        ])
        json_path = _write_file(tmp_path / "people.json", json_data)

        result_json = await ingest_file(
            dataset_repo=dataset_repo,
            file_path=str(json_path),
            investigation_id=investigation["id"],
        )

        result = json.loads(result_json)
        assert result["status"] == "success"
        dataset_id = result["dataset_id"]

        records = dataset_repo.get_records(dataset_id)
        assert len(records) == 3

        # Verify data round-trips
        first_data = json.loads(records[0]["data"])
        assert first_data["name"] == "Alice"
        assert first_data["amount"] == 1000


class TestIngestXLSX:
    """Ingest an XLSX file works correctly."""

    async def test_ingest_xlsx(
        self,
        tmp_path: Path,
        dataset_repo: DatasetRepo,
        investigation: dict,
    ):
        """XLSX files are parsed and stored correctly."""
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["name", "value"])
        ws.append(["Test", 42])
        ws.append(["Another", 99])
        xlsx_path = tmp_path / "data.xlsx"
        wb.save(str(xlsx_path))

        result_json = await ingest_file(
            dataset_repo=dataset_repo,
            file_path=str(xlsx_path),
            investigation_id=investigation["id"],
        )

        result = json.loads(result_json)
        assert result["status"] == "success"
        assert result["row_count"] == 2
        assert result["file_type"] == "xlsx"
        assert result["column_names"] == ["name", "value"]


class TestIngestDetectsFileType:
    """File type is detected from extension."""

    async def test_csv_detected(
        self,
        tmp_path: Path,
        dataset_repo: DatasetRepo,
        investigation: dict,
    ):
        """CSV file type detected from .csv extension."""
        csv_path = _write_file(tmp_path / "data.csv", "a,b\n1,2\n")

        result_json = await ingest_file(
            dataset_repo=dataset_repo,
            file_path=str(csv_path),
            investigation_id=investigation["id"],
        )

        result = json.loads(result_json)
        assert result["file_type"] == "csv"

    async def test_json_detected(
        self,
        tmp_path: Path,
        dataset_repo: DatasetRepo,
        investigation: dict,
    ):
        """JSON file type detected from .json extension."""
        json_path = _write_file(
            tmp_path / "data.json", json.dumps([{"a": 1}]),
        )

        result_json = await ingest_file(
            dataset_repo=dataset_repo,
            file_path=str(json_path),
            investigation_id=investigation["id"],
        )

        result = json.loads(result_json)
        assert result["file_type"] == "json"

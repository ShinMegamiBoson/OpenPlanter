"""Tests for redthread.agent.tools.timeline — timeline event recording.

TDD: These tests were written before the implementation.
Tools are plain async functions taking repos as dependency injection.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from redthread.agent.tools.timeline import record_timeline_event
from redthread.db.graph import NetworkXGraphDB
from redthread.db.repositories import DatasetRepo, InvestigationRepo, TimelineEventRepo
from redthread.db.sqlite import SQLiteDB


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite_db(tmp_path: Path) -> SQLiteDB:
    return SQLiteDB(str(tmp_path / "test.db"))


@pytest.fixture
def graph_db(tmp_path: Path) -> NetworkXGraphDB:
    return NetworkXGraphDB(str(tmp_path / "test_graph.json"))


@pytest.fixture
def inv_repo(sqlite_db: SQLiteDB, graph_db: NetworkXGraphDB) -> InvestigationRepo:
    return InvestigationRepo(sqlite_db, graph_db)


@pytest.fixture
def timeline_repo(sqlite_db: SQLiteDB, graph_db: NetworkXGraphDB) -> TimelineEventRepo:
    return TimelineEventRepo(sqlite_db, graph_db)


@pytest.fixture
def dataset_repo(sqlite_db: SQLiteDB, graph_db: NetworkXGraphDB) -> DatasetRepo:
    return DatasetRepo(sqlite_db, graph_db)


@pytest.fixture
def investigation(inv_repo: InvestigationRepo) -> dict:
    """Create a test investigation."""
    return inv_repo.create(title="Timeline Tool Test Investigation")


@pytest.fixture
def dataset_with_records(
    dataset_repo: DatasetRepo, investigation: dict,
) -> tuple[dict, list[dict]]:
    """Create a dataset with sample records and return (dataset, records)."""
    ds = dataset_repo.create(
        investigation_id=investigation["id"],
        filename="transactions.csv",
        file_type="csv",
        row_count=2,
        column_names=["date", "amount", "description"],
    )
    rows = [
        {"date": "2024-01-15", "amount": 10000, "desc": "Wire transfer"},
        {"date": "2024-02-01", "amount": 5000, "desc": "Check deposit"},
    ]
    dataset_repo.store_records(ds["id"], rows)
    records = dataset_repo.get_records(ds["id"])
    return ds, records


# ---------------------------------------------------------------------------
# record_timeline_event
# ---------------------------------------------------------------------------


class TestRecordTimelineEvent:
    """record_timeline_event tool — recording dated events."""

    async def test_record_with_all_fields(
        self,
        timeline_repo: TimelineEventRepo,
        investigation: dict,
        dataset_with_records: tuple[dict, list[dict]],
    ):
        """Record event with all fields creates entry in DB."""
        ds, records = dataset_with_records
        result = await record_timeline_event(
            timeline_repo=timeline_repo,
            investigation_id=investigation["id"],
            entity_id="entity-1",
            entity_name="John Smith",
            event_date="2024-01-15",
            amount=10000.00,
            description="Wire transfer to offshore account",
            source_record_id=records[0]["id"],
            source_dataset_id=ds["id"],
        )

        parsed = json.loads(result)
        assert parsed["status"] == "recorded"
        assert "id" in parsed
        assert parsed["entity_name"] == "John Smith"
        assert parsed["event_date"] == "2024-01-15"

        # Verify actually persisted in DB
        events = timeline_repo.query_by_investigation(investigation["id"])
        assert len(events) == 1
        assert events[0]["entity_name"] == "John Smith"
        assert events[0]["amount"] == 10000.00

    async def test_record_with_minimal_fields(
        self, timeline_repo: TimelineEventRepo, investigation: dict,
    ):
        """Record event with minimal required fields succeeds."""
        result = await record_timeline_event(
            timeline_repo=timeline_repo,
            investigation_id=investigation["id"],
            entity_id="entity-2",
            entity_name="Acme Corp",
            event_date="2024-06-01",
        )

        parsed = json.loads(result)
        assert parsed["status"] == "recorded"
        assert "id" in parsed
        assert parsed["entity_name"] == "Acme Corp"
        assert parsed["event_date"] == "2024-06-01"

    async def test_record_with_iso8601_datetime(
        self, timeline_repo: TimelineEventRepo, investigation: dict,
    ):
        """Record event with full ISO 8601 datetime string succeeds."""
        result = await record_timeline_event(
            timeline_repo=timeline_repo,
            investigation_id=investigation["id"],
            entity_id="entity-3",
            entity_name="Jane Doe",
            event_date="2024-03-15T14:30:00Z",
        )

        parsed = json.loads(result)
        assert parsed["status"] == "recorded"

    async def test_record_invalid_date_format_returns_error(
        self, timeline_repo: TimelineEventRepo, investigation: dict,
    ):
        """Record event with invalid date format returns error message."""
        result = await record_timeline_event(
            timeline_repo=timeline_repo,
            investigation_id=investigation["id"],
            entity_id="entity-4",
            entity_name="Bad Date Person",
            event_date="not-a-date",
        )

        assert "error" in result.lower() or "invalid" in result.lower()

        # Verify nothing was persisted
        events = timeline_repo.query_by_investigation(investigation["id"])
        assert len(events) == 0

    async def test_record_invalid_date_format_partial(
        self, timeline_repo: TimelineEventRepo, investigation: dict,
    ):
        """Record event with a partially valid date returns error."""
        result = await record_timeline_event(
            timeline_repo=timeline_repo,
            investigation_id=investigation["id"],
            entity_id="entity-5",
            entity_name="Partial Date",
            event_date="2024-13-01",  # month 13 is invalid
        )

        assert "error" in result.lower() or "invalid" in result.lower()

        events = timeline_repo.query_by_investigation(investigation["id"])
        assert len(events) == 0

    async def test_events_retrievable_by_investigation(
        self, timeline_repo: TimelineEventRepo, investigation: dict,
    ):
        """Events are retrievable from TimelineEventRepo filtered by investigation_id."""
        await record_timeline_event(
            timeline_repo=timeline_repo,
            investigation_id=investigation["id"],
            entity_id="e1",
            entity_name="Entity One",
            event_date="2024-01-01",
            amount=1000.0,
        )
        await record_timeline_event(
            timeline_repo=timeline_repo,
            investigation_id=investigation["id"],
            entity_id="e2",
            entity_name="Entity Two",
            event_date="2024-02-01",
            amount=2000.0,
        )

        events = timeline_repo.query_by_investigation(investigation["id"])
        assert len(events) == 2
        # Sorted by event_date
        assert events[0]["event_date"] == "2024-01-01"
        assert events[1]["event_date"] == "2024-02-01"

    async def test_events_retrievable_by_entity_id(
        self, timeline_repo: TimelineEventRepo, investigation: dict,
    ):
        """Events are retrievable filtered by entity_id."""
        await record_timeline_event(
            timeline_repo=timeline_repo,
            investigation_id=investigation["id"],
            entity_id="entity-X",
            entity_name="X Corp",
            event_date="2024-01-01",
        )
        await record_timeline_event(
            timeline_repo=timeline_repo,
            investigation_id=investigation["id"],
            entity_id="entity-Y",
            entity_name="Y Corp",
            event_date="2024-02-01",
        )

        results = timeline_repo.query_by_entity(investigation["id"], "entity-X")
        assert len(results) == 1
        assert results[0]["entity_id"] == "entity-X"

    async def test_record_with_zero_amount(
        self, timeline_repo: TimelineEventRepo, investigation: dict,
    ):
        """Record event with amount=0.0 succeeds (zero is valid)."""
        result = await record_timeline_event(
            timeline_repo=timeline_repo,
            investigation_id=investigation["id"],
            entity_id="entity-6",
            entity_name="Zero Amount",
            event_date="2024-05-01",
            amount=0.0,
        )

        parsed = json.loads(result)
        assert parsed["status"] == "recorded"

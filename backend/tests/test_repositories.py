"""Tests for redthread.db.repositories — data access repositories.

TDD: These tests were written before the implementation.
Each repo takes SQLiteDB and GraphDB via dependency injection.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from redthread.db.graph import NetworkXGraphDB
from redthread.db.repositories import (
    DatasetRepo,
    EvidenceRepo,
    InvestigationRepo,
    MessageRepo,
    TimelineEventRepo,
)
from redthread.db.sqlite import SQLiteDB


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
    """InvestigationRepo with injected dependencies."""
    return InvestigationRepo(sqlite_db, graph_db)


@pytest.fixture
def dataset_repo(sqlite_db: SQLiteDB, graph_db: NetworkXGraphDB) -> DatasetRepo:
    """DatasetRepo with injected dependencies."""
    return DatasetRepo(sqlite_db, graph_db)


@pytest.fixture
def evidence_repo(sqlite_db: SQLiteDB, graph_db: NetworkXGraphDB) -> EvidenceRepo:
    """EvidenceRepo with injected dependencies."""
    return EvidenceRepo(sqlite_db, graph_db)


@pytest.fixture
def timeline_repo(sqlite_db: SQLiteDB, graph_db: NetworkXGraphDB) -> TimelineEventRepo:
    """TimelineEventRepo with injected dependencies."""
    return TimelineEventRepo(sqlite_db, graph_db)


@pytest.fixture
def message_repo(sqlite_db: SQLiteDB, graph_db: NetworkXGraphDB) -> MessageRepo:
    """MessageRepo with injected dependencies."""
    return MessageRepo(sqlite_db, graph_db)


def _make_investigation(inv_repo: InvestigationRepo, title: str = "Test Investigation") -> dict:
    """Helper: create an investigation via the repo and return it."""
    return inv_repo.create(title=title)


# ---------------------------------------------------------------------------
# InvestigationRepo
# ---------------------------------------------------------------------------


class TestInvestigationRepoCreate:
    """Create investigation and retrieve it."""

    def test_create_and_get(self, inv_repo: InvestigationRepo):
        """Create investigation and retrieve it by ID."""
        inv = inv_repo.create(title="Money Laundering Case #42")
        assert inv["id"] is not None
        assert inv["title"] == "Money Laundering Case #42"
        assert inv["status"] == "active"

        retrieved = inv_repo.get(inv["id"])
        assert retrieved is not None
        assert retrieved["id"] == inv["id"]
        assert retrieved["title"] == "Money Laundering Case #42"

    def test_create_sets_timestamps(self, inv_repo: InvestigationRepo):
        """Created investigation has created_at and updated_at timestamps."""
        inv = inv_repo.create(title="Timestamped")
        assert "created_at" in inv
        assert "updated_at" in inv
        assert inv["created_at"] is not None
        assert inv["updated_at"] is not None

    def test_get_nonexistent_returns_none(self, inv_repo: InvestigationRepo):
        """Getting a non-existent investigation returns None."""
        result = inv_repo.get("nonexistent-id")
        assert result is None


class TestInvestigationRepoList:
    """Investigation listing returns all investigations sorted by updated_at desc."""

    def test_list_all_sorted_by_updated_at_desc(self, inv_repo: InvestigationRepo):
        """List returns all investigations sorted by updated_at descending."""
        inv1 = inv_repo.create(title="First")
        inv2 = inv_repo.create(title="Second")
        inv3 = inv_repo.create(title="Third")

        all_invs = inv_repo.list_all()
        assert len(all_invs) == 3
        # Most recent should be first
        assert all_invs[0]["title"] == "Third"
        assert all_invs[2]["title"] == "First"

    def test_list_empty(self, inv_repo: InvestigationRepo):
        """List returns empty list when no investigations exist."""
        all_invs = inv_repo.list_all()
        assert all_invs == []


class TestInvestigationRepoUpdateStatus:
    """Update investigation status."""

    def test_update_status_to_archived(self, inv_repo: InvestigationRepo):
        """Update status from active to archived."""
        inv = inv_repo.create(title="To Archive")
        updated = inv_repo.update_status(inv["id"], "archived")
        assert updated is not None
        assert updated["status"] == "archived"

        # Verify persistence
        retrieved = inv_repo.get(inv["id"])
        assert retrieved["status"] == "archived"

    def test_update_status_nonexistent_returns_none(self, inv_repo: InvestigationRepo):
        """Updating status of non-existent investigation returns None."""
        result = inv_repo.update_status("nonexistent-id", "archived")
        assert result is None


# ---------------------------------------------------------------------------
# DatasetRepo
# ---------------------------------------------------------------------------


class TestDatasetRepoCreate:
    """Create dataset with records and retrieve records by dataset."""

    def test_create_dataset(
        self, dataset_repo: DatasetRepo, inv_repo: InvestigationRepo,
    ):
        """Create a dataset linked to an investigation."""
        inv = _make_investigation(inv_repo)
        ds = dataset_repo.create(
            investigation_id=inv["id"],
            filename="transactions.csv",
            file_type="csv",
            row_count=100,
            column_names=["date", "amount", "description"],
        )
        assert ds["id"] is not None
        assert ds["filename"] == "transactions.csv"
        assert ds["row_count"] == 100

    def test_create_dataset_with_warnings(
        self, dataset_repo: DatasetRepo, inv_repo: InvestigationRepo,
    ):
        """Create dataset with validation warnings."""
        inv = _make_investigation(inv_repo)
        ds = dataset_repo.create(
            investigation_id=inv["id"],
            filename="messy.csv",
            file_type="csv",
            validation_warnings=["Row 5 has missing columns", "Row 10 has extra columns"],
        )
        assert ds["validation_warnings"] is not None

    def test_get_datasets_by_investigation(
        self, dataset_repo: DatasetRepo, inv_repo: InvestigationRepo,
    ):
        """Get all datasets for an investigation."""
        inv = _make_investigation(inv_repo)
        dataset_repo.create(investigation_id=inv["id"], filename="a.csv", file_type="csv")
        dataset_repo.create(investigation_id=inv["id"], filename="b.json", file_type="json")

        datasets = dataset_repo.get_by_investigation(inv["id"])
        assert len(datasets) == 2

    def test_store_and_retrieve_records(
        self, dataset_repo: DatasetRepo, inv_repo: InvestigationRepo,
    ):
        """Store records in batch and retrieve them by dataset ID."""
        inv = _make_investigation(inv_repo)
        ds = dataset_repo.create(
            investigation_id=inv["id"], filename="data.csv", file_type="csv",
        )
        rows = [
            {"date": "2024-01-01", "amount": 1000, "desc": "Wire transfer"},
            {"date": "2024-01-02", "amount": 2500, "desc": "Check deposit"},
            {"date": "2024-01-03", "amount": 500, "desc": "ATM withdrawal"},
        ]
        dataset_repo.store_records(ds["id"], rows)

        records = dataset_repo.get_records(ds["id"])
        assert len(records) == 3
        # Verify row_number assignment
        row_numbers = sorted(r["row_number"] for r in records)
        assert row_numbers == [1, 2, 3]
        # Verify data round-trips
        first = next(r for r in records if r["row_number"] == 1)
        data = json.loads(first["data"])
        assert data["amount"] == 1000


# ---------------------------------------------------------------------------
# EvidenceRepo
# ---------------------------------------------------------------------------


class TestEvidenceRepoCreate:
    """Create evidence chain and query by entity/confidence."""

    def test_create_evidence_chain(
        self, evidence_repo: EvidenceRepo, inv_repo: InvestigationRepo,
    ):
        """Create an evidence chain entry."""
        inv = _make_investigation(inv_repo)
        ec = evidence_repo.create(
            investigation_id=inv["id"],
            entity_id="entity-1",
            claim="John Smith appears in multiple transactions",
            supporting_evidence="Records show 5 transactions totaling $50,000",
            confidence="confirmed",
        )
        assert ec["id"] is not None
        assert ec["claim"] == "John Smith appears in multiple transactions"
        assert ec["confidence"] == "confirmed"

    def test_query_by_entity_id(
        self, evidence_repo: EvidenceRepo, inv_repo: InvestigationRepo,
    ):
        """Query evidence chains by entity_id returns correct subset."""
        inv = _make_investigation(inv_repo)
        evidence_repo.create(
            investigation_id=inv["id"], entity_id="entity-A",
            claim="Claim A", supporting_evidence="Ev A", confidence="confirmed",
        )
        evidence_repo.create(
            investigation_id=inv["id"], entity_id="entity-B",
            claim="Claim B", supporting_evidence="Ev B", confidence="probable",
        )

        results = evidence_repo.query(investigation_id=inv["id"], entity_id="entity-A")
        assert len(results) == 1
        assert results[0]["entity_id"] == "entity-A"

    def test_query_by_confidence(
        self, evidence_repo: EvidenceRepo, inv_repo: InvestigationRepo,
    ):
        """Query evidence chains by confidence returns only confirmed entries."""
        inv = _make_investigation(inv_repo)
        evidence_repo.create(
            investigation_id=inv["id"], entity_id="e1",
            claim="Claim 1", supporting_evidence="Ev 1", confidence="confirmed",
        )
        evidence_repo.create(
            investigation_id=inv["id"], entity_id="e2",
            claim="Claim 2", supporting_evidence="Ev 2", confidence="possible",
        )

        results = evidence_repo.query(investigation_id=inv["id"], confidence="confirmed")
        assert len(results) == 1
        assert results[0]["confidence"] == "confirmed"

    def test_query_all_for_investigation(
        self, evidence_repo: EvidenceRepo, inv_repo: InvestigationRepo,
    ):
        """Query all evidence for an investigation returns complete list."""
        inv = _make_investigation(inv_repo)
        evidence_repo.create(
            investigation_id=inv["id"], entity_id="e1",
            claim="C1", supporting_evidence="E1", confidence="confirmed",
        )
        evidence_repo.create(
            investigation_id=inv["id"], entity_id="e2",
            claim="C2", supporting_evidence="E2", confidence="probable",
        )

        results = evidence_repo.query(investigation_id=inv["id"])
        assert len(results) == 2


# ---------------------------------------------------------------------------
# TimelineEventRepo
# ---------------------------------------------------------------------------


class TestTimelineEventRepo:
    """Timeline event create and query."""

    def test_create_event(
        self, timeline_repo: TimelineEventRepo, inv_repo: InvestigationRepo,
    ):
        """Create a timeline event and verify it's returned."""
        inv = _make_investigation(inv_repo)
        event = timeline_repo.create(
            investigation_id=inv["id"],
            entity_id="entity-1",
            entity_name="John Smith",
            event_date="2024-01-15",
            amount=10000.00,
            description="Wire transfer to offshore account",
        )
        assert event["id"] is not None
        assert event["entity_name"] == "John Smith"
        assert event["amount"] == 10000.00

    def test_query_by_investigation_sorted_by_date(
        self, timeline_repo: TimelineEventRepo, inv_repo: InvestigationRepo,
    ):
        """Query events by investigation returns them sorted by event_date."""
        inv = _make_investigation(inv_repo)
        timeline_repo.create(
            investigation_id=inv["id"], entity_id="e1", entity_name="A",
            event_date="2024-03-01", amount=300,
        )
        timeline_repo.create(
            investigation_id=inv["id"], entity_id="e1", entity_name="A",
            event_date="2024-01-01", amount=100,
        )
        timeline_repo.create(
            investigation_id=inv["id"], entity_id="e1", entity_name="A",
            event_date="2024-02-01", amount=200,
        )

        events = timeline_repo.query_by_investigation(inv["id"])
        assert len(events) == 3
        dates = [e["event_date"] for e in events]
        assert dates == ["2024-01-01", "2024-02-01", "2024-03-01"]

    def test_query_by_entity_id(
        self, timeline_repo: TimelineEventRepo, inv_repo: InvestigationRepo,
    ):
        """Query events by entity_id returns correct subset."""
        inv = _make_investigation(inv_repo)
        timeline_repo.create(
            investigation_id=inv["id"], entity_id="entity-X", entity_name="X",
            event_date="2024-01-01",
        )
        timeline_repo.create(
            investigation_id=inv["id"], entity_id="entity-Y", entity_name="Y",
            event_date="2024-02-01",
        )

        results = timeline_repo.query_by_entity(inv["id"], "entity-X")
        assert len(results) == 1
        assert results[0]["entity_id"] == "entity-X"


# ---------------------------------------------------------------------------
# MessageRepo
# ---------------------------------------------------------------------------


class TestMessageRepo:
    """Message append and retrieval."""

    def test_append_and_get_history(
        self, message_repo: MessageRepo, inv_repo: InvestigationRepo,
    ):
        """Append messages and retrieve them in chronological order."""
        inv = _make_investigation(inv_repo)

        message_repo.append(inv["id"], role="user", content="Hello, investigate this.")
        message_repo.append(inv["id"], role="assistant", content="I'll start the investigation.")
        message_repo.append(inv["id"], role="user", content="Check the transactions.")

        history = message_repo.get_history(inv["id"])
        assert len(history) == 3
        # Verify chronological order
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "Hello, investigate this."
        assert history[1]["role"] == "assistant"
        assert history[2]["role"] == "user"
        assert history[2]["content"] == "Check the transactions."

    def test_empty_history(
        self, message_repo: MessageRepo, inv_repo: InvestigationRepo,
    ):
        """Get history for investigation with no messages returns empty list."""
        inv = _make_investigation(inv_repo)
        history = message_repo.get_history(inv["id"])
        assert history == []

    def test_messages_scoped_to_investigation(
        self, message_repo: MessageRepo, inv_repo: InvestigationRepo,
    ):
        """Messages from one investigation don't appear in another."""
        inv1 = _make_investigation(inv_repo, title="Investigation 1")
        inv2 = _make_investigation(inv_repo, title="Investigation 2")

        message_repo.append(inv1["id"], role="user", content="Msg for inv1")
        message_repo.append(inv2["id"], role="user", content="Msg for inv2")

        history1 = message_repo.get_history(inv1["id"])
        history2 = message_repo.get_history(inv2["id"])
        assert len(history1) == 1
        assert len(history2) == 1
        assert history1[0]["content"] == "Msg for inv1"
        assert history2[0]["content"] == "Msg for inv2"

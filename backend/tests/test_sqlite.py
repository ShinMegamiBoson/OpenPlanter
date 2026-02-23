"""Tests for redthread.db.sqlite — SQLite schema and connection manager.

TDD: These tests were written before the implementation.
"""

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from redthread.db.sqlite import SQLiteDB


@pytest.fixture
def tmp_db(tmp_path: Path) -> SQLiteDB:
    """Create a fresh SQLiteDB instance on a temp path."""
    db_path = tmp_path / "test.db"
    db = SQLiteDB(str(db_path))
    return db


class TestSchemaCreation:
    """Schema creates all tables on fresh database."""

    def test_all_six_tables_exist(self, tmp_db: SQLiteDB):
        """All 6 tables (investigations, datasets, records, evidence_chains,
        timeline_events, messages) are created on fresh database."""
        rows = tmp_db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        table_names = sorted(row["name"] for row in rows)
        expected = sorted([
            "investigations",
            "datasets",
            "records",
            "evidence_chains",
            "timeline_events",
            "messages",
        ])
        assert table_names == expected


class TestWALMode:
    """WAL mode is enabled after connection."""

    def test_wal_mode_enabled(self, tmp_db: SQLiteDB):
        """journal_mode should be 'wal' after connection."""
        result = tmp_db.fetchone("PRAGMA journal_mode")
        assert result["journal_mode"] == "wal"


class TestForeignKeys:
    """Foreign keys are enforced."""

    def test_foreign_keys_enabled(self, tmp_db: SQLiteDB):
        """PRAGMA foreign_keys should return 1."""
        result = tmp_db.fetchone("PRAGMA foreign_keys")
        assert result["foreign_keys"] == 1


class TestInvestigationCRUD:
    """Insert and retrieve an investigation round-trips correctly."""

    def test_insert_and_retrieve(self, tmp_db: SQLiteDB):
        """Insert a row into investigations and retrieve it by ID."""
        inv_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        tmp_db.execute(
            "INSERT INTO investigations (id, title, created_at, updated_at, status) "
            "VALUES (?, ?, ?, ?, ?)",
            (inv_id, "Test Investigation", now, now, "active"),
        )
        row = tmp_db.fetchone(
            "SELECT * FROM investigations WHERE id = ?", (inv_id,)
        )
        assert row is not None
        assert row["id"] == inv_id
        assert row["title"] == "Test Investigation"
        assert row["status"] == "active"

    def test_metadata_json_blob(self, tmp_db: SQLiteDB):
        """Insert investigation with JSON metadata and retrieve it."""
        inv_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        metadata = '{"source": "test", "tags": ["aml", "bsa"]}'
        tmp_db.execute(
            "INSERT INTO investigations (id, title, created_at, updated_at, status, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (inv_id, "Meta Test", now, now, "active", metadata),
        )
        row = tmp_db.fetchone(
            "SELECT metadata FROM investigations WHERE id = ?", (inv_id,)
        )
        assert row["metadata"] == metadata


class TestEvidenceChainConstraints:
    """Evidence chain constraints work correctly."""

    def _create_investigation(self, db: SQLiteDB) -> str:
        """Helper: create an investigation and return its ID."""
        inv_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO investigations (id, title, created_at, updated_at, status) "
            "VALUES (?, ?, ?, ?, ?)",
            (inv_id, "Test", now, now, "active"),
        )
        return inv_id

    def test_insert_evidence_chain_all_required_fields(self, tmp_db: SQLiteDB):
        """Insert evidence chain with all required fields succeeds."""
        inv_id = self._create_investigation(tmp_db)
        ec_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        tmp_db.execute(
            "INSERT INTO evidence_chains "
            "(id, investigation_id, entity_id, claim, supporting_evidence, "
            "confidence, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ec_id, inv_id, "entity-1", "Claim text", "Evidence text", "confirmed", now),
        )
        row = tmp_db.fetchone(
            "SELECT * FROM evidence_chains WHERE id = ?", (ec_id,)
        )
        assert row is not None
        assert row["confidence"] == "confirmed"

    def test_invalid_confidence_raises_constraint_error(self, tmp_db: SQLiteDB):
        """Evidence chain with invalid confidence value raises IntegrityError."""
        inv_id = self._create_investigation(tmp_db)
        ec_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with pytest.raises(sqlite3.IntegrityError):
            tmp_db.execute(
                "INSERT INTO evidence_chains "
                "(id, investigation_id, entity_id, claim, supporting_evidence, "
                "confidence, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ec_id, inv_id, "entity-1", "Claim", "Evidence", "INVALID", now),
            )

    def test_foreign_key_prevents_orphaned_evidence_chains(self, tmp_db: SQLiteDB):
        """Foreign key constraint prevents orphaned evidence chains (nonexistent investigation_id)."""
        ec_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with pytest.raises(sqlite3.IntegrityError):
            tmp_db.execute(
                "INSERT INTO evidence_chains "
                "(id, investigation_id, entity_id, claim, supporting_evidence, "
                "confidence, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ec_id, "nonexistent-inv-id", "entity-1", "Claim", "Evidence", "confirmed", now),
            )


class TestEvidenceChainQueries:
    """Query evidence chains filtered by entity_id and confidence."""

    def _setup_evidence(self, db: SQLiteDB) -> str:
        """Helper: create an investigation with several evidence chains."""
        inv_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO investigations (id, title, created_at, updated_at, status) "
            "VALUES (?, ?, ?, ?, ?)",
            (inv_id, "Test", now, now, "active"),
        )
        entries = [
            (str(uuid.uuid4()), inv_id, "entity-A", "Claim A1", "Ev A1", "confirmed", now),
            (str(uuid.uuid4()), inv_id, "entity-A", "Claim A2", "Ev A2", "probable", now),
            (str(uuid.uuid4()), inv_id, "entity-B", "Claim B1", "Ev B1", "confirmed", now),
            (str(uuid.uuid4()), inv_id, "entity-B", "Claim B2", "Ev B2", "possible", now),
        ]
        db.executemany(
            "INSERT INTO evidence_chains "
            "(id, investigation_id, entity_id, claim, supporting_evidence, "
            "confidence, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            entries,
        )
        return inv_id

    def test_query_by_entity_id(self, tmp_db: SQLiteDB):
        """Query evidence chains filtered by entity_id returns correct subset."""
        inv_id = self._setup_evidence(tmp_db)
        rows = tmp_db.fetchall(
            "SELECT * FROM evidence_chains WHERE investigation_id = ? AND entity_id = ?",
            (inv_id, "entity-A"),
        )
        assert len(rows) == 2
        assert all(row["entity_id"] == "entity-A" for row in rows)

    def test_query_by_confidence(self, tmp_db: SQLiteDB):
        """Query evidence chains filtered by confidence returns correct subset."""
        inv_id = self._setup_evidence(tmp_db)
        rows = tmp_db.fetchall(
            "SELECT * FROM evidence_chains WHERE investigation_id = ? AND confidence = ?",
            (inv_id, "confirmed"),
        )
        assert len(rows) == 2
        assert all(row["confidence"] == "confirmed" for row in rows)


class TestContextManager:
    """SQLiteDB supports context manager protocol."""

    def test_context_manager(self, tmp_path: Path):
        """SQLiteDB works as a context manager."""
        db_path = tmp_path / "ctx_test.db"
        with SQLiteDB(str(db_path)) as db:
            rows = db.fetchall(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            assert isinstance(rows, list)
        # After exit, connection should be closed — further ops should fail
        with pytest.raises(Exception):
            db.execute("SELECT 1")


class TestExecuteMany:
    """executemany works for batch inserts."""

    def test_executemany_inserts(self, tmp_db: SQLiteDB):
        """executemany inserts multiple rows correctly."""
        inv_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        tmp_db.execute(
            "INSERT INTO investigations (id, title, created_at, updated_at, status) "
            "VALUES (?, ?, ?, ?, ?)",
            (inv_id, "Test", now, now, "active"),
        )
        messages = [
            (str(uuid.uuid4()), inv_id, "user", "Hello", now),
            (str(uuid.uuid4()), inv_id, "assistant", "Hi there", now),
            (str(uuid.uuid4()), inv_id, "user", "Follow up", now),
        ]
        tmp_db.executemany(
            "INSERT INTO messages (id, investigation_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            messages,
        )
        rows = tmp_db.fetchall(
            "SELECT * FROM messages WHERE investigation_id = ?", (inv_id,)
        )
        assert len(rows) == 3

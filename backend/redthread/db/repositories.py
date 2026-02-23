"""Data access repositories combining SQLite and Graph DB operations.

Each repo takes SQLiteDB and GraphDB instances via dependency injection.
Repositories are the single entry point for all persistence — no direct
DB access from tools or API routes.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from redthread.db.graph import GraphDB
from redthread.db.sqlite import SQLiteDB


def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    """Generate a new UUID string."""
    return str(uuid.uuid4())


class InvestigationRepo:
    """Repository for investigation sessions.

    On create, initializes the investigation record. The graph DB instance
    is shared and scoped by investigation_id in entity properties.
    """

    def __init__(self, db: SQLiteDB, graph: GraphDB) -> None:
        self._db = db
        self._graph = graph

    def create(self, title: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """Create a new investigation and return it as a dict."""
        inv_id = _new_id()
        now = _now_iso()
        meta_json = json.dumps(metadata) if metadata else None
        self._db.execute(
            "INSERT INTO investigations (id, title, created_at, updated_at, status, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (inv_id, title, now, now, "active", meta_json),
        )
        return self.get(inv_id)  # type: ignore[return-value]

    def get(self, investigation_id: str) -> dict[str, Any] | None:
        """Get an investigation by ID."""
        return self._db.fetchone(
            "SELECT * FROM investigations WHERE id = ?", (investigation_id,)
        )

    def list_all(self) -> list[dict[str, Any]]:
        """List all investigations sorted by updated_at descending."""
        return self._db.fetchall(
            "SELECT * FROM investigations ORDER BY updated_at DESC"
        )

    def update_status(self, investigation_id: str, status: str) -> dict[str, Any] | None:
        """Update investigation status and return the updated record."""
        now = _now_iso()
        self._db.execute(
            "UPDATE investigations SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, investigation_id),
        )
        return self.get(investigation_id)


class DatasetRepo:
    """Repository for ingested datasets and their records."""

    def __init__(self, db: SQLiteDB, graph: GraphDB) -> None:
        self._db = db
        self._graph = graph

    def create(
        self,
        investigation_id: str,
        filename: str,
        file_type: str,
        row_count: int | None = None,
        column_names: list[str] | None = None,
        validation_warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a dataset record."""
        ds_id = _new_id()
        now = _now_iso()
        col_json = json.dumps(column_names) if column_names else None
        warn_json = json.dumps(validation_warnings) if validation_warnings else None
        self._db.execute(
            "INSERT INTO datasets "
            "(id, investigation_id, filename, file_type, row_count, "
            "column_names, ingested_at, validation_warnings) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ds_id, investigation_id, filename, file_type, row_count, col_json, now, warn_json),
        )
        return self._db.fetchone("SELECT * FROM datasets WHERE id = ?", (ds_id,))  # type: ignore[return-value]

    def get(self, dataset_id: str) -> dict[str, Any] | None:
        """Get a dataset by ID."""
        return self._db.fetchone("SELECT * FROM datasets WHERE id = ?", (dataset_id,))

    def get_by_investigation(self, investigation_id: str) -> list[dict[str, Any]]:
        """Get all datasets for an investigation."""
        return self._db.fetchall(
            "SELECT * FROM datasets WHERE investigation_id = ? ORDER BY ingested_at DESC",
            (investigation_id,),
        )

    def store_records(self, dataset_id: str, rows: list[dict[str, Any]]) -> int:
        """Store parsed rows as Record entries (batch insert).

        Returns the number of records stored.
        """
        records = []
        for i, row_data in enumerate(rows, start=1):
            records.append((
                _new_id(),
                dataset_id,
                i,
                json.dumps(row_data),
            ))
        self._db.executemany(
            "INSERT INTO records (id, dataset_id, row_number, data) VALUES (?, ?, ?, ?)",
            records,
        )
        return len(records)

    def get_records(self, dataset_id: str) -> list[dict[str, Any]]:
        """Get all records for a dataset, ordered by row_number."""
        return self._db.fetchall(
            "SELECT * FROM records WHERE dataset_id = ? ORDER BY row_number",
            (dataset_id,),
        )


class EvidenceRepo:
    """Repository for evidence chain entries."""

    def __init__(self, db: SQLiteDB, graph: GraphDB) -> None:
        self._db = db
        self._graph = graph

    def create(
        self,
        investigation_id: str,
        claim: str,
        supporting_evidence: str,
        confidence: str,
        entity_id: str | None = None,
        source_record_id: str | None = None,
        source_dataset_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create an evidence chain entry."""
        ec_id = _new_id()
        now = _now_iso()
        meta_json = json.dumps(metadata) if metadata else None
        self._db.execute(
            "INSERT INTO evidence_chains "
            "(id, investigation_id, entity_id, claim, supporting_evidence, "
            "source_record_id, source_dataset_id, confidence, created_at, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ec_id, investigation_id, entity_id, claim, supporting_evidence,
                source_record_id, source_dataset_id, confidence, now, meta_json,
            ),
        )
        return self._db.fetchone(  # type: ignore[return-value]
            "SELECT * FROM evidence_chains WHERE id = ?", (ec_id,)
        )

    def query(
        self,
        investigation_id: str,
        entity_id: str | None = None,
        confidence: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query evidence chains with optional entity_id and confidence filters."""
        sql = "SELECT * FROM evidence_chains WHERE investigation_id = ?"
        params: list[Any] = [investigation_id]

        if entity_id is not None:
            sql += " AND entity_id = ?"
            params.append(entity_id)

        if confidence is not None:
            sql += " AND confidence = ?"
            params.append(confidence)

        sql += " ORDER BY created_at"
        return self._db.fetchall(sql, params)


class TimelineEventRepo:
    """Repository for timeline events (transactions, dated events)."""

    def __init__(self, db: SQLiteDB, graph: GraphDB) -> None:
        self._db = db
        self._graph = graph

    def create(
        self,
        investigation_id: str,
        entity_id: str | None = None,
        entity_name: str | None = None,
        event_date: str = "",
        amount: float | None = None,
        description: str | None = None,
        source_record_id: str | None = None,
        source_dataset_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a timeline event."""
        event_id = _new_id()
        now = _now_iso()
        self._db.execute(
            "INSERT INTO timeline_events "
            "(id, investigation_id, entity_id, entity_name, event_date, "
            "amount, description, source_record_id, source_dataset_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event_id, investigation_id, entity_id, entity_name, event_date,
                amount, description, source_record_id, source_dataset_id, now,
            ),
        )
        return self._db.fetchone(  # type: ignore[return-value]
            "SELECT * FROM timeline_events WHERE id = ?", (event_id,)
        )

    def query_by_investigation(self, investigation_id: str) -> list[dict[str, Any]]:
        """Get all events for an investigation, sorted by event_date."""
        return self._db.fetchall(
            "SELECT * FROM timeline_events WHERE investigation_id = ? ORDER BY event_date",
            (investigation_id,),
        )

    def query_by_entity(
        self, investigation_id: str, entity_id: str,
    ) -> list[dict[str, Any]]:
        """Get events for a specific entity within an investigation."""
        return self._db.fetchall(
            "SELECT * FROM timeline_events "
            "WHERE investigation_id = ? AND entity_id = ? ORDER BY event_date",
            (investigation_id, entity_id),
        )


class MessageRepo:
    """Repository for chat messages."""

    def __init__(self, db: SQLiteDB, graph: GraphDB) -> None:
        self._db = db
        self._graph = graph

    def append(self, investigation_id: str, role: str, content: str) -> dict[str, Any]:
        """Append a message to the conversation history."""
        msg_id = _new_id()
        now = _now_iso()
        self._db.execute(
            "INSERT INTO messages (id, investigation_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (msg_id, investigation_id, role, content, now),
        )
        return self._db.fetchone(  # type: ignore[return-value]
            "SELECT * FROM messages WHERE id = ?", (msg_id,)
        )

    def get_history(self, investigation_id: str) -> list[dict[str, Any]]:
        """Get conversation history for an investigation in chronological order."""
        return self._db.fetchall(
            "SELECT * FROM messages WHERE investigation_id = ? ORDER BY created_at",
            (investigation_id,),
        )

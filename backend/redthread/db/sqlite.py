"""SQLite database schema and connection manager for Redthread.

Provides the SQLiteDB class — the single entry point for all relational
persistence. Enables WAL mode and foreign keys on connect. Creates the
full schema (6 tables) on initialization.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Sequence


# Full schema for all 6 tables.
_SCHEMA_SQL = """
-- Investigation sessions
CREATE TABLE IF NOT EXISTS investigations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    metadata TEXT
);

-- Ingested datasets
CREATE TABLE IF NOT EXISTS datasets (
    id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL REFERENCES investigations(id),
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    row_count INTEGER,
    column_names TEXT,
    ingested_at TEXT NOT NULL,
    validation_warnings TEXT
);

-- Ingested records (normalized rows from datasets)
CREATE TABLE IF NOT EXISTS records (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL REFERENCES datasets(id),
    row_number INTEGER NOT NULL,
    data TEXT NOT NULL
);

-- Evidence chains
CREATE TABLE IF NOT EXISTS evidence_chains (
    id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL REFERENCES investigations(id),
    entity_id TEXT,
    claim TEXT NOT NULL,
    supporting_evidence TEXT NOT NULL,
    source_record_id TEXT REFERENCES records(id),
    source_dataset_id TEXT REFERENCES datasets(id),
    confidence TEXT NOT NULL CHECK(confidence IN ('confirmed','probable','possible','unresolved')),
    created_at TEXT NOT NULL,
    metadata TEXT
);

-- Timeline events
CREATE TABLE IF NOT EXISTS timeline_events (
    id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL REFERENCES investigations(id),
    entity_id TEXT,
    entity_name TEXT,
    event_date TEXT NOT NULL,
    amount REAL,
    description TEXT,
    source_record_id TEXT REFERENCES records(id),
    source_dataset_id TEXT REFERENCES datasets(id),
    created_at TEXT NOT NULL
);

-- Chat messages
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL REFERENCES investigations(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class SQLiteDB:
    """SQLite connection manager with schema auto-creation.

    Usage:
        db = SQLiteDB("/path/to/db.sqlite")
        db.execute("INSERT INTO ...", params)
        rows = db.fetchall("SELECT * FROM ...")

    Or as a context manager:
        with SQLiteDB("/path/to/db.sqlite") as db:
            db.execute(...)
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._configure()
        self._create_schema()

    def _configure(self) -> None:
        """Enable WAL mode and foreign keys."""
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

    def _create_schema(self) -> None:
        """Create all tables if they don't exist."""
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        """Execute a single SQL statement and commit."""
        cursor = self._conn.execute(sql, params)
        self._conn.commit()
        return cursor

    def executemany(self, sql: str, params_seq: Sequence[Sequence[Any]]) -> sqlite3.Cursor:
        """Execute a SQL statement for each set of params and commit."""
        cursor = self._conn.executemany(sql, params_seq)
        self._conn.commit()
        return cursor

    def fetchone(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        """Execute a query and return the first row as a dict, or None."""
        cursor = self._conn.execute(sql, params)
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        """Execute a query and return all rows as a list of dicts."""
        cursor = self._conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def __enter__(self) -> "SQLiteDB":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

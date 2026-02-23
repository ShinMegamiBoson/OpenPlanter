"""Pydantic models matching the SQLite table schemas.

These are shared between the DB layer and API responses.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Investigation(BaseModel):
    """An investigation session."""

    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    status: str = "active"  # active | archived
    metadata: dict[str, Any] | None = None


class Dataset(BaseModel):
    """An ingested dataset (file)."""

    id: str
    investigation_id: str
    filename: str
    file_type: str  # csv | json | xlsx
    row_count: int | None = None
    column_names: list[str] | None = None
    ingested_at: datetime
    validation_warnings: list[str] | None = None


class Record(BaseModel):
    """A single normalized row from a dataset."""

    id: str
    dataset_id: str
    row_number: int
    data: dict[str, Any]


class EvidenceChain(BaseModel):
    """A structured evidence chain entry."""

    id: str
    investigation_id: str
    entity_id: str | None = None
    claim: str
    supporting_evidence: str
    source_record_id: str | None = None
    source_dataset_id: str | None = None
    confidence: str  # confirmed | probable | possible | unresolved
    created_at: datetime
    metadata: dict[str, Any] | None = None


class TimelineEvent(BaseModel):
    """A dated event (transaction, transfer, etc.) for timeline visualization."""

    id: str
    investigation_id: str
    entity_id: str | None = None
    entity_name: str | None = None
    event_date: str  # ISO 8601
    amount: float | None = None
    description: str | None = None
    source_record_id: str | None = None
    source_dataset_id: str | None = None
    created_at: datetime


class Message(BaseModel):
    """A chat message in an investigation session."""

    id: str
    investigation_id: str
    role: str  # user | assistant
    content: str
    created_at: datetime

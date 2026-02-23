"""Tests for REST API routes (Section 9.1)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from redthread.db.graph import NetworkXGraphDB
from redthread.db.repositories import (
    DatasetRepo,
    EvidenceRepo,
    InvestigationRepo,
    MessageRepo,
    TimelineEventRepo,
)
from redthread.db.sqlite import SQLiteDB
from redthread.config import Settings


@pytest.fixture
def app_with_state(tmp_path):
    """Create a FastAPI app with test state."""
    from fastapi import FastAPI
    from redthread.api.routes import router

    app = FastAPI()
    app.include_router(router)

    db = SQLiteDB(str(tmp_path / "test.db"))
    graph_db = NetworkXGraphDB(str(tmp_path / "graph.json"))

    app.state.settings = Settings(
        ANTHROPIC_API_KEY=None,
        UPLOAD_DIR=str(tmp_path / "uploads"),
    )
    app.state.db = db
    app.state.graph_db = graph_db
    app.state.investigation_repo = InvestigationRepo(db, graph_db)
    app.state.dataset_repo = DatasetRepo(db, graph_db)
    app.state.evidence_repo = EvidenceRepo(db, graph_db)
    app.state.timeline_repo = TimelineEventRepo(db, graph_db)
    app.state.message_repo = MessageRepo(db, graph_db)

    return app


@pytest.fixture
def client(app_with_state):
    return TestClient(app_with_state)


@pytest.fixture
def investigation_id(client):
    """Create a test investigation and return its ID."""
    resp = client.post(
        "/api/v1/investigations",
        json={"title": "Test Investigation"},
    )
    assert resp.status_code == 200
    return resp.json()["id"]


# -- Investigation endpoints --------------------------------------------------

def test_create_investigation(client):
    resp = client.post(
        "/api/v1/investigations",
        json={"title": "My Investigation", "metadata": {"case": "123"}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "My Investigation"
    assert data["status"] == "active"
    assert "id" in data


def test_list_investigations(client, investigation_id):
    resp = client.get("/api/v1/investigations")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert any(inv["id"] == investigation_id for inv in data)


def test_get_investigation(client, investigation_id):
    resp = client.get(f"/api/v1/investigations/{investigation_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == investigation_id


def test_get_investigation_not_found(client):
    resp = client.get("/api/v1/investigations/nonexistent")
    assert resp.status_code == 404


def test_archive_investigation(client, investigation_id):
    resp = client.delete(f"/api/v1/investigations/{investigation_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "archived"


def test_archive_investigation_not_found(client):
    resp = client.delete("/api/v1/investigations/nonexistent")
    assert resp.status_code == 404


# -- Evidence endpoints -------------------------------------------------------

def test_get_evidence_empty(client, investigation_id):
    resp = client.get(f"/api/v1/investigations/{investigation_id}/evidence")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["evidence"] == []


def test_get_evidence_with_filter(client, investigation_id, app_with_state):
    # Add evidence directly
    app_with_state.state.evidence_repo.create(
        investigation_id=investigation_id,
        claim="Test claim",
        supporting_evidence="Test evidence",
        confidence="confirmed",
    )
    app_with_state.state.evidence_repo.create(
        investigation_id=investigation_id,
        claim="Possible claim",
        supporting_evidence="Weak evidence",
        confidence="possible",
    )

    # Query with confidence filter
    resp = client.get(
        f"/api/v1/investigations/{investigation_id}/evidence",
        params={"confidence": "confirmed"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["evidence"][0]["confidence"] == "confirmed"


# -- Graph endpoint -----------------------------------------------------------

def test_get_graph_empty(client, investigation_id):
    resp = client.get(f"/api/v1/investigations/{investigation_id}/graph")
    assert resp.status_code == 200
    data = resp.json()
    assert data["nodes"] == []
    assert data["edges"] == []


def test_get_graph_with_data(client, investigation_id, app_with_state):
    graph_db = app_with_state.state.graph_db
    graph_db.add_entity(
        entity_id="e1",
        entity_type="person",
        name="John Smith",
        properties={"investigation_id": investigation_id},
    )
    graph_db.add_entity(
        entity_id="e2",
        entity_type="organization",
        name="Acme Corp",
        properties={"investigation_id": investigation_id},
    )
    graph_db.add_relationship(
        source_id="e1",
        target_id="e2",
        rel_type="AFFILIATED_WITH",
        properties={"investigation_id": investigation_id},
    )

    resp = client.get(f"/api/v1/investigations/{investigation_id}/graph")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["nodes"]) == 2
    assert len(data["edges"]) == 1
    assert data["nodes"][0]["data"]["id"] in ("e1", "e2")
    assert data["edges"][0]["data"]["type"] == "AFFILIATED_WITH"


# -- Timeline endpoint --------------------------------------------------------

def test_get_timeline_empty(client, investigation_id):
    resp = client.get(f"/api/v1/investigations/{investigation_id}/timeline")
    assert resp.status_code == 200
    data = resp.json()
    assert data["events"] == []


def test_get_timeline_with_events(client, investigation_id, app_with_state):
    app_with_state.state.timeline_repo.create(
        investigation_id=investigation_id,
        entity_id="e1",
        entity_name="John Smith",
        event_date="2024-01-15",
        amount=5000.0,
        description="Wire transfer",
    )

    resp = client.get(f"/api/v1/investigations/{investigation_id}/timeline")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["events"]) == 1
    assert data["events"][0]["date"] == "2024-01-15"
    assert data["events"][0]["amount"] == 5000.0


# -- Messages endpoint --------------------------------------------------------

def test_get_messages_empty(client, investigation_id):
    resp = client.get(f"/api/v1/investigations/{investigation_id}/messages")
    assert resp.status_code == 200
    assert resp.json() == []


# -- File upload endpoint -----------------------------------------------------

def test_upload_valid_csv(client, investigation_id):
    content = b"name,amount\nJohn,5000\nJane,3000"
    resp = client.post(
        f"/api/v1/investigations/{investigation_id}/upload",
        files={"file": ("test.csv", io.BytesIO(content), "text/csv")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "uploaded"
    assert data["filename"] == "test.csv"
    assert data["size_bytes"] == len(content)


def test_upload_rejects_unsupported_type(client, investigation_id):
    content = b"hello world"
    resp = client.post(
        f"/api/v1/investigations/{investigation_id}/upload",
        files={"file": ("test.txt", io.BytesIO(content), "text/plain")},
    )
    assert resp.status_code == 400
    assert "Unsupported file type" in resp.json()["detail"]


def test_upload_rejects_missing_investigation(client):
    content = b"name,amount\nJohn,5000"
    resp = client.post(
        "/api/v1/investigations/nonexistent/upload",
        files={"file": ("test.csv", io.BytesIO(content), "text/csv")},
    )
    assert resp.status_code == 404

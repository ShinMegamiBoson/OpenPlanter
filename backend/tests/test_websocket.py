"""Tests for WebSocket endpoint (Section 9.2)."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from redthread.api.websocket import router as ws_router
from redthread.db.graph import NetworkXGraphDB
from redthread.db.repositories import (
    EvidenceRepo,
    InvestigationRepo,
    MessageRepo,
    TimelineEventRepo,
    DatasetRepo,
)
from redthread.db.sqlite import SQLiteDB
from redthread.config import Settings


@pytest.fixture
def app_with_state(tmp_path):
    """Create a FastAPI app with WebSocket routes and test state."""
    app = FastAPI()
    app.include_router(ws_router)

    db = SQLiteDB(str(tmp_path / "test.db"))
    graph_db = NetworkXGraphDB(str(tmp_path / "graph.json"))

    app.state.settings = Settings(ANTHROPIC_API_KEY=None)
    app.state.db = db
    app.state.graph_db = graph_db
    app.state.investigation_repo = InvestigationRepo(db, graph_db)
    app.state.dataset_repo = DatasetRepo(db, graph_db)
    app.state.evidence_repo = EvidenceRepo(db, graph_db)
    app.state.timeline_repo = TimelineEventRepo(db, graph_db)
    app.state.message_repo = MessageRepo(db, graph_db)
    app.state.agent = None  # No agent for tests

    return app


@pytest.fixture
def client(app_with_state):
    return TestClient(app_with_state)


@pytest.fixture
def investigation_id(app_with_state):
    """Create a test investigation."""
    inv = app_with_state.state.investigation_repo.create(title="Test Investigation")
    return inv["id"]


def test_websocket_rejects_nonexistent_investigation(client):
    """WebSocket connection should be rejected for nonexistent investigation."""
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/chat/nonexistent"):
            pass


def test_websocket_accepts_valid_investigation_no_agent(client, investigation_id):
    """WebSocket connects but returns error when agent is not configured."""
    with client.websocket_connect(f"/ws/chat/{investigation_id}") as ws:
        data = ws.receive_json()
        assert data["type"] == "error"
        assert "not configured" in data["message"]


def test_websocket_handles_invalid_json(client, investigation_id, app_with_state):
    """WebSocket should handle invalid JSON gracefully."""
    # Need to set agent to something so the connection stays open
    # Use a mock that won't crash
    class MockAgent:
        pass

    app_with_state.state.agent = MockAgent()

    with client.websocket_connect(f"/ws/chat/{investigation_id}") as ws:
        ws.send_text("not valid json{{{")
        data = ws.receive_json()
        assert data["type"] == "error"
        assert "Invalid JSON" in data["message"]


def test_websocket_handles_unknown_frame_type(client, investigation_id, app_with_state):
    """WebSocket should return error for unknown frame types."""

    class MockAgent:
        pass

    app_with_state.state.agent = MockAgent()

    with client.websocket_connect(f"/ws/chat/{investigation_id}") as ws:
        ws.send_json({"type": "unknown_type"})
        data = ws.receive_json()
        assert data["type"] == "error"
        assert "Unknown frame type" in data["message"]


def test_websocket_handles_empty_message(client, investigation_id, app_with_state):
    """WebSocket should reject empty message content."""

    class MockAgent:
        pass

    app_with_state.state.agent = MockAgent()

    with client.websocket_connect(f"/ws/chat/{investigation_id}") as ws:
        ws.send_json({"type": "message", "content": ""})
        data = ws.receive_json()
        assert data["type"] == "error"
        assert "empty" in data["message"].lower()


def test_websocket_handles_empty_sub_investigation(client, investigation_id, app_with_state):
    """WebSocket should reject empty sub-investigation question."""

    class MockAgent:
        pass

    app_with_state.state.agent = MockAgent()

    with client.websocket_connect(f"/ws/chat/{investigation_id}") as ws:
        ws.send_json({"type": "sub_investigate", "question": "  "})
        data = ws.receive_json()
        assert data["type"] == "error"
        assert "empty" in data["message"].lower()

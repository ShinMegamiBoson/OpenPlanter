"""Tests for the RedthreadAgent client and tool assembly."""

from __future__ import annotations

import pytest

from redthread.agent.client import RedthreadAgent, Repositories
from redthread.agent.prompts import SYSTEM_PROMPT, SUB_INVESTIGATOR_PROMPT_TEMPLATE
from redthread.agent.sdk_adapter import StreamEvent
from redthread.config import Settings
from redthread.db.graph import NetworkXGraphDB
from redthread.db.repositories import (
    DatasetRepo,
    EvidenceRepo,
    MessageRepo,
    TimelineEventRepo,
)
from redthread.db.sqlite import SQLiteDB


@pytest.fixture
def db(tmp_path):
    """Create a SQLite DB in a temp directory."""
    db_path = str(tmp_path / "test.db")
    return SQLiteDB(db_path)


@pytest.fixture
def graph_db(tmp_path):
    """Create a NetworkX graph DB."""
    return NetworkXGraphDB(str(tmp_path / "graph.json"))


@pytest.fixture
def repos(db, graph_db):
    """Create all repositories."""
    return Repositories(
        dataset_repo=DatasetRepo(db, graph_db),
        evidence_repo=EvidenceRepo(db, graph_db),
        timeline_repo=TimelineEventRepo(db, graph_db),
        message_repo=MessageRepo(db, graph_db),
    )


@pytest.fixture
def settings():
    """Create test settings (no real API key)."""
    return Settings(ANTHROPIC_API_KEY=None, EXA_API_KEY=None)


@pytest.fixture
def agent(settings, db, graph_db, repos):
    """Create a RedthreadAgent without API key (for tool registration tests)."""
    return RedthreadAgent(
        settings=settings,
        db=db,
        graph_db=graph_db,
        repos=repos,
    )


# -- Tool registration tests -------------------------------------------------

def test_agent_registers_all_tools(agent):
    """All expected tools should be registered in the tool server."""
    expected_tools = [
        "ingest_file",
        "resolve_entity",
        "add_relationship",
        "query_entity_graph",
        "screen_ofac",
        "web_search",
        "fetch_url",
        "record_evidence",
        "query_evidence",
        "generate_sar_narrative",
        "record_timeline_event",
    ]
    registered = agent.tool_server.list_tools()
    for tool_name in expected_tools:
        assert tool_name in registered, f"Missing tool: {tool_name}"


def test_agent_tool_count(agent):
    """Should have exactly 11 tools registered."""
    assert len(agent.tool_server.list_tools()) == 11


def test_tool_server_anthropic_format(agent):
    """Tools should export valid Anthropic API format."""
    tools = agent.tool_server.to_anthropic_tools()
    assert len(tools) == 11
    for tool in tools:
        assert "name" in tool
        assert "description" in tool
        assert "input_schema" in tool


# -- Tool execution tests (via tool server) -----------------------------------

@pytest.mark.asyncio
async def test_resolve_entity_via_server(agent, graph_db, db):
    """Resolve entity tool should work through the tool server."""
    # Create an investigation first
    db.execute(
        "INSERT INTO investigations (id, title, created_at, updated_at, status) "
        "VALUES (?, ?, ?, ?, ?)",
        ("inv-1", "Test", "2024-01-01", "2024-01-01", "active"),
    )

    result = await agent.tool_server.call_tool("resolve_entity", {
        "name": "Acme Corporation",
        "entity_type": "organization",
        "investigation_id": "inv-1",
    })

    import json
    parsed = json.loads(result)
    assert parsed["status"] == "created"
    assert parsed["name"] == "Acme Corporation"


@pytest.mark.asyncio
async def test_record_evidence_via_server(agent, db):
    """Record evidence tool should work through the tool server."""
    db.execute(
        "INSERT INTO investigations (id, title, created_at, updated_at, status) "
        "VALUES (?, ?, ?, ?, ?)",
        ("inv-1", "Test", "2024-01-01", "2024-01-01", "active"),
    )

    # Use empty source IDs to avoid FK constraints (they become NULL)
    result = await agent.tool_server.call_tool("record_evidence", {
        "investigation_id": "inv-1",
        "claim": "Entity X transacted with Entity Y",
        "supporting_evidence": "Bank records show transfer on 2024-01-15",
        "source_record_id": "",
        "source_dataset_id": "",
        "confidence": "confirmed",
    })

    import json
    parsed = json.loads(result)
    assert parsed["status"] == "recorded"
    assert parsed["confidence"] == "confirmed"


@pytest.mark.asyncio
async def test_web_search_without_api_key(agent):
    """Web search should return error when no API key."""
    result = await agent.tool_server.call_tool("web_search", {
        "query": "test query",
    })
    assert "not available" in result


@pytest.mark.asyncio
async def test_query_evidence_via_server(agent, db):
    """Query evidence tool should work through the tool server."""
    db.execute(
        "INSERT INTO investigations (id, title, created_at, updated_at, status) "
        "VALUES (?, ?, ?, ?, ?)",
        ("inv-1", "Test", "2024-01-01", "2024-01-01", "active"),
    )

    result = await agent.tool_server.call_tool("query_evidence", {
        "investigation_id": "inv-1",
    })

    import json
    parsed = json.loads(result)
    assert parsed["investigation_id"] == "inv-1"
    assert parsed["total"] == 0


# -- Chat without API key tests ----------------------------------------------

@pytest.mark.asyncio
async def test_chat_without_api_key(agent):
    """Chat should yield error event when no API key configured."""
    events = []
    async for event in agent.chat("inv-1", "hello"):
        events.append(event)

    assert len(events) == 1
    assert events[0].event_type == "error"
    assert "ANTHROPIC_API_KEY" in events[0].content


@pytest.mark.asyncio
async def test_sub_investigation_without_api_key(agent):
    """Sub-investigation should return error when no API key."""
    result = await agent.create_sub_investigation("inv-1", "who is entity X?")
    assert "ANTHROPIC_API_KEY" in result


# -- System prompt tests ------------------------------------------------------

def test_system_prompt_contains_identity():
    """System prompt should identify as Redthread."""
    assert "Redthread" in SYSTEM_PROMPT
    assert "financial crime investigation" in SYSTEM_PROMPT


def test_system_prompt_contains_epistemic_discipline():
    """Ported epistemic discipline section should be present."""
    assert "EPISTEMIC DISCIPLINE" in SYSTEM_PROMPT
    assert "skeptical professional" in SYSTEM_PROMPT


def test_system_prompt_contains_evidence_chains():
    """Evidence chain standards should be preserved."""
    assert "EVIDENCE CHAINS" in SYSTEM_PROMPT
    assert "claim" in SYSTEM_PROMPT
    assert "source" in SYSTEM_PROMPT


def test_system_prompt_contains_tool_descriptions():
    """System prompt should describe available tools."""
    assert "ingest_file" in SYSTEM_PROMPT
    assert "resolve_entity" in SYSTEM_PROMPT
    assert "screen_ofac" in SYSTEM_PROMPT
    assert "web_search" in SYSTEM_PROMPT
    assert "record_evidence" in SYSTEM_PROMPT
    assert "generate_sar_narrative" in SYSTEM_PROMPT


def test_system_prompt_contains_sar_disclaimer():
    """SAR narrative guidance should include draft disclaimer."""
    assert "DRAFT" in SYSTEM_PROMPT
    assert "analyst review" in SYSTEM_PROMPT.lower()


def test_system_prompt_no_terminal_references():
    """Terminal-specific content should NOT be in the new prompt."""
    assert "heredoc" not in SYSTEM_PROMPT.lower()
    assert "vim" not in SYSTEM_PROMPT.lower()
    assert "run_shell" not in SYSTEM_PROMPT
    assert "step-limited loop" not in SYSTEM_PROMPT


def test_sub_investigator_prompt_template():
    """Sub-investigator template should format correctly."""
    filled = SUB_INVESTIGATOR_PROMPT_TEMPLATE.format(
        question="Who owns Entity X?",
        context="Known entities: Entity X, Entity Y",
    )
    assert "Who owns Entity X?" in filled
    assert "Known entities" in filled


# -- Message history tests ----------------------------------------------------

def test_build_messages(agent, db):
    """_build_messages should load history and append new message."""
    db.execute(
        "INSERT INTO investigations (id, title, created_at, updated_at, status) "
        "VALUES (?, ?, ?, ?, ?)",
        ("inv-1", "Test", "2024-01-01", "2024-01-01", "active"),
    )

    # Add some history
    agent._repos.message_repo.append("inv-1", "user", "first question")
    agent._repos.message_repo.append("inv-1", "assistant", "first answer")

    messages = agent._build_messages("inv-1", "second question")

    assert len(messages) == 3
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "first question"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "first answer"
    assert messages[2]["role"] == "user"
    assert messages[2]["content"] == "second question"

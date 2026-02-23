"""Tests for redthread.agent.tools.entity — entity graph operations tool.

TDD: These tests were written before the implementation.
Tools are plain async functions (NOT decorated with @tool).
They take graph_db and repos as dependency-injected parameters.
"""

import json
from pathlib import Path

import pytest

from redthread.agent.tools.entity import (
    add_relationship,
    query_entity_graph,
    resolve_entity,
)
from redthread.db.graph import NetworkXGraphDB
from redthread.db.repositories import InvestigationRepo
from redthread.db.sqlite import SQLiteDB


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite_db(tmp_path: Path) -> SQLiteDB:
    """Create a fresh SQLiteDB instance."""
    db_path = tmp_path / "test_entity.db"
    return SQLiteDB(str(db_path))


@pytest.fixture
def graph_db(tmp_path: Path) -> NetworkXGraphDB:
    """Create a fresh NetworkXGraphDB instance."""
    graph_path = tmp_path / "test_entity_graph.json"
    return NetworkXGraphDB(str(graph_path))


@pytest.fixture
def inv_repo(sqlite_db: SQLiteDB, graph_db: NetworkXGraphDB) -> InvestigationRepo:
    """InvestigationRepo with injected dependencies."""
    return InvestigationRepo(sqlite_db, graph_db)


@pytest.fixture
def investigation_id(inv_repo: InvestigationRepo) -> str:
    """Create a test investigation and return its ID."""
    inv = inv_repo.create(title="Entity Test Investigation")
    return inv["id"]


# ---------------------------------------------------------------------------
# resolve_entity
# ---------------------------------------------------------------------------


class TestResolveEntity:
    """Test resolve_entity tool function."""

    @pytest.mark.asyncio
    async def test_resolve_new_entity_creates_node(
        self, graph_db: NetworkXGraphDB, investigation_id: str,
    ):
        """Resolving a new entity creates a node in the graph."""
        result = await resolve_entity(
            graph_db=graph_db,
            name="Acme Corporation",
            entity_type="organization",
            investigation_id=investigation_id,
        )
        parsed = json.loads(result)
        assert parsed["status"] == "created"
        assert parsed["entity_id"] is not None
        assert parsed["name"] == "Acme Corporation"

        # Verify entity exists in graph
        entity = graph_db.get_entity(parsed["entity_id"])
        assert entity is not None
        assert entity["name"] == "Acme Corporation"
        assert entity["entity_type"] == "organization"

    @pytest.mark.asyncio
    async def test_resolve_matching_entity_returns_existing(
        self, graph_db: NetworkXGraphDB, investigation_id: str,
    ):
        """Resolving a name that fuzzy-matches an existing entity returns the existing entity ID."""
        # First, create an entity
        result1 = await resolve_entity(
            graph_db=graph_db,
            name="Acme Corporation",
            entity_type="organization",
            investigation_id=investigation_id,
        )
        parsed1 = json.loads(result1)
        original_id = parsed1["entity_id"]

        # Now resolve a similar name
        result2 = await resolve_entity(
            graph_db=graph_db,
            name="ACME Corp",
            entity_type="organization",
            investigation_id=investigation_id,
        )
        parsed2 = json.loads(result2)

        # Should match the existing entity
        assert parsed2["status"] == "matched"
        assert parsed2["entity_id"] == original_id
        assert "match_score" in parsed2

    @pytest.mark.asyncio
    async def test_resolve_different_entity_creates_new(
        self, graph_db: NetworkXGraphDB, investigation_id: str,
    ):
        """Resolving a clearly different name creates a new entity."""
        # Create first entity
        result1 = await resolve_entity(
            graph_db=graph_db,
            name="Acme Corporation",
            entity_type="organization",
            investigation_id=investigation_id,
        )
        parsed1 = json.loads(result1)

        # Resolve a completely different entity
        result2 = await resolve_entity(
            graph_db=graph_db,
            name="Globex Industries",
            entity_type="organization",
            investigation_id=investigation_id,
        )
        parsed2 = json.loads(result2)

        assert parsed2["status"] == "created"
        assert parsed2["entity_id"] != parsed1["entity_id"]

    @pytest.mark.asyncio
    async def test_resolve_empty_name_returns_error(
        self, graph_db: NetworkXGraphDB, investigation_id: str,
    ):
        """Resolving with an empty name returns an error message."""
        result = await resolve_entity(
            graph_db=graph_db,
            name="",
            entity_type="person",
            investigation_id=investigation_id,
        )
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert "empty" in parsed["message"].lower() or "name" in parsed["message"].lower()

    @pytest.mark.asyncio
    async def test_resolve_with_source_record_id(
        self, graph_db: NetworkXGraphDB, investigation_id: str,
    ):
        """source_record_id is stored in entity properties."""
        result = await resolve_entity(
            graph_db=graph_db,
            name="John Smith",
            entity_type="person",
            investigation_id=investigation_id,
            source_record_id="rec-123",
        )
        parsed = json.loads(result)
        entity = graph_db.get_entity(parsed["entity_id"])
        assert entity is not None
        assert "rec-123" in str(entity.get("properties", {}))

    @pytest.mark.asyncio
    async def test_resolve_person_name_variants(
        self, graph_db: NetworkXGraphDB, investigation_id: str,
    ):
        """Person name variants (John Smith vs Smith, John) resolve to same entity."""
        result1 = await resolve_entity(
            graph_db=graph_db,
            name="John Smith",
            entity_type="person",
            investigation_id=investigation_id,
        )
        parsed1 = json.loads(result1)

        result2 = await resolve_entity(
            graph_db=graph_db,
            name="Smith, John",
            entity_type="person",
            investigation_id=investigation_id,
        )
        parsed2 = json.loads(result2)

        assert parsed2["status"] == "matched"
        assert parsed2["entity_id"] == parsed1["entity_id"]


# ---------------------------------------------------------------------------
# add_relationship
# ---------------------------------------------------------------------------


class TestAddRelationship:
    """Test add_relationship tool function."""

    @pytest.mark.asyncio
    async def test_add_relationship_between_entities(
        self, graph_db: NetworkXGraphDB, investigation_id: str,
    ):
        """Add a relationship between two entities creates an edge in the graph."""
        # Create two entities
        r1 = await resolve_entity(
            graph_db=graph_db, name="Acme Corp",
            entity_type="organization", investigation_id=investigation_id,
        )
        r2 = await resolve_entity(
            graph_db=graph_db, name="John Smith",
            entity_type="person", investigation_id=investigation_id,
        )
        id1 = json.loads(r1)["entity_id"]
        id2 = json.loads(r2)["entity_id"]

        result = await add_relationship(
            graph_db=graph_db,
            source_entity_id=id1,
            target_entity_id=id2,
            relationship_type="AFFILIATED_WITH",
            investigation_id=investigation_id,
        )
        parsed = json.loads(result)
        assert parsed["status"] == "created"

        # Verify edge exists
        rels = graph_db.get_relationships(id1)
        assert len(rels) >= 1
        rel_types = [r["rel_type"] for r in rels]
        assert "AFFILIATED_WITH" in rel_types

    @pytest.mark.asyncio
    async def test_add_relationship_with_properties(
        self, graph_db: NetworkXGraphDB, investigation_id: str,
    ):
        """Relationship properties are stored."""
        r1 = await resolve_entity(
            graph_db=graph_db, name="Entity A",
            entity_type="organization", investigation_id=investigation_id,
        )
        r2 = await resolve_entity(
            graph_db=graph_db, name="Entity B",
            entity_type="organization", investigation_id=investigation_id,
        )
        id1 = json.loads(r1)["entity_id"]
        id2 = json.loads(r2)["entity_id"]

        props = json.dumps({"amount": 50000, "date": "2024-01-15"})
        result = await add_relationship(
            graph_db=graph_db,
            source_entity_id=id1,
            target_entity_id=id2,
            relationship_type="TRANSACTED_WITH",
            properties=props,
            investigation_id=investigation_id,
        )
        parsed = json.loads(result)
        assert parsed["status"] == "created"

    @pytest.mark.asyncio
    async def test_add_relationship_invalid_type_returns_error(
        self, graph_db: NetworkXGraphDB, investigation_id: str,
    ):
        """Invalid relationship type returns an error."""
        r1 = await resolve_entity(
            graph_db=graph_db, name="Entity X",
            entity_type="organization", investigation_id=investigation_id,
        )
        r2 = await resolve_entity(
            graph_db=graph_db, name="Entity Y",
            entity_type="organization", investigation_id=investigation_id,
        )
        id1 = json.loads(r1)["entity_id"]
        id2 = json.loads(r2)["entity_id"]

        result = await add_relationship(
            graph_db=graph_db,
            source_entity_id=id1,
            target_entity_id=id2,
            relationship_type="INVALID_TYPE",
            investigation_id=investigation_id,
        )
        parsed = json.loads(result)
        assert parsed["status"] == "error"


# ---------------------------------------------------------------------------
# query_entity_graph
# ---------------------------------------------------------------------------


class TestQueryEntityGraph:
    """Test query_entity_graph tool function."""

    @pytest.mark.asyncio
    async def test_query_full_graph(
        self, graph_db: NetworkXGraphDB, investigation_id: str,
    ):
        """Query graph for investigation returns all entities and relationships."""
        # Create some entities and relationships
        r1 = await resolve_entity(
            graph_db=graph_db, name="Alice",
            entity_type="person", investigation_id=investigation_id,
        )
        r2 = await resolve_entity(
            graph_db=graph_db, name="Bob",
            entity_type="person", investigation_id=investigation_id,
        )
        id1 = json.loads(r1)["entity_id"]
        id2 = json.loads(r2)["entity_id"]

        await add_relationship(
            graph_db=graph_db, source_entity_id=id1, target_entity_id=id2,
            relationship_type="TRANSACTED_WITH", investigation_id=investigation_id,
        )

        result = await query_entity_graph(
            graph_db=graph_db,
            investigation_id=investigation_id,
        )
        parsed = json.loads(result)

        assert len(parsed["entities"]) == 2
        assert len(parsed["relationships"]) >= 1

    @pytest.mark.asyncio
    async def test_query_specific_entity(
        self, graph_db: NetworkXGraphDB, investigation_id: str,
    ):
        """Query graph for specific entity returns its relationships."""
        r1 = await resolve_entity(
            graph_db=graph_db, name="Charlie",
            entity_type="person", investigation_id=investigation_id,
        )
        r2 = await resolve_entity(
            graph_db=graph_db, name="Dave",
            entity_type="person", investigation_id=investigation_id,
        )
        r3 = await resolve_entity(
            graph_db=graph_db, name="Eve",
            entity_type="person", investigation_id=investigation_id,
        )
        id1 = json.loads(r1)["entity_id"]
        id2 = json.loads(r2)["entity_id"]
        id3 = json.loads(r3)["entity_id"]

        await add_relationship(
            graph_db=graph_db, source_entity_id=id1, target_entity_id=id2,
            relationship_type="AFFILIATED_WITH", investigation_id=investigation_id,
        )
        await add_relationship(
            graph_db=graph_db, source_entity_id=id1, target_entity_id=id3,
            relationship_type="TRANSACTED_WITH", investigation_id=investigation_id,
        )

        result = await query_entity_graph(
            graph_db=graph_db,
            investigation_id=investigation_id,
            entity_id=id1,
        )
        parsed = json.loads(result)

        assert parsed["entity"]["id"] == id1
        assert len(parsed["relationships"]) == 2

    @pytest.mark.asyncio
    async def test_query_empty_graph(
        self, graph_db: NetworkXGraphDB, investigation_id: str,
    ):
        """Query empty graph returns empty entities and relationships."""
        result = await query_entity_graph(
            graph_db=graph_db,
            investigation_id=investigation_id,
        )
        parsed = json.loads(result)
        assert parsed["entities"] == []
        assert parsed["relationships"] == []

    @pytest.mark.asyncio
    async def test_query_nonexistent_entity(
        self, graph_db: NetworkXGraphDB, investigation_id: str,
    ):
        """Query for a nonexistent entity returns an error."""
        result = await query_entity_graph(
            graph_db=graph_db,
            investigation_id=investigation_id,
            entity_id="nonexistent-id",
        )
        parsed = json.loads(result)
        assert parsed["status"] == "error"

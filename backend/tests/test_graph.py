"""Tests for redthread.db.graph — Graph DB interface and NetworkX fallback.

TDD: These tests were written before the implementation.
Tests are written against the NetworkXGraphDB implementation.
"""

import json
from pathlib import Path

import pytest

from redthread.db.graph import NetworkXGraphDB


@pytest.fixture
def graph_db(tmp_path: Path) -> NetworkXGraphDB:
    """Create a fresh NetworkXGraphDB instance with JSON persistence in temp dir."""
    graph_path = tmp_path / "test_graph.json"
    return NetworkXGraphDB(str(graph_path))


@pytest.fixture
def populated_graph(graph_db: NetworkXGraphDB) -> NetworkXGraphDB:
    """Graph with some entities and relationships pre-loaded."""
    graph_db.add_entity("e1", "person", "John Smith", {"investigation_id": "inv-1"})
    graph_db.add_entity("e2", "organization", "Acme Corp", {"investigation_id": "inv-1"})
    graph_db.add_entity("e3", "person", "Jane Doe", {"investigation_id": "inv-1"})
    graph_db.add_entity("e4", "person", "Bob Other", {"investigation_id": "inv-2"})
    graph_db.add_relationship("e1", "e2", "AFFILIATED_WITH", {"role": "director"})
    graph_db.add_relationship("e1", "e3", "TRANSACTED_WITH", {"amount": "50000"})
    graph_db.add_relationship("e2", "e3", "RELATES_TO", {})
    return graph_db


class TestAddAndGetEntity:
    """Add entity and retrieve by ID returns correct data."""

    def test_add_and_get_entity(self, graph_db: NetworkXGraphDB):
        """Add a single entity and retrieve it by ID."""
        graph_db.add_entity(
            "ent-1", "person", "John Smith",
            {"investigation_id": "inv-1", "dob": "1990-01-01"},
        )
        entity = graph_db.get_entity("ent-1")
        assert entity is not None
        assert entity["id"] == "ent-1"
        assert entity["entity_type"] == "person"
        assert entity["name"] == "John Smith"
        assert entity["properties"]["dob"] == "1990-01-01"
        assert entity["properties"]["investigation_id"] == "inv-1"

    def test_get_nonexistent_entity_returns_none(self, graph_db: NetworkXGraphDB):
        """Getting an entity that does not exist returns None."""
        result = graph_db.get_entity("nonexistent-id")
        assert result is None


class TestAddAndGetRelationship:
    """Add relationship between two entities and retrieve relationships."""

    def test_add_and_get_relationship(self, graph_db: NetworkXGraphDB):
        """Add relationship between two entities and retrieve it."""
        graph_db.add_entity("a", "person", "Alice", {"investigation_id": "inv-1"})
        graph_db.add_entity("b", "person", "Bob", {"investigation_id": "inv-1"})
        graph_db.add_relationship("a", "b", "TRANSACTED_WITH", {"amount": "10000"})
        rels = graph_db.get_relationships("a")
        assert len(rels) >= 1
        rel = rels[0]
        assert rel["source_id"] == "a"
        assert rel["target_id"] == "b"
        assert rel["rel_type"] == "TRANSACTED_WITH"
        assert rel["properties"]["amount"] == "10000"

    def test_get_relationships_includes_incoming(self, graph_db: NetworkXGraphDB):
        """get_relationships returns both outgoing and incoming edges."""
        graph_db.add_entity("x", "person", "X", {"investigation_id": "inv-1"})
        graph_db.add_entity("y", "person", "Y", {"investigation_id": "inv-1"})
        graph_db.add_relationship("y", "x", "AFFILIATED_WITH", {})
        rels = graph_db.get_relationships("x")
        assert len(rels) >= 1
        # The relationship Y -> X should appear when querying X
        assert any(r["source_id"] == "y" and r["target_id"] == "x" for r in rels)


class TestGetAllEntities:
    """Get all entities filtered by investigation_id returns correct subset."""

    def test_filter_by_investigation(self, populated_graph: NetworkXGraphDB):
        """Only entities belonging to inv-1 are returned."""
        entities = populated_graph.get_all_entities("inv-1")
        assert len(entities) == 3
        ids = {e["id"] for e in entities}
        assert ids == {"e1", "e2", "e3"}

    def test_filter_by_different_investigation(self, populated_graph: NetworkXGraphDB):
        """Only entities belonging to inv-2 are returned."""
        entities = populated_graph.get_all_entities("inv-2")
        assert len(entities) == 1
        assert entities[0]["id"] == "e4"

    def test_filter_by_nonexistent_investigation(self, populated_graph: NetworkXGraphDB):
        """Non-existent investigation returns empty list."""
        entities = populated_graph.get_all_entities("inv-999")
        assert entities == []


class TestGetAllRelationships:
    """Get all relationships filtered by investigation_id."""

    def test_get_all_relationships_for_investigation(self, populated_graph: NetworkXGraphDB):
        """Returns all relationships where both endpoints belong to the investigation."""
        rels = populated_graph.get_all_relationships("inv-1")
        assert len(rels) == 3

    def test_no_relationships_for_empty_investigation(self, populated_graph: NetworkXGraphDB):
        """Investigation with no relationships returns empty list."""
        rels = populated_graph.get_all_relationships("inv-2")
        assert rels == []


class TestFindPath:
    """Find path between connected and disconnected entities."""

    def test_find_path_between_connected_entities(self, populated_graph: NetworkXGraphDB):
        """Find path between connected entities returns non-empty path."""
        path = populated_graph.find_path("e1", "e3")
        assert len(path) > 0
        # Path should include at least the start and end entities
        path_ids = [node["id"] for node in path]
        assert "e1" in path_ids
        assert "e3" in path_ids

    def test_find_path_between_disconnected_entities(self, populated_graph: NetworkXGraphDB):
        """Find path between disconnected entities returns empty list."""
        path = populated_graph.find_path("e1", "e4")
        assert path == []

    def test_find_path_nonexistent_entity(self, graph_db: NetworkXGraphDB):
        """Find path with nonexistent entity returns empty list."""
        path = graph_db.find_path("nonexistent-1", "nonexistent-2")
        assert path == []


class TestDuplicateEntity:
    """Duplicate entity ID raises or updates gracefully."""

    def test_duplicate_entity_id_updates(self, graph_db: NetworkXGraphDB):
        """Adding an entity with an existing ID updates the entity."""
        graph_db.add_entity("dup-1", "person", "Original Name", {"investigation_id": "inv-1"})
        graph_db.add_entity("dup-1", "person", "Updated Name", {"investigation_id": "inv-1"})
        entity = graph_db.get_entity("dup-1")
        assert entity is not None
        assert entity["name"] == "Updated Name"


class TestClose:
    """Graph DB closes without errors."""

    def test_close_without_errors(self, graph_db: NetworkXGraphDB):
        """Calling close() does not raise."""
        graph_db.add_entity("c1", "person", "Close Test", {"investigation_id": "inv-1"})
        graph_db.close()  # Should not raise

    def test_close_persists_to_json(self, tmp_path: Path):
        """After close(), the graph data is persisted to the JSON file."""
        graph_path = tmp_path / "persist_test.json"
        db = NetworkXGraphDB(str(graph_path))
        db.add_entity("p1", "person", "Persisted", {"investigation_id": "inv-1"})
        db.close()

        # Verify JSON file exists and contains data
        assert graph_path.exists()
        with open(graph_path) as f:
            data = json.load(f)
        assert "nodes" in data
        assert len(data["nodes"]) > 0


class TestJSONPersistence:
    """NetworkXGraphDB loads from and saves to JSON file."""

    def test_reload_from_json(self, tmp_path: Path):
        """Data persisted to JSON can be reloaded by a new instance."""
        graph_path = tmp_path / "reload_test.json"

        # Create and populate
        db1 = NetworkXGraphDB(str(graph_path))
        db1.add_entity("r1", "person", "Reloaded", {"investigation_id": "inv-1"})
        db1.add_entity("r2", "org", "ReloadedOrg", {"investigation_id": "inv-1"})
        db1.add_relationship("r1", "r2", "AFFILIATED_WITH", {"since": "2024"})
        db1.close()

        # Reload
        db2 = NetworkXGraphDB(str(graph_path))
        entity = db2.get_entity("r1")
        assert entity is not None
        assert entity["name"] == "Reloaded"
        rels = db2.get_relationships("r1")
        assert len(rels) >= 1
        db2.close()

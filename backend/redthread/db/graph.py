"""Graph database interface and NetworkX fallback implementation.

Defines a GraphDB Protocol (abstract interface) for graph operations.
Provides NetworkXGraphDB as a working implementation using networkx.MultiDiGraph
with JSON file persistence.

The Protocol makes it easy to add LadybugDB later when the package is validated.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import networkx as nx


@runtime_checkable
class GraphDB(Protocol):
    """Abstract interface for graph database operations.

    Any implementation must support entity (node) and relationship (edge)
    CRUD plus path-finding.
    """

    def add_entity(
        self, entity_id: str, entity_type: str, name: str, properties: dict[str, Any],
    ) -> None:
        """Add or update an entity (node) in the graph."""
        ...

    def add_relationship(
        self, source_id: str, target_id: str, rel_type: str, properties: dict[str, Any],
    ) -> None:
        """Add a directed relationship (edge) between two entities."""
        ...

    def get_entity(self, entity_id: str) -> dict[str, Any] | None:
        """Get an entity by ID. Returns None if not found."""
        ...

    def get_relationships(self, entity_id: str) -> list[dict[str, Any]]:
        """Get all relationships (both incoming and outgoing) for an entity."""
        ...

    def get_all_entities(self, investigation_id: str) -> list[dict[str, Any]]:
        """Get all entities belonging to an investigation."""
        ...

    def get_all_relationships(self, investigation_id: str) -> list[dict[str, Any]]:
        """Get all relationships where both endpoints belong to the investigation."""
        ...

    def find_path(self, source_id: str, target_id: str) -> list[dict[str, Any]]:
        """Find a path between two entities. Returns list of entity dicts along the path,
        or empty list if no path exists."""
        ...

    def close(self) -> None:
        """Persist any in-memory state and release resources."""
        ...


class NetworkXGraphDB:
    """Graph DB implementation backed by networkx.MultiDiGraph with JSON persistence.

    On init, loads from a JSON file if it exists. On close(), persists back to the
    same file. All operations are in-memory between open and close.

    JSON format:
    {
        "nodes": [
            {"id": "...", "entity_type": "...", "name": "...", "properties": {...}}
        ],
        "edges": [
            {"source_id": "...", "target_id": "...", "rel_type": "...", "properties": {...}}
        ]
    }
    """

    def __init__(self, graph_path: str) -> None:
        self._graph_path = Path(graph_path)
        self._graph: nx.MultiDiGraph = nx.MultiDiGraph()
        self._load()

    def _load(self) -> None:
        """Load graph data from JSON file if it exists."""
        if not self._graph_path.exists():
            return
        try:
            with open(self._graph_path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return

        for node in data.get("nodes", []):
            self._graph.add_node(
                node["id"],
                entity_type=node["entity_type"],
                name=node["name"],
                properties=node.get("properties", {}),
            )
        for edge in data.get("edges", []):
            self._graph.add_edge(
                edge["source_id"],
                edge["target_id"],
                rel_type=edge["rel_type"],
                properties=edge.get("properties", {}),
            )

    def _save(self) -> None:
        """Persist graph data to JSON file."""
        nodes = []
        for node_id, attrs in self._graph.nodes(data=True):
            nodes.append({
                "id": node_id,
                "entity_type": attrs.get("entity_type", ""),
                "name": attrs.get("name", ""),
                "properties": attrs.get("properties", {}),
            })

        edges = []
        for source, target, attrs in self._graph.edges(data=True):
            edges.append({
                "source_id": source,
                "target_id": target,
                "rel_type": attrs.get("rel_type", ""),
                "properties": attrs.get("properties", {}),
            })

        self._graph_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._graph_path, "w") as f:
            json.dump({"nodes": nodes, "edges": edges}, f, indent=2)

    def add_entity(
        self, entity_id: str, entity_type: str, name: str, properties: dict[str, Any],
    ) -> None:
        """Add or update an entity node."""
        self._graph.add_node(
            entity_id,
            entity_type=entity_type,
            name=name,
            properties=dict(properties),  # defensive copy
        )

    def add_relationship(
        self, source_id: str, target_id: str, rel_type: str, properties: dict[str, Any],
    ) -> None:
        """Add a directed relationship edge."""
        self._graph.add_edge(
            source_id, target_id,
            rel_type=rel_type,
            properties=dict(properties),
        )

    def get_entity(self, entity_id: str) -> dict[str, Any] | None:
        """Get entity by ID, or None if not found."""
        if entity_id not in self._graph:
            return None
        attrs = self._graph.nodes[entity_id]
        return {
            "id": entity_id,
            "entity_type": attrs.get("entity_type", ""),
            "name": attrs.get("name", ""),
            "properties": attrs.get("properties", {}),
        }

    def get_relationships(self, entity_id: str) -> list[dict[str, Any]]:
        """Get all relationships (outgoing + incoming) for an entity."""
        if entity_id not in self._graph:
            return []
        results: list[dict[str, Any]] = []

        # Outgoing edges
        for _, target, attrs in self._graph.out_edges(entity_id, data=True):
            results.append({
                "source_id": entity_id,
                "target_id": target,
                "rel_type": attrs.get("rel_type", ""),
                "properties": attrs.get("properties", {}),
            })

        # Incoming edges
        for source, _, attrs in self._graph.in_edges(entity_id, data=True):
            results.append({
                "source_id": source,
                "target_id": entity_id,
                "rel_type": attrs.get("rel_type", ""),
                "properties": attrs.get("properties", {}),
            })

        return results

    def get_all_entities(self, investigation_id: str) -> list[dict[str, Any]]:
        """Get all entities belonging to an investigation (by investigation_id in properties)."""
        results: list[dict[str, Any]] = []
        for node_id, attrs in self._graph.nodes(data=True):
            props = attrs.get("properties", {})
            if props.get("investigation_id") == investigation_id:
                results.append({
                    "id": node_id,
                    "entity_type": attrs.get("entity_type", ""),
                    "name": attrs.get("name", ""),
                    "properties": props,
                })
        return results

    def get_all_relationships(self, investigation_id: str) -> list[dict[str, Any]]:
        """Get all relationships where both endpoints belong to the investigation."""
        # First, get the set of entity IDs in this investigation
        inv_entity_ids = {
            node_id
            for node_id, attrs in self._graph.nodes(data=True)
            if attrs.get("properties", {}).get("investigation_id") == investigation_id
        }

        results: list[dict[str, Any]] = []
        for source, target, attrs in self._graph.edges(data=True):
            if source in inv_entity_ids and target in inv_entity_ids:
                results.append({
                    "source_id": source,
                    "target_id": target,
                    "rel_type": attrs.get("rel_type", ""),
                    "properties": attrs.get("properties", {}),
                })
        return results

    def find_path(self, source_id: str, target_id: str) -> list[dict[str, Any]]:
        """Find shortest path between two entities. Returns entity dicts along the path."""
        if source_id not in self._graph or target_id not in self._graph:
            return []

        # Use the undirected view for path finding (relationships are bidirectional
        # in investigation context)
        undirected = self._graph.to_undirected()
        try:
            path_nodes = nx.shortest_path(undirected, source_id, target_id)
        except nx.NetworkXNoPath:
            return []

        result: list[dict[str, Any]] = []
        for node_id in path_nodes:
            entity = self.get_entity(node_id)
            if entity is not None:
                result.append(entity)
        return result

    def close(self) -> None:
        """Persist graph state to JSON file."""
        self._save()

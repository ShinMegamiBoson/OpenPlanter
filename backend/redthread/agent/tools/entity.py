"""Entity graph operations tools for the Redthread agent.

These are plain async functions (NOT decorated with @tool).
The SDK adapter will wrap them with the decorator in section 8.
Tools take graph_db as a dependency-injection parameter.

Operations:
- resolve_entity: compare against all entities in investigation, create or return existing
- add_relationship: add typed edge in graph
- query_entity_graph: return full graph or single entity's relationships
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from redthread.db.graph import GraphDB
from redthread.entity.pairwise import compare_entities, THRESHOLD_PROBABLE


# Valid relationship types matching the graph DB schema
VALID_RELATIONSHIP_TYPES = frozenset({
    "RELATES_TO",
    "TRANSACTED_WITH",
    "AFFILIATED_WITH",
    "LOCATED_AT",
})


def _new_id() -> str:
    """Generate a new UUID string."""
    return str(uuid.uuid4())


async def resolve_entity(
    graph_db: GraphDB,
    name: str,
    entity_type: str,
    investigation_id: str,
    source_record_id: str = "",
) -> str:
    """Resolve an entity name against known entities in the investigation graph.

    If a match is found above the 'probable' threshold, returns the existing entity.
    If no match, creates a new entity node. Returns the entity ID and any matches found.

    Parameters
    ----------
    graph_db : GraphDB
        Injected graph database instance.
    name : str
        Entity name to resolve.
    entity_type : str
        Type of entity: 'person', 'organization', or 'unknown'.
    investigation_id : str
        Investigation this entity belongs to.
    source_record_id : str
        Optional reference to the source record.

    Returns
    -------
    str
        JSON string with resolution result.
    """
    if not name or not name.strip():
        return json.dumps({
            "status": "error",
            "message": "Entity name cannot be empty",
        })

    # Step 1: Fetch all entities for the investigation
    existing_entities = graph_db.get_all_entities(investigation_id)

    # Step 2: Compare input name against each existing entity
    best_match: dict[str, Any] | None = None
    best_score: float = 0.0
    best_result = None

    for entity in existing_entities:
        match_result = compare_entities(name, entity["name"], entity_type=entity_type)
        if match_result.score > best_score:
            best_score = match_result.score
            best_match = entity
            best_result = match_result

    # Step 3: If best match >= probable threshold, return existing entity
    if best_match is not None and best_score >= THRESHOLD_PROBABLE:
        return json.dumps({
            "status": "matched",
            "entity_id": best_match["id"],
            "name": best_match["name"],
            "entity_type": best_match["entity_type"],
            "match_score": round(best_score, 4),
            "match_type": best_result.match_type if best_result else "unknown",
            "message": (
                f"Matched '{name}' to existing entity '{best_match['name']}' "
                f"(score: {best_score:.2f})"
            ),
        })

    # Step 4: No match found — create new entity node
    entity_id = _new_id()
    properties: dict[str, Any] = {
        "investigation_id": investigation_id,
    }
    if source_record_id:
        properties["source_record_ids"] = [source_record_id]

    graph_db.add_entity(
        entity_id=entity_id,
        entity_type=entity_type,
        name=name,
        properties=properties,
    )

    return json.dumps({
        "status": "created",
        "entity_id": entity_id,
        "name": name,
        "entity_type": entity_type,
        "message": f"Created new entity '{name}' ({entity_type})",
    })


async def add_relationship(
    graph_db: GraphDB,
    source_entity_id: str,
    target_entity_id: str,
    relationship_type: str,
    properties: str = "{}",
    investigation_id: str = "",
) -> str:
    """Add a typed relationship between two entities in the investigation graph.

    Parameters
    ----------
    graph_db : GraphDB
        Injected graph database instance.
    source_entity_id : str
        ID of the source entity.
    target_entity_id : str
        ID of the target entity.
    relationship_type : str
        One of: TRANSACTED_WITH, AFFILIATED_WITH, LOCATED_AT, RELATES_TO.
    properties : str
        JSON string of relationship properties.
    investigation_id : str
        Investigation context (for validation).

    Returns
    -------
    str
        JSON string with result.
    """
    # Validate relationship type
    if relationship_type not in VALID_RELATIONSHIP_TYPES:
        return json.dumps({
            "status": "error",
            "message": (
                f"Invalid relationship type '{relationship_type}'. "
                f"Must be one of: {', '.join(sorted(VALID_RELATIONSHIP_TYPES))}"
            ),
        })

    # Validate entities exist
    source = graph_db.get_entity(source_entity_id)
    target = graph_db.get_entity(target_entity_id)

    if source is None:
        return json.dumps({
            "status": "error",
            "message": f"Source entity '{source_entity_id}' not found in graph",
        })
    if target is None:
        return json.dumps({
            "status": "error",
            "message": f"Target entity '{target_entity_id}' not found in graph",
        })

    # Parse properties
    try:
        props = json.loads(properties) if isinstance(properties, str) else properties
    except json.JSONDecodeError:
        props = {}

    if investigation_id:
        props["investigation_id"] = investigation_id

    # Add the relationship
    graph_db.add_relationship(
        source_id=source_entity_id,
        target_id=target_entity_id,
        rel_type=relationship_type,
        properties=props,
    )

    return json.dumps({
        "status": "created",
        "source_entity_id": source_entity_id,
        "target_entity_id": target_entity_id,
        "relationship_type": relationship_type,
        "message": (
            f"Created {relationship_type} relationship: "
            f"'{source['name']}' -> '{target['name']}'"
        ),
    })


async def query_entity_graph(
    graph_db: GraphDB,
    investigation_id: str,
    entity_id: str = "",
) -> str:
    """Query the entity graph.

    If entity_id is provided, returns that entity and its immediate relationships.
    Otherwise returns the full graph for the investigation.

    Parameters
    ----------
    graph_db : GraphDB
        Injected graph database instance.
    investigation_id : str
        Investigation to query.
    entity_id : str
        Optional specific entity to query.

    Returns
    -------
    str
        JSON string with graph data.
    """
    if entity_id:
        # Query specific entity
        entity = graph_db.get_entity(entity_id)
        if entity is None:
            return json.dumps({
                "status": "error",
                "message": f"Entity '{entity_id}' not found",
            })

        relationships = graph_db.get_relationships(entity_id)
        return json.dumps({
            "entity": entity,
            "relationships": relationships,
        })

    # Query full graph for investigation
    entities = graph_db.get_all_entities(investigation_id)
    relationships = graph_db.get_all_relationships(investigation_id)

    return json.dumps({
        "entities": entities,
        "relationships": relationships,
        "total_entities": len(entities),
        "total_relationships": len(relationships),
    })

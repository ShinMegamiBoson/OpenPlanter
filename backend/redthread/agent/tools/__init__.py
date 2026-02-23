"""Redthread agent tools — investigation capabilities registered with the SDK adapter.

Each tool is a plain async function with dependency injection. This module
creates ToolDefinition entries and assembles them into a ToolServer for
the agent client.
"""

from __future__ import annotations

from typing import Any

from redthread.agent.sdk_adapter import ToolDefinition, ToolServer
from redthread.db.graph import GraphDB
from redthread.db.repositories import (
    DatasetRepo,
    EvidenceRepo,
    MessageRepo,
    TimelineEventRepo,
)
from redthread.db.sqlite import SQLiteDB
from redthread.search.exa import ExaClient

# Import all tool functions
from redthread.agent.tools.ingest import ingest_file
from redthread.agent.tools.entity import (
    resolve_entity,
    add_relationship,
    query_entity_graph,
)
from redthread.agent.tools.search import web_search, fetch_url
from redthread.agent.tools.evidence import record_evidence, query_evidence
from redthread.agent.tools.sar import generate_sar_narrative
from redthread.agent.tools.timeline import record_timeline_event


def create_tool_server(
    db: SQLiteDB,
    graph_db: GraphDB,
    dataset_repo: DatasetRepo,
    evidence_repo: EvidenceRepo,
    timeline_repo: TimelineEventRepo,
    message_repo: MessageRepo,
    exa_client: ExaClient | None = None,
) -> ToolServer:
    """Create a ToolServer with all investigation tools registered.

    Each tool's injected dependencies are bound via closures so the agent
    only passes the parameters it controls (investigation_id, entity_name, etc.).

    Parameters
    ----------
    db : SQLiteDB
        Database instance (needed for OFAC screening).
    graph_db : GraphDB
        Entity graph database.
    dataset_repo : DatasetRepo
        Dataset + records repository.
    evidence_repo : EvidenceRepo
        Evidence chain repository.
    timeline_repo : TimelineEventRepo
        Timeline event repository.
    message_repo : MessageRepo
        Chat message repository.
    exa_client : ExaClient | None
        Exa web search client (None if no API key configured).
    """
    server = ToolServer("redthread")

    # -- ingest_file ----------------------------------------------------------
    async def _ingest_file(
        file_path: str,
        investigation_id: str,
        description: str = "",
    ) -> str:
        return await ingest_file(dataset_repo, file_path, investigation_id, description)

    server.register(ToolDefinition(
        name="ingest_file",
        description=(
            "Ingest a local data file (CSV, JSON, XLSX) into the investigation. "
            "Parses the file, stores records in the database, and returns a summary "
            "with column names, row count, and any validation warnings."
        ),
        parameters={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file on disk.",
                },
                "investigation_id": {
                    "type": "string",
                    "description": "ID of the investigation to associate with.",
                },
                "description": {
                    "type": "string",
                    "description": "Optional description of the file contents.",
                    "default": "",
                },
            },
            "required": ["file_path", "investigation_id"],
        },
        handler=_ingest_file,
    ))

    # -- resolve_entity -------------------------------------------------------
    async def _resolve_entity(
        name: str,
        entity_type: str,
        investigation_id: str,
        source_record_id: str = "",
    ) -> str:
        return await resolve_entity(graph_db, name, entity_type, investigation_id, source_record_id)

    server.register(ToolDefinition(
        name="resolve_entity",
        description=(
            "Resolve an entity name against the investigation's entity graph using "
            "fuzzy matching. If a match is found, returns the existing entity. "
            "If no match, creates a new entity node."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Entity name to resolve.",
                },
                "entity_type": {
                    "type": "string",
                    "description": "Type: 'person', 'organization', or 'unknown'.",
                    "enum": ["person", "organization", "unknown"],
                },
                "investigation_id": {
                    "type": "string",
                    "description": "Investigation ID.",
                },
                "source_record_id": {
                    "type": "string",
                    "description": "Optional source record reference.",
                    "default": "",
                },
            },
            "required": ["name", "entity_type", "investigation_id"],
        },
        handler=_resolve_entity,
    ))

    # -- add_relationship -----------------------------------------------------
    async def _add_relationship(
        source_entity_id: str,
        target_entity_id: str,
        relationship_type: str,
        properties: str = "{}",
        investigation_id: str = "",
    ) -> str:
        return await add_relationship(
            graph_db, source_entity_id, target_entity_id,
            relationship_type, properties, investigation_id,
        )

    server.register(ToolDefinition(
        name="add_relationship",
        description=(
            "Add a typed relationship between two entities in the investigation graph. "
            "Types: TRANSACTED_WITH, AFFILIATED_WITH, LOCATED_AT, RELATES_TO."
        ),
        parameters={
            "type": "object",
            "properties": {
                "source_entity_id": {
                    "type": "string",
                    "description": "ID of the source entity.",
                },
                "target_entity_id": {
                    "type": "string",
                    "description": "ID of the target entity.",
                },
                "relationship_type": {
                    "type": "string",
                    "description": "Relationship type.",
                    "enum": ["TRANSACTED_WITH", "AFFILIATED_WITH", "LOCATED_AT", "RELATES_TO"],
                },
                "properties": {
                    "type": "string",
                    "description": "JSON string of relationship properties.",
                    "default": "{}",
                },
                "investigation_id": {
                    "type": "string",
                    "description": "Investigation context.",
                    "default": "",
                },
            },
            "required": ["source_entity_id", "target_entity_id", "relationship_type"],
        },
        handler=_add_relationship,
    ))

    # -- query_entity_graph ---------------------------------------------------
    async def _query_entity_graph(
        investigation_id: str,
        entity_id: str = "",
    ) -> str:
        return await query_entity_graph(graph_db, investigation_id, entity_id)

    server.register(ToolDefinition(
        name="query_entity_graph",
        description=(
            "Query the entity graph. If entity_id is provided, returns that entity "
            "and its immediate relationships. Otherwise returns the full graph."
        ),
        parameters={
            "type": "object",
            "properties": {
                "investigation_id": {
                    "type": "string",
                    "description": "Investigation to query.",
                },
                "entity_id": {
                    "type": "string",
                    "description": "Optional specific entity to query.",
                    "default": "",
                },
            },
            "required": ["investigation_id"],
        },
        handler=_query_entity_graph,
    ))

    # -- screen_ofac ----------------------------------------------------------
    # OFAC tool is registered conditionally (may not have SDN data loaded)
    async def _screen_ofac(
        entity_name: str,
        investigation_id: str,
        top_n: int = 10,
    ) -> str:
        # Lazy import to avoid circular dependency and allow OFAC module to be optional
        from redthread.agent.tools.ofac import screen_ofac
        return await screen_ofac(entity_name, investigation_id, db, top_n)

    server.register(ToolDefinition(
        name="screen_ofac",
        description=(
            "Screen an entity name against the OFAC/SDN sanctions list. "
            "Returns matches with confidence levels. Results are for analyst "
            "review, not automated decisioning."
        ),
        parameters={
            "type": "object",
            "properties": {
                "entity_name": {
                    "type": "string",
                    "description": "Entity name to screen.",
                },
                "investigation_id": {
                    "type": "string",
                    "description": "Investigation context.",
                },
                "top_n": {
                    "type": "integer",
                    "description": "Maximum number of matches to return.",
                    "default": 10,
                },
            },
            "required": ["entity_name", "investigation_id"],
        },
        handler=_screen_ofac,
    ))

    # -- web_search -----------------------------------------------------------
    async def _web_search(
        query: str,
        num_results: int = 10,
    ) -> str:
        if exa_client is None:
            return "Web search is not available. EXA_API_KEY is not configured."
        return await web_search(exa_client, query, num_results)

    server.register(ToolDefinition(
        name="web_search",
        description=(
            "Search the web for information about entities, public records, "
            "news, or supplementary data. Returns titles, URLs, and snippets."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query string.",
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of results to return (1-20).",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
        handler=_web_search,
    ))

    # -- fetch_url ------------------------------------------------------------
    async def _fetch_url(url: str) -> str:
        if exa_client is None:
            return "URL fetching is not available. EXA_API_KEY is not configured."
        return await fetch_url(exa_client, url)

    server.register(ToolDefinition(
        name="fetch_url",
        description=(
            "Fetch and extract text content from a specific URL. Useful for "
            "reading public records, news articles, or corporate filings."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to fetch content from.",
                },
            },
            "required": ["url"],
        },
        handler=_fetch_url,
    ))

    # -- record_evidence ------------------------------------------------------
    async def _record_evidence(
        investigation_id: str,
        claim: str,
        supporting_evidence: str,
        source_record_id: str,
        source_dataset_id: str,
        confidence: str,
        entity_id: str = "",
    ) -> str:
        return await record_evidence(
            evidence_repo, investigation_id, claim,
            supporting_evidence, source_record_id, source_dataset_id,
            confidence, entity_id,
        )

    server.register(ToolDefinition(
        name="record_evidence",
        description=(
            "Record a finding as a structured evidence chain entry. Every claim "
            "must trace to a specific record in a specific dataset. Confidence: "
            "confirmed, probable, possible, or unresolved."
        ),
        parameters={
            "type": "object",
            "properties": {
                "investigation_id": {
                    "type": "string",
                    "description": "Investigation this evidence belongs to.",
                },
                "claim": {
                    "type": "string",
                    "description": "The factual claim being recorded.",
                },
                "supporting_evidence": {
                    "type": "string",
                    "description": "Description of evidence supporting the claim.",
                },
                "source_record_id": {
                    "type": "string",
                    "description": "ID of the source record.",
                },
                "source_dataset_id": {
                    "type": "string",
                    "description": "ID of the source dataset.",
                },
                "confidence": {
                    "type": "string",
                    "description": "Confidence level.",
                    "enum": ["confirmed", "probable", "possible", "unresolved"],
                },
                "entity_id": {
                    "type": "string",
                    "description": "Optional entity this evidence relates to.",
                    "default": "",
                },
            },
            "required": [
                "investigation_id", "claim", "supporting_evidence",
                "source_record_id", "source_dataset_id", "confidence",
            ],
        },
        handler=_record_evidence,
    ))

    # -- query_evidence -------------------------------------------------------
    async def _query_evidence(
        investigation_id: str,
        entity_id: str = "",
        confidence: str = "",
    ) -> str:
        return await query_evidence(evidence_repo, investigation_id, entity_id, confidence)

    server.register(ToolDefinition(
        name="query_evidence",
        description=(
            "Query accumulated evidence chains with optional filters by entity "
            "or confidence level."
        ),
        parameters={
            "type": "object",
            "properties": {
                "investigation_id": {
                    "type": "string",
                    "description": "Investigation to query evidence for.",
                },
                "entity_id": {
                    "type": "string",
                    "description": "Optional entity filter.",
                    "default": "",
                },
                "confidence": {
                    "type": "string",
                    "description": "Optional confidence level filter.",
                    "default": "",
                },
            },
            "required": ["investigation_id"],
        },
        handler=_query_evidence,
    ))

    # -- generate_sar_narrative -----------------------------------------------
    async def _generate_sar_narrative(
        investigation_id: str,
        subject_entity_ids: str = "",
    ) -> str:
        return await generate_sar_narrative(
            evidence_repo, graph_db, investigation_id, subject_entity_ids,
        )

    server.register(ToolDefinition(
        name="generate_sar_narrative",
        description=(
            "Generate a draft SAR narrative from accumulated evidence. "
            "IMPORTANT: Output is a DRAFT requiring analyst review and editing "
            "before any regulatory submission."
        ),
        parameters={
            "type": "object",
            "properties": {
                "investigation_id": {
                    "type": "string",
                    "description": "Investigation to generate narrative for.",
                },
                "subject_entity_ids": {
                    "type": "string",
                    "description": "Comma-separated entity IDs for subjects.",
                    "default": "",
                },
            },
            "required": ["investigation_id"],
        },
        handler=_generate_sar_narrative,
    ))

    # -- record_timeline_event ------------------------------------------------
    async def _record_timeline_event(
        investigation_id: str,
        entity_id: str,
        entity_name: str,
        event_date: str,
        amount: float = 0.0,
        description: str = "",
        source_record_id: str = "",
        source_dataset_id: str = "",
    ) -> str:
        return await record_timeline_event(
            timeline_repo, investigation_id, entity_id, entity_name,
            event_date, amount, description, source_record_id, source_dataset_id,
        )

    server.register(ToolDefinition(
        name="record_timeline_event",
        description=(
            "Record a transaction or event for the timeline visualization. "
            "Call when you identify dated transactions, transfers, or events."
        ),
        parameters={
            "type": "object",
            "properties": {
                "investigation_id": {
                    "type": "string",
                    "description": "Investigation this event belongs to.",
                },
                "entity_id": {
                    "type": "string",
                    "description": "Entity associated with this event.",
                },
                "entity_name": {
                    "type": "string",
                    "description": "Human-readable entity name.",
                },
                "event_date": {
                    "type": "string",
                    "description": "Date in ISO 8601 format (e.g., 2024-01-15).",
                },
                "amount": {
                    "type": "number",
                    "description": "Transaction amount.",
                    "default": 0.0,
                },
                "description": {
                    "type": "string",
                    "description": "Event description.",
                    "default": "",
                },
                "source_record_id": {
                    "type": "string",
                    "description": "Optional source record ID.",
                    "default": "",
                },
                "source_dataset_id": {
                    "type": "string",
                    "description": "Optional source dataset ID.",
                    "default": "",
                },
            },
            "required": ["investigation_id", "entity_id", "entity_name", "event_date"],
        },
        handler=_record_timeline_event,
    ))

    return server

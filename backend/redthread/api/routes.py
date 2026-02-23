"""REST API routes for the Redthread backend.

All endpoints are under /api/v1. Routes receive dependencies
(repos, graph_db) via FastAPI's dependency injection or app.state.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1")

ALLOWED_EXTENSIONS = {".csv", ".json", ".xlsx"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


# -- Request/Response models --------------------------------------------------

class CreateInvestigationRequest(BaseModel):
    title: str
    metadata: dict[str, Any] | None = None


# -- Helper to get state from app ---------------------------------------------

def _get_state(request: Request) -> Any:
    """Get app state (repos, settings, etc.)."""
    return request.app.state


# -- Investigation endpoints ---------------------------------------------------

@router.post("/investigations")
async def create_investigation(
    body: CreateInvestigationRequest,
    request: Request,
) -> dict[str, Any]:
    """Create a new investigation."""
    state = _get_state(request)
    investigation = state.investigation_repo.create(
        title=body.title,
        metadata=body.metadata,
    )
    return investigation


@router.get("/investigations")
async def list_investigations(request: Request) -> list[dict[str, Any]]:
    """List all investigations."""
    state = _get_state(request)
    return state.investigation_repo.list_all()


@router.get("/investigations/{investigation_id}")
async def get_investigation(
    investigation_id: str,
    request: Request,
) -> dict[str, Any]:
    """Get investigation details."""
    state = _get_state(request)
    investigation = state.investigation_repo.get(investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return investigation


@router.delete("/investigations/{investigation_id}")
async def archive_investigation(
    investigation_id: str,
    request: Request,
) -> dict[str, Any]:
    """Archive an investigation (soft delete)."""
    state = _get_state(request)
    investigation = state.investigation_repo.get(investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    updated = state.investigation_repo.update_status(investigation_id, "archived")
    return updated


# -- Evidence endpoints -------------------------------------------------------

@router.get("/investigations/{investigation_id}/evidence")
async def get_evidence(
    investigation_id: str,
    request: Request,
    entity_id: str | None = None,
    confidence: str | None = None,
) -> dict[str, Any]:
    """Get evidence chains for an investigation, with optional filters."""
    state = _get_state(request)
    entries = state.evidence_repo.query(
        investigation_id=investigation_id,
        entity_id=entity_id,
        confidence=confidence,
    )
    return {
        "investigation_id": investigation_id,
        "evidence": entries,
        "total": len(entries),
    }


# -- Graph endpoint -----------------------------------------------------------

@router.get("/investigations/{investigation_id}/graph")
async def get_graph(
    investigation_id: str,
    request: Request,
) -> dict[str, Any]:
    """Get entity graph formatted for Cytoscape.js."""
    state = _get_state(request)
    entities = state.graph_db.get_all_entities(investigation_id)
    relationships = state.graph_db.get_all_relationships(investigation_id)

    # Format for Cytoscape.js
    nodes = [
        {
            "data": {
                "id": entity["id"],
                "label": entity.get("name", "Unknown"),
                "type": entity.get("entity_type", "unknown"),
            },
        }
        for entity in entities
    ]
    edges = [
        {
            "data": {
                "source": rel["source_id"],
                "target": rel["target_id"],
                "type": rel.get("rel_type", "RELATES_TO"),
            },
        }
        for rel in relationships
    ]

    return {"nodes": nodes, "edges": edges}


# -- Timeline endpoint --------------------------------------------------------

@router.get("/investigations/{investigation_id}/timeline")
async def get_timeline(
    investigation_id: str,
    request: Request,
) -> dict[str, Any]:
    """Get timeline events formatted for Recharts."""
    state = _get_state(request)
    events = state.timeline_repo.query_by_investigation(investigation_id)

    formatted_events = [
        {
            "date": event["event_date"],
            "entity_id": event.get("entity_id"),
            "entity_name": event.get("entity_name"),
            "amount": event.get("amount"),
            "description": event.get("description"),
        }
        for event in events
    ]

    return {"events": formatted_events}


# -- Messages endpoint --------------------------------------------------------

@router.get("/investigations/{investigation_id}/messages")
async def get_messages(
    investigation_id: str,
    request: Request,
) -> list[dict[str, Any]]:
    """Get chat history for an investigation."""
    state = _get_state(request)
    return state.message_repo.get_history(investigation_id)


# -- File upload endpoint -----------------------------------------------------

@router.post("/investigations/{investigation_id}/upload")
async def upload_file(
    investigation_id: str,
    request: Request,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Upload a file to an investigation.

    Validates file extension and size. Saves to upload directory.
    Does NOT auto-ingest — the agent decides when to ingest via the tool.
    """
    state = _get_state(request)

    # Validate investigation exists
    investigation = state.investigation_repo.get(investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found")

    # Validate file extension
    if file.filename is None:
        raise HTTPException(status_code=400, detail="Filename is required")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: '{suffix}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    # Read file content and check size
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds maximum size of {MAX_FILE_SIZE // (1024 * 1024)} MB",
        )

    # Save file — sanitize filename to prevent path traversal
    safe_name = Path(file.filename).name  # strips directory components
    upload_dir = Path(state.settings.UPLOAD_DIR) / investigation_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / safe_name
    file_path.write_bytes(content)

    return {
        "status": "uploaded",
        "filename": safe_name,
        "size_bytes": len(content),
        "file_path": f"{investigation_id}/{safe_name}",
        "investigation_id": investigation_id,
    }

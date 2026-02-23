"""WebSocket endpoint for chat streaming.

Handles the real-time communication between the frontend chat panel
and the Redthread agent. Streams agent responses token-by-token.

Protocol (JSON frames):
    Client → Server: {"type": "message", "content": "user text"}
    Client → Server: {"type": "sub_investigate", "question": "specific question"}

    Server → Client: {"type": "text_delta", "content": "partial text"}
    Server → Client: {"type": "tool_call", "tool": "name", "input": {...}}
    Server → Client: {"type": "tool_result", "tool": "name", "output": "..."}
    Server → Client: {"type": "message_complete", "content": "full message"}
    Server → Client: {"type": "graph_update", "data": {...}}
    Server → Client: {"type": "evidence_update", "data": {...}}
    Server → Client: {"type": "error", "message": "..."}
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()

# Tools that modify the graph — trigger graph_update frame after
GRAPH_TOOLS = {"resolve_entity", "add_relationship"}
# Tools that modify evidence — trigger evidence_update frame after
EVIDENCE_TOOLS = {"record_evidence"}


async def _send_json(ws: WebSocket, data: dict[str, Any]) -> None:
    """Send a JSON frame, silently ignoring broken connections."""
    try:
        await ws.send_json(data)
    except Exception:
        pass


@router.websocket("/ws/chat/{investigation_id}")
async def chat_websocket(
    websocket: WebSocket,
    investigation_id: str,
) -> None:
    """WebSocket endpoint for real-time chat with the agent.

    Validates the investigation exists, then enters a message loop:
    - On "message": streams agent response
    - On "sub_investigate": runs focused sub-investigation
    """
    state = websocket.app.state

    # Validate investigation exists
    investigation = state.investigation_repo.get(investigation_id)
    if investigation is None:
        await websocket.close(code=4004, reason="Investigation not found")
        return

    # Check if agent is available
    if state.agent is None:
        await websocket.accept()
        await _send_json(websocket, {
            "type": "error",
            "message": "Agent is not configured. Check ANTHROPIC_API_KEY.",
        })
        await websocket.close()
        return

    await websocket.accept()

    try:
        while True:
            # Receive client frame
            raw = await websocket.receive_text()
            try:
                frame = json.loads(raw)
            except json.JSONDecodeError:
                await _send_json(websocket, {
                    "type": "error",
                    "message": "Invalid JSON frame",
                })
                continue

            frame_type = frame.get("type")

            if frame_type == "message":
                content = frame.get("content", "").strip()
                if not content:
                    await _send_json(websocket, {
                        "type": "error",
                        "message": "Message content cannot be empty",
                    })
                    continue

                # Stream agent response
                tools_called = set()
                async for event in state.agent.chat(investigation_id, content):
                    if event.event_type == "text_delta":
                        await _send_json(websocket, {
                            "type": "text_delta",
                            "content": event.content,
                        })
                    elif event.event_type == "tool_call":
                        tools_called.add(event.tool_name)
                        await _send_json(websocket, {
                            "type": "tool_call",
                            "tool": event.tool_name,
                            "input": event.tool_input,
                        })
                    elif event.event_type == "tool_result":
                        await _send_json(websocket, {
                            "type": "tool_result",
                            "tool": event.tool_name,
                            "output": event.tool_output,
                        })
                    elif event.event_type == "message_complete":
                        await _send_json(websocket, {
                            "type": "message_complete",
                            "content": event.content,
                        })
                    elif event.event_type == "error":
                        await _send_json(websocket, {
                            "type": "error",
                            "message": event.content,
                        })

                # Send update frames if tools modified graph or evidence
                if tools_called & GRAPH_TOOLS:
                    entities = state.graph_db.get_all_entities(investigation_id)
                    relationships = state.graph_db.get_all_relationships(investigation_id)
                    nodes = [
                        {"data": {"id": e["id"], "label": e.get("name", ""), "type": e.get("entity_type", "")}}
                        for e in entities
                    ]
                    edges = [
                        {"data": {"source": r["source_id"], "target": r["target_id"], "type": r.get("rel_type", "")}}
                        for r in relationships
                    ]
                    await _send_json(websocket, {
                        "type": "graph_update",
                        "data": {"nodes": nodes, "edges": edges},
                    })

                if tools_called & EVIDENCE_TOOLS:
                    evidence = state.evidence_repo.query(investigation_id=investigation_id)
                    await _send_json(websocket, {
                        "type": "evidence_update",
                        "data": {"evidence": evidence, "total": len(evidence)},
                    })

            elif frame_type == "sub_investigate":
                question = frame.get("question", "").strip()
                if not question:
                    await _send_json(websocket, {
                        "type": "error",
                        "message": "Sub-investigation question cannot be empty",
                    })
                    continue

                # Run sub-investigation and stream the result
                result = await state.agent.create_sub_investigation(
                    investigation_id, question,
                )
                await _send_json(websocket, {
                    "type": "message_complete",
                    "content": result,
                })

            else:
                await _send_json(websocket, {
                    "type": "error",
                    "message": f"Unknown frame type: {frame_type}",
                })

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for investigation {investigation_id}")
    except Exception as exc:
        logger.error(f"WebSocket error: {exc}")
        try:
            await _send_json(websocket, {
                "type": "error",
                "message": "Internal server error",
            })
        except Exception:
            pass

"""Timeline event recording agent tool.

Plain async function (NOT decorated with @tool yet).
The SDK adapter will wrap it with the decorator in section 8.
Takes repos as parameters for dependency injection.
"""

from __future__ import annotations

import json
from datetime import date, datetime

from redthread.db.repositories import TimelineEventRepo


def _validate_iso8601_date(date_str: str) -> bool:
    """Validate that a string is a valid ISO 8601 date or datetime.

    Accepts:
    - YYYY-MM-DD (date only)
    - YYYY-MM-DDTHH:MM:SS (datetime without timezone)
    - YYYY-MM-DDTHH:MM:SSZ (datetime with UTC)
    - YYYY-MM-DDTHH:MM:SS+HH:MM (datetime with timezone offset)

    Returns True if valid, False otherwise.
    """
    # Try date-only first (YYYY-MM-DD)
    try:
        date.fromisoformat(date_str)
        return True
    except (ValueError, TypeError):
        pass

    # Try full datetime
    try:
        datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return True
    except (ValueError, TypeError):
        pass

    return False


async def record_timeline_event(
    timeline_repo: TimelineEventRepo,
    investigation_id: str,
    entity_id: str,
    entity_name: str,
    event_date: str,
    amount: float = 0.0,
    description: str = "",
    source_record_id: str = "",
    source_dataset_id: str = "",
) -> str:
    """Record a transaction or event for the timeline visualization.

    Call this when you identify dated transactions, transfers, or significant
    events during investigation.

    Parameters
    ----------
    timeline_repo : TimelineEventRepo
        Injected timeline event repository instance.
    investigation_id : str
        Investigation this event belongs to.
    entity_id : str
        The entity associated with this event.
    entity_name : str
        Human-readable entity name for display.
    event_date : str
        Date of the event in ISO 8601 format (YYYY-MM-DD or full datetime).
    amount : float
        Transaction amount (default 0.0).
    description : str
        Human-readable description of the event.
    source_record_id : str
        Optional source record ID.
    source_dataset_id : str
        Optional source dataset ID.

    Returns
    -------
    str
        JSON string with confirmation and event ID, or an error message.
    """
    # Validate event_date is valid ISO 8601
    if not _validate_iso8601_date(event_date):
        return json.dumps({
            "error": (
                f"Invalid event_date '{event_date}'. "
                "Must be a valid ISO 8601 date (e.g., 2024-01-15 or 2024-01-15T14:30:00Z)."
            ),
        })

    event = timeline_repo.create(
        investigation_id=investigation_id,
        entity_id=entity_id if entity_id else None,
        entity_name=entity_name if entity_name else None,
        event_date=event_date,
        amount=amount if amount is not None else None,
        description=description if description else None,
        source_record_id=source_record_id if source_record_id else None,
        source_dataset_id=source_dataset_id if source_dataset_id else None,
    )

    return json.dumps({
        "status": "recorded",
        "id": event["id"],
        "investigation_id": event["investigation_id"],
        "entity_id": event.get("entity_id"),
        "entity_name": event.get("entity_name"),
        "event_date": event["event_date"],
        "amount": event.get("amount"),
        "description": event.get("description"),
        "created_at": event["created_at"],
    })

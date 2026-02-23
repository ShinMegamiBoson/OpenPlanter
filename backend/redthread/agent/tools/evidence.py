"""Evidence chain recording and querying agent tools.

Plain async functions (NOT decorated with @tool yet).
The SDK adapter will wrap them with the decorator in section 8.
Tools take repos as parameters for dependency injection.
"""

from __future__ import annotations

import json

from redthread.db.repositories import EvidenceRepo

VALID_CONFIDENCE_LEVELS = ("confirmed", "probable", "possible", "unresolved")


async def record_evidence(
    evidence_repo: EvidenceRepo,
    investigation_id: str,
    claim: str,
    supporting_evidence: str,
    source_record_id: str,
    source_dataset_id: str,
    confidence: str,
    entity_id: str = "",
) -> str:
    """Record a finding as a structured evidence chain entry.

    Every claim must trace to a specific record in a specific dataset.
    Confidence must be one of: confirmed, probable, possible, unresolved.

    Parameters
    ----------
    evidence_repo : EvidenceRepo
        Injected evidence repository instance.
    investigation_id : str
        Investigation this evidence belongs to.
    claim : str
        The factual claim being recorded (must be non-empty).
    supporting_evidence : str
        Description of evidence supporting the claim (must be non-empty).
    source_record_id : str
        ID of the source record (may be empty for web-sourced evidence).
    source_dataset_id : str
        ID of the source dataset (may be empty for web-sourced evidence).
    confidence : str
        Confidence level: confirmed, probable, possible, or unresolved.
    entity_id : str
        Optional entity this evidence relates to.

    Returns
    -------
    str
        JSON string with the created entry details, or an error message.
    """
    # Validate confidence level
    if confidence not in VALID_CONFIDENCE_LEVELS:
        return json.dumps({
            "error": (
                f"Invalid confidence '{confidence}'. "
                f"Must be one of: {', '.join(VALID_CONFIDENCE_LEVELS)}"
            ),
        })

    # Validate claim is non-empty
    if not claim or not claim.strip():
        return json.dumps({
            "error": "claim must be non-empty",
        })

    # Validate supporting_evidence is non-empty
    if not supporting_evidence or not supporting_evidence.strip():
        return json.dumps({
            "error": "supporting_evidence must be non-empty",
        })

    entry = evidence_repo.create(
        investigation_id=investigation_id,
        claim=claim.strip(),
        supporting_evidence=supporting_evidence.strip(),
        confidence=confidence,
        entity_id=entity_id if entity_id else None,
        source_record_id=source_record_id if source_record_id else None,
        source_dataset_id=source_dataset_id if source_dataset_id else None,
    )

    return json.dumps({
        "status": "recorded",
        "id": entry["id"],
        "investigation_id": entry["investigation_id"],
        "claim": entry["claim"],
        "confidence": entry["confidence"],
        "entity_id": entry.get("entity_id"),
        "created_at": entry["created_at"],
    })


async def query_evidence(
    evidence_repo: EvidenceRepo,
    investigation_id: str,
    entity_id: str = "",
    confidence: str = "",
) -> str:
    """Query accumulated evidence chains with optional filters.

    Parameters
    ----------
    evidence_repo : EvidenceRepo
        Injected evidence repository instance.
    investigation_id : str
        Investigation to query evidence for.
    entity_id : str
        Optional filter — return only evidence for this entity.
    confidence : str
        Optional filter — return only evidence at this confidence level.

    Returns
    -------
    str
        JSON string with matching evidence chain entries and source citations.
    """
    entries = evidence_repo.query(
        investigation_id=investigation_id,
        entity_id=entity_id if entity_id else None,
        confidence=confidence if confidence else None,
    )

    evidence_list = []
    for entry in entries:
        evidence_list.append({
            "id": entry["id"],
            "claim": entry["claim"],
            "supporting_evidence": entry["supporting_evidence"],
            "confidence": entry["confidence"],
            "entity_id": entry.get("entity_id"),
            "source_record_id": entry.get("source_record_id"),
            "source_dataset_id": entry.get("source_dataset_id"),
            "created_at": entry["created_at"],
        })

    return json.dumps({
        "investigation_id": investigation_id,
        "evidence": evidence_list,
        "total": len(evidence_list),
    })

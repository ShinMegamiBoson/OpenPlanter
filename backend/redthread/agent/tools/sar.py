"""SAR (Suspicious Activity Report) narrative generation agent tool.

Plain async function (NOT decorated with @tool yet).
The SDK adapter will wrap it with the decorator in section 8.

The tool assembles evidence chains into a structured SAR narrative template.
It does NOT use an LLM — it produces a structured document from evidence data
that the agent can then refine or the analyst can edit.

Template structure:
1. DRAFT NOTICE (header)
2. Subject information (entities under investigation)
3. Summary of suspicious activity (from confirmed + probable evidence)
4. Detailed narrative (chronological, citing evidence chain IDs)
5. Supporting evidence appendix (all evidence chains with source citations)
6. DRAFT NOTICE (footer)
"""

from __future__ import annotations

from typing import Any

from redthread.db.graph import GraphDB
from redthread.db.repositories import EvidenceRepo

_DRAFT_HEADER = (
    "=" * 72 + "\n"
    "*** DRAFT — FOR ANALYST REVIEW ONLY — NOT FOR REGULATORY SUBMISSION ***\n"
    "=" * 72
)

_DRAFT_FOOTER = (
    "=" * 72 + "\n"
    "*** DRAFT — REQUIRES ANALYST REVIEW AND EDITING BEFORE SUBMISSION ***\n"
    "=" * 72
)

_CONFIDENCE_RANK = {
    "confirmed": 0,
    "probable": 1,
    "possible": 2,
    "unresolved": 3,
}


def _format_entity_info(entity: dict[str, Any]) -> str:
    """Format a single entity's information for the subject section."""
    name = entity.get("name", "Unknown")
    entity_type = entity.get("entity_type", "unknown")
    entity_id = entity.get("id", "N/A")
    return f"  - {name} (Type: {entity_type}, ID: {entity_id})"


def _format_evidence_entry(entry: dict[str, Any], index: int) -> str:
    """Format a single evidence chain entry for the appendix."""
    parts = [
        f"  [{index}] Evidence ID: {entry['id']}",
        f"      Claim: {entry['claim']}",
        f"      Supporting Evidence: {entry['supporting_evidence']}",
        f"      Confidence: {entry['confidence']}",
    ]
    if entry.get("entity_id"):
        parts.append(f"      Entity: {entry['entity_id']}")
    if entry.get("source_record_id"):
        parts.append(f"      Source Record: {entry['source_record_id']}")
    if entry.get("source_dataset_id"):
        parts.append(f"      Source Dataset: {entry['source_dataset_id']}")
    parts.append(f"      Recorded: {entry['created_at']}")
    return "\n".join(parts)


async def generate_sar_narrative(
    evidence_repo: EvidenceRepo,
    graph_db: GraphDB,
    investigation_id: str,
    subject_entity_ids: str = "",
) -> str:
    """Generate a draft SAR narrative from accumulated evidence.

    The narrative is assembled from evidence chains and formatted following
    standard SAR narrative structure.

    IMPORTANT: The output is clearly labeled as a DRAFT requiring analyst
    review and editing before any regulatory submission.

    Parameters
    ----------
    evidence_repo : EvidenceRepo
        Injected evidence repository instance.
    graph_db : GraphDB
        Injected graph database for entity lookups.
    investigation_id : str
        Investigation to generate the narrative for.
    subject_entity_ids : str
        Comma-separated entity IDs for investigation subjects.
        If empty, narrative covers all evidence in the investigation.

    Returns
    -------
    str
        Formatted SAR narrative draft, or a message if no evidence exists.
    """
    # Fetch all evidence for the investigation (sorted chronologically by repo)
    all_evidence = evidence_repo.query(investigation_id=investigation_id)

    if not all_evidence:
        return (
            "No evidence entries found for this investigation. "
            "Record evidence using the record_evidence tool before "
            "generating a SAR narrative."
        )

    # Parse subject entity IDs
    subject_ids = [
        eid.strip()
        for eid in subject_entity_ids.split(",")
        if eid.strip()
    ]

    # Resolve subject entity information from graph
    subjects: list[dict[str, Any]] = []
    for entity_id in subject_ids:
        entity = graph_db.get_entity(entity_id)
        if entity:
            subjects.append(entity)

    # Categorize evidence by confidence
    confirmed_evidence = [e for e in all_evidence if e["confidence"] == "confirmed"]
    probable_evidence = [e for e in all_evidence if e["confidence"] == "probable"]
    possible_evidence = [e for e in all_evidence if e["confidence"] == "possible"]
    unresolved_evidence = [e for e in all_evidence if e["confidence"] == "unresolved"]

    # Build the narrative sections
    sections: list[str] = []

    # 1. DRAFT HEADER
    sections.append(_DRAFT_HEADER)
    sections.append("")

    # 2. Subject Information
    sections.append("SECTION 1: SUBJECT INFORMATION")
    sections.append("-" * 40)
    if subjects:
        for subj in subjects:
            sections.append(_format_entity_info(subj))
    else:
        sections.append("  No specific subjects identified. Narrative covers all evidence.")
    sections.append("")

    # 3. Summary of Suspicious Activity
    sections.append("SECTION 2: SUSPICIOUS ACTIVITY SUMMARY")
    sections.append("-" * 40)
    summary_evidence = confirmed_evidence + probable_evidence
    if summary_evidence:
        sections.append(
            f"  This investigation identified {len(summary_evidence)} "
            f"finding(s) at confirmed or probable confidence level:"
        )
        sections.append("")
        for entry in summary_evidence:
            confidence_label = entry["confidence"].upper()
            sections.append(
                f"  - [{confidence_label}] {entry['claim']} "
                f"(Evidence ID: {entry['id']})"
            )
    else:
        sections.append(
            "  No confirmed or probable findings recorded. "
            "All evidence is at possible or unresolved confidence levels."
        )
    sections.append("")

    # 4. Detailed Narrative (chronological, all evidence)
    sections.append("SECTION 3: DETAILED NARRATIVE")
    sections.append("-" * 40)
    sections.append(
        "  The following is a chronological account of findings, "
        "ordered by the date each finding was recorded."
    )
    sections.append("")
    for i, entry in enumerate(all_evidence, start=1):
        confidence_label = entry["confidence"].upper()
        entity_ref = f" (Entity: {entry['entity_id']})" if entry.get("entity_id") else ""
        sections.append(
            f"  {i}. [{confidence_label}]{entity_ref} {entry['claim']}"
        )
        sections.append(
            f"     Evidence: {entry['supporting_evidence']}"
        )
        sections.append(
            f"     (Ref: {entry['id']})"
        )
        sections.append("")

    # 5. Supporting Evidence Appendix
    sections.append("SECTION 4: EVIDENCE APPENDIX")
    sections.append("-" * 40)
    sections.append(
        f"  Total evidence entries: {len(all_evidence)}"
    )
    sections.append(
        f"  Confirmed: {len(confirmed_evidence)} | "
        f"Probable: {len(probable_evidence)} | "
        f"Possible: {len(possible_evidence)} | "
        f"Unresolved: {len(unresolved_evidence)}"
    )
    sections.append("")
    for i, entry in enumerate(all_evidence, start=1):
        sections.append(_format_evidence_entry(entry, i))
        sections.append("")

    # 6. DRAFT FOOTER
    sections.append(_DRAFT_FOOTER)

    return "\n".join(sections)

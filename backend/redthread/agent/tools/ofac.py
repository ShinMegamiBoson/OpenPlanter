"""OFAC/SDN screening agent tool.

Plain async function with dependency injection, consistent with all
other tools in redthread.agent.tools.  The SDK adapter will wrap
this with the @tool decorator in section 8.

Results are advisory — all hits require analyst review before any
compliance or enforcement decision.
"""

from __future__ import annotations

from redthread.db.sqlite import SQLiteDB
from redthread.ofac.screener import screen_entity


async def screen_ofac(
    entity_name: str,
    investigation_id: str,
    db: SQLiteDB,
    top_n: int = 10,
) -> str:
    """Screen an entity name against the OFAC/SDN sanctions list.

    Returns matches with confidence levels.  Results are for analyst
    review, not automated decisioning.

    Parameters
    ----------
    entity_name : str
        The name to screen against the SDN list.
    investigation_id : str
        Current investigation context (for audit trail).
    db : SQLiteDB
        Database containing the sdn_entries table.
    top_n : int
        Maximum number of hits to return.

    Returns
    -------
    str
        Formatted screening results as a readable string.
    """
    if not entity_name or not entity_name.strip():
        return "Error: entity_name is required and cannot be empty."

    hits = screen_entity(entity_name, db, top_n=top_n)

    if not hits:
        return (
            f"OFAC/SDN Screening Result for '{entity_name}':\n"
            f"No matches found against the SDN list.\n\n"
            f"Note: This screening result requires analyst review. "
            f"A clear result does not guarantee the entity is not sanctioned."
        )

    lines = [
        f"OFAC/SDN Screening Result for '{entity_name}':",
        f"Found {len(hits)} potential match(es):\n",
    ]

    for i, hit in enumerate(hits, 1):
        alias_info = f" (matched alias: {hit.matched_alias})" if hit.matched_alias else ""
        lines.append(
            f"  {i}. {hit.sdn_name}{alias_info}\n"
            f"     UID: {hit.sdn_uid} | Type: {hit.sdn_entry_type} | "
            f"Program: {hit.program}\n"
            f"     Score: {hit.match_score:.4f} | Confidence: {hit.confidence}"
        )

    lines.append("")
    lines.append(
        "IMPORTANT: These results are for analyst review only and must not "
        "be used for automated decisioning. Analyst review required."
    )

    return "\n".join(lines)

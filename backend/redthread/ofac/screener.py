"""OFAC/SDN fuzzy screening engine.

Checks entity names against the local SDN list using the pairwise
entity comparison pipeline.  Results are advisory — all matches
require analyst review before any compliance decision.

Screening approach:
1. Normalize the input name (lowercase, strip suffixes, normalize whitespace).
2. Load all SDN entries into an in-memory cache on first call (~30K entries).
3. For each SDN entry, compare primary name + all aliases using compare_entities().
4. Return top N matches above the "possible" threshold (score >= 0.60),
   sorted by score descending.
5. Map scores to confidence tiers via score_to_confidence().
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from redthread.db.sqlite import SQLiteDB
from redthread.entity.pairwise import compare_entities, score_to_confidence, THRESHOLD_POSSIBLE

logger = logging.getLogger(__name__)

# Module-level cache: populated on first screening call, reused after that.
_sdn_cache: list[dict] | None = None


@dataclass
class ScreeningHit:
    """A single screening match against the SDN list."""

    sdn_uid: int
    sdn_name: str
    match_score: float
    confidence: str  # confirmed | probable | possible
    matched_alias: str | None  # which alias matched, if not primary name
    sdn_entry_type: str
    program: str


def _load_sdn_cache(db: SQLiteDB) -> list[dict]:
    """Load all SDN entries from SQLite into memory for fast screening."""
    rows = db.fetchall("SELECT * FROM sdn_entries")
    cache = []
    for row in rows:
        aliases_raw = row.get("aliases", "[]")
        try:
            aliases = json.loads(aliases_raw) if isinstance(aliases_raw, str) else aliases_raw
        except (json.JSONDecodeError, TypeError):
            aliases = []
        cache.append({
            "uid": row["uid"],
            "name": row["name"],
            "entry_type": row.get("entry_type", "Unknown"),
            "program": row.get("program", ""),
            "aliases": aliases if isinstance(aliases, list) else [],
        })
    return cache


def _invalidate_cache() -> None:
    """Clear the in-memory SDN cache (useful after reloading the list)."""
    global _sdn_cache  # noqa: PLW0603
    _sdn_cache = None


def _get_entity_type_hint(sdn_entry_type: str) -> str:
    """Map SDN entry_type to the pairwise comparison entity_type hint."""
    if sdn_entry_type == "Individual":
        return "person"
    if sdn_entry_type == "Entity":
        return "organization"
    return "unknown"


def screen_entity(
    name: str,
    db: SQLiteDB,
    top_n: int = 10,
) -> list[ScreeningHit]:
    """Screen a name against all SDN entries and return top matches.

    Parameters
    ----------
    name : str
        The entity name to screen.
    db : SQLiteDB
        Database containing the sdn_entries table.
    top_n : int
        Maximum number of hits to return (default 10).

    Returns
    -------
    list[ScreeningHit]
        Matches with score >= 0.60 ("possible" threshold), sorted by
        score descending.  Empty list if no matches above threshold.
    """
    global _sdn_cache  # noqa: PLW0603

    if not name or not name.strip():
        return []

    # Load cache on first call
    if _sdn_cache is None:
        _sdn_cache = _load_sdn_cache(db)
        logger.info("Loaded %d SDN entries into screening cache", len(_sdn_cache))

    hits: list[ScreeningHit] = []

    for sdn in _sdn_cache:
        entity_type_hint = _get_entity_type_hint(sdn["entry_type"])

        # Compare against primary name
        best_score = 0.0
        best_alias: str | None = None

        result = compare_entities(name, sdn["name"], entity_type=entity_type_hint)
        if result.score > best_score:
            best_score = result.score
            best_alias = None  # primary name match

        # Compare against each alias
        for alias in sdn["aliases"]:
            if not alias:
                continue
            alias_result = compare_entities(name, alias, entity_type=entity_type_hint)
            if alias_result.score > best_score:
                best_score = alias_result.score
                best_alias = alias

        # Only keep matches at or above "possible" threshold
        if best_score >= THRESHOLD_POSSIBLE:
            confidence = score_to_confidence(best_score)
            hits.append(ScreeningHit(
                sdn_uid=sdn["uid"],
                sdn_name=sdn["name"],
                match_score=round(best_score, 4),
                confidence=confidence,
                matched_alias=best_alias,
                sdn_entry_type=sdn["entry_type"],
                program=sdn["program"],
            ))

    # Sort by score descending, take top N
    hits.sort(key=lambda h: h.match_score, reverse=True)
    return hits[:top_n]

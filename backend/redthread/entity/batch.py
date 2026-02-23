"""Tier 2 batch entity resolution.

Batch entity resolution across entire datasets. Uses the pairwise
compare_entities() function from Tier 1 over all record pairs.

The tech plan originally specified splink with DuckDB backend for
probabilistic record linkage, but splink's Bayesian model requires
training data (or pre-set m/u values) to produce meaningful match
probabilities. Without training data, the untrained parameters produce
zero matches even for obvious duplicates. Since we're operating in
unsupervised mode with no labeled training data, we fall back to the
simpler but reliable approach of iterating compare_entities() over
all candidate pairs with blocking rules for efficiency.

This module is for bulk dataset processing (e.g., "find all related
entities across these files"), not real-time comparison. The pairwise
module (Tier 1) handles individual comparisons during conversation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

from redthread.entity.pairwise import compare_entities, score_to_confidence

logger = logging.getLogger(__name__)


@dataclass
class BatchMatchResult:
    """Result of batch entity resolution across a dataset.

    Attributes
    ----------
    pairs : list[dict]
        Each dict: {entity_a, entity_b, score, confidence, matching_fields}
    total_comparisons : int
        Number of pairwise comparisons performed.
    matches_found : int
        Number of pairs above the threshold.
    """

    pairs: list[dict[str, Any]] = field(default_factory=list)
    total_comparisons: int = 0
    matches_found: int = 0


def _get_blocking_key(record: dict[str, Any], match_fields: list[str]) -> str:
    """Generate a blocking key from the first character of primary match fields.

    Records with different blocking keys are not compared, reducing the
    O(n^2) comparison space significantly for large datasets. The blocking
    key is case-insensitive.
    """
    parts = []
    for field_name in match_fields:
        value = str(record.get(field_name, "")).strip().lower()
        if value:
            parts.append(value[0])
        else:
            parts.append("")
    return "|".join(parts)


def batch_resolve(
    records: list[dict[str, Any]],
    match_fields: list[str],
    threshold: float = 0.8,
    use_blocking: bool = True,
) -> BatchMatchResult:
    """Resolve entities in batch across a list of records.

    Compares all pairs of records (with optional blocking to reduce the
    comparison space) using the Tier 1 pairwise compare_entities() function.

    Parameters
    ----------
    records : list[dict]
        List of record dicts. Each must have a 'unique_id' field and
        the fields listed in match_fields. Should also have 'entity_type'
        (defaults to 'unknown').
    match_fields : list[str]
        Field names to compare (e.g., ['name']). Currently the primary
        match field (first in list) is used for entity comparison.
    threshold : float
        Minimum composite score to include a pair in results (0.0-1.0).
    use_blocking : bool
        If True, only compare records that share the same blocking key
        (first character of primary match field). Greatly reduces
        comparisons for large datasets but may miss some matches.
        For datasets under 1000 records, blocking is skipped regardless.

    Returns
    -------
    BatchMatchResult
        Contains matched pairs sorted by score descending.
    """
    if not records or len(records) < 2:
        return BatchMatchResult(pairs=[], total_comparisons=0, matches_found=0)

    if not match_fields:
        return BatchMatchResult(pairs=[], total_comparisons=0, matches_found=0)

    primary_field = match_fields[0]

    # Build index with unique_id -> record mapping
    indexed_records: list[tuple[str, dict[str, Any]]] = []
    for record in records:
        uid = str(record.get("unique_id", ""))
        if uid:
            indexed_records.append((uid, record))

    if len(indexed_records) < 2:
        return BatchMatchResult(pairs=[], total_comparisons=0, matches_found=0)

    # Determine whether to use blocking
    # For small datasets (< 1000 records), skip blocking for completeness
    should_block = use_blocking and len(indexed_records) >= 1000

    if should_block:
        # Group records by blocking key
        blocks: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        for uid, record in indexed_records:
            key = _get_blocking_key(record, match_fields)
            if key not in blocks:
                blocks[key] = []
            blocks[key].append((uid, record))

        # Generate pairs within each block
        candidate_pairs: list[tuple[tuple[str, dict[str, Any]], tuple[str, dict[str, Any]]]] = []
        for block_records in blocks.values():
            if len(block_records) > 1:
                candidate_pairs.extend(combinations(block_records, 2))

        logger.info(
            "Batch resolve: %d records in %d blocks, %d candidate pairs",
            len(indexed_records), len(blocks), len(candidate_pairs),
        )
    else:
        # Compare all pairs (no blocking)
        candidate_pairs = list(combinations(indexed_records, 2))

    # Perform pairwise comparisons
    matched_pairs: list[dict[str, Any]] = []
    total_comparisons = 0

    for (uid_a, rec_a), (uid_b, rec_b) in candidate_pairs:
        name_a = str(rec_a.get(primary_field, "")).strip()
        name_b = str(rec_b.get(primary_field, "")).strip()

        # Skip if either name is empty
        if not name_a or not name_b:
            total_comparisons += 1
            continue

        entity_type = rec_a.get("entity_type", rec_b.get("entity_type", "unknown"))

        result = compare_entities(name_a, name_b, entity_type=str(entity_type))
        total_comparisons += 1

        if result.score >= threshold:
            matched_pairs.append({
                "entity_a": uid_a,
                "entity_b": uid_b,
                "name_a": name_a,
                "name_b": name_b,
                "score": round(result.score, 4),
                "confidence": score_to_confidence(result.score),
                "match_type": result.match_type,
                "matching_fields": match_fields,
            })

    # Sort by score descending
    matched_pairs.sort(key=lambda p: p["score"], reverse=True)

    return BatchMatchResult(
        pairs=matched_pairs,
        total_comparisons=total_comparisons,
        matches_found=len(matched_pairs),
    )

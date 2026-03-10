#!/usr/bin/env python3
"""Score investigation findings by confidence tier.

Reads findings files in findings/ and evidence chains in evidence/,
re-scores based on evidence chain strength, source diversity, and
corroboration status. Updates confidence fields in-place.

Scoring rules:
  - 2+ independent sources with different collection paths → confirmed
  - Strong single source (official record) or high match score → probable
  - Circumstantial evidence only or moderate match → possible
  - Insufficient data or contradictory evidence → unresolved

Uses Python stdlib only — zero external dependencies.

Usage:
    python3 confidence_scorer.py /path/to/investigation
    python3 confidence_scorer.py /path/to/investigation --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONFIDENCE_TIERS = ["confirmed", "probable", "possible", "unresolved"]


def score_entity(entity: dict[str, Any]) -> tuple[str, str]:
    """Score an entity from canonical.json based on source diversity and variant count.

    Returns (new_confidence, reason).
    """
    sources = entity.get("sources", [])
    variants = entity.get("variants", [])

    unique_sources = len(set(sources))
    variant_count = len(variants)

    # Check for hard signals: same identifier value across 2+ sources
    has_hard_signal = False
    has_hard_disqualifier = False
    similarities = []
    hard_signal_values: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for v in variants:
        sim = v.get("similarity", 0)
        if isinstance(sim, (int, float)):
            similarities.append(sim)
        fields = v.get("fields", {})
        source = v.get("source", "")
        for field_name in ("ein", "tin", "phone", "email"):
            val = str(fields.get(field_name, "")).strip()
            if val:
                hard_signal_values[field_name].append((val, source))

    for field_name, entries in hard_signal_values.items():
        vals = [v for v, _ in entries]
        srcs = [s for _, s in entries]
        if len(set(vals)) == 1 and len(set(srcs)) >= 2:
            has_hard_signal = True
        elif len(set(vals)) > 1:
            has_hard_disqualifier = True

    avg_similarity = sum(similarities) / len(similarities) if similarities else 0
    max_similarity = max(similarities) if similarities else 0

    # Hard disqualifier overrides everything
    if has_hard_disqualifier:
        return "unresolved", (
            f"conflicting hard identifiers across variants"
        )

    # Scoring logic
    if unique_sources >= 2 and (has_hard_signal or avg_similarity >= 0.90):
        return "confirmed", (
            f"{unique_sources} independent sources"
            + (", hard signal match" if has_hard_signal else "")
            + f", avg similarity {avg_similarity:.2f}"
        )
    elif unique_sources >= 2 and avg_similarity >= 0.85:
        return "confirmed", (
            f"{unique_sources} sources, avg similarity {avg_similarity:.2f}"
        )
    elif unique_sources >= 2 or (has_hard_signal and avg_similarity >= 0.70):
        return "probable", (
            f"{unique_sources} sources"
            + (", hard signal" if has_hard_signal else "")
            + f", avg similarity {avg_similarity:.2f}"
        )
    elif variant_count >= 2 and avg_similarity >= 0.70:
        return "possible", (
            f"{variant_count} variants, avg similarity {avg_similarity:.2f}"
        )
    elif variant_count >= 2:
        return "possible", f"{variant_count} variants, low similarity {avg_similarity:.2f}"
    else:
        return "unresolved", f"single record, similarity {max_similarity:.2f}"


def score_cross_reference(xref: dict[str, Any]) -> tuple[str, str]:
    """Score a cross-reference based on dataset count and match quality."""
    dataset_count = xref.get("dataset_count", 0)
    pairs = xref.get("cross_reference_pairs", [])

    if not pairs:
        return "unresolved", "no cross-reference pairs"

    # Analyze pair quality
    exact_matches = 0
    total_fields = 0
    for pair in pairs:
        mf = pair.get("matching_fields", {})
        total_fields += len(mf)
        exact_matches += pair.get("exact_match_count", 0)

    match_rate = exact_matches / total_fields if total_fields > 0 else 0

    if dataset_count >= 3 and match_rate >= 0.5:
        return "confirmed", (
            f"{dataset_count} datasets, {exact_matches}/{total_fields} "
            f"exact field matches ({match_rate:.0%})"
        )
    elif dataset_count >= 2 and match_rate >= 0.3:
        return "probable", (
            f"{dataset_count} datasets, {match_rate:.0%} field match rate"
        )
    elif dataset_count >= 2:
        return "possible", (
            f"{dataset_count} datasets, low field match rate {match_rate:.0%}"
        )
    else:
        return "unresolved", f"only {dataset_count} dataset(s)"


def score_evidence_chain(chain: dict[str, Any]) -> tuple[str, str]:
    """Score an evidence chain based on hop quality and corroboration."""
    hops = chain.get("hops", [])
    corr = chain.get("corroboration", {})

    if not hops:
        return "unresolved", "no evidence hops"

    # Analyze hop quality
    scores = []
    for hop in hops:
        s = hop.get("match_score")
        if s is not None:
            try:
                scores.append(float(s))
            except (ValueError, TypeError):
                pass

    min_score = min(scores) if scores else 0
    avg_score = sum(scores) / len(scores) if scores else 0

    # Check corroboration
    corr_status = corr.get("status", "single")
    independent_sources = corr.get("independent_sources", 1)
    if isinstance(independent_sources, str):
        try:
            independent_sources = int(independent_sources)
        except ValueError:
            independent_sources = 1

    # Link strength = weakest hop
    if corr_status == "corroborated" and independent_sources >= 2 and min_score >= 0.85:
        return "confirmed", (
            f"corroborated by {independent_sources} sources, "
            f"min hop score {min_score:.2f}"
        )
    elif (
        corr_status == "corroborated"
        or (independent_sources >= 2 and min_score >= 0.70)
    ):
        return "probable", (
            f"{'corroborated' if corr_status == 'corroborated' else 'multi-source'}, "
            f"min hop score {min_score:.2f}"
        )
    elif min_score >= 0.55 and len(hops) <= 3:
        return "possible", (
            f"single source chain, {len(hops)} hops, min score {min_score:.2f}"
        )
    elif corr_status == "contradicted":
        return "unresolved", "contradicted by other evidence"
    else:
        return "unresolved", f"weak chain, min score {min_score:.2f}"


def process_file(
    filepath: Path, dry_run: bool
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Process a single JSON findings file. Returns (tier_counts, changes)."""
    tier_counts: dict[str, int] = defaultdict(int)
    changes: list[dict[str, Any]] = []

    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"  Error reading {filepath.name}: {e}")
        return dict(tier_counts), changes

    modified = False

    # Detect file type and score accordingly
    if isinstance(data, dict):
        # Canonical entity map
        entities = data.get("entities", [])
        if entities and "canonical_name" in (entities[0] if entities else {}):
            for entity in entities:
                old = entity.get("confidence", "unresolved")
                new, reason = score_entity(entity)
                tier_counts[new] += 1
                if old != new:
                    changes.append(
                        {
                            "id": entity.get("canonical_id", "?"),
                            "name": entity.get("canonical_name", "?"),
                            "old": old,
                            "new": new,
                            "reason": reason,
                        }
                    )
                    entity["confidence"] = new
                    entity["confidence_basis"] = reason
                    modified = True

        # Cross-references
        xrefs = data.get("cross_references", [])
        for xref in xrefs:
            old = xref.get("confidence", "unresolved")
            new, reason = score_cross_reference(xref)
            tier_counts[new] += 1
            if old != new:
                changes.append(
                    {
                        "id": xref.get("entity_id", "?"),
                        "name": xref.get("entity_name", "?"),
                        "old": old,
                        "new": new,
                        "reason": reason,
                    }
                )
                xref["confidence"] = new
                xref["confidence_basis"] = reason
                modified = True

        # Evidence chains
        chains = data.get("chains", data.get("evidence_chains", []))
        for chain in chains:
            old = chain.get("confidence", "unresolved")
            new, reason = score_evidence_chain(chain)
            tier_counts[new] += 1
            if old != new:
                changes.append(
                    {
                        "id": chain.get("chain_id", "?"),
                        "name": chain.get("claim", "?")[:60],
                        "old": old,
                        "new": new,
                        "reason": reason,
                    }
                )
                chain["confidence"] = new
                chain["confidence_basis"] = reason
                modified = True

    # Write back if modified and not dry-run
    if modified and not dry_run:
        filepath.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    return dict(tier_counts), changes


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-score investigation findings by confidence tier"
    )
    parser.add_argument("workspace", type=Path, help="Path to investigation workspace")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without modifying files",
    )
    args = parser.parse_args()

    workspace = args.workspace.resolve()

    # Find all JSON files in entities/, findings/, evidence/
    search_dirs = [
        workspace / "entities",
        workspace / "findings",
        workspace / "evidence",
    ]
    json_files: list[Path] = []
    for d in search_dirs:
        if d.exists():
            json_files.extend(d.glob("*.json"))

    if not json_files:
        print("No JSON files found in entities/, findings/, or evidence/")
        sys.exit(0)

    total_tiers: dict[str, int] = defaultdict(int)
    all_changes: list[dict[str, Any]] = []

    mode = "DRY RUN" if args.dry_run else "SCORING"
    print(f"Confidence scoring ({mode}):\n")

    for fp in sorted(json_files):
        tiers, changes = process_file(fp, args.dry_run)
        for tier, count in tiers.items():
            total_tiers[tier] += count
        all_changes.extend(changes)

        status = f"{sum(tiers.values())} items"
        if changes:
            status += f", {len(changes)} re-scored"
        print(f"  {fp.relative_to(workspace)}: {status}")

    # Report changes
    if all_changes:
        print(f"\nConfidence changes ({len(all_changes)}):")
        for c in all_changes:
            arrow = f"{c['old']} -> {c['new']}"
            print(f"  [{arrow:30s}] {c['name']}")
            print(f"    Reason: {c['reason']}")
    else:
        print("\nNo confidence changes needed.")

    # Summary
    print(f"\nConfidence breakdown:")
    for tier in CONFIDENCE_TIERS:
        count = total_tiers.get(tier, 0)
        print(f"  {tier}: {count}")

    total = sum(total_tiers.values())
    if total > 0:
        confirmed = total_tiers.get("confirmed", 0)
        print(f"\n  Total items: {total}")
        print(f"  Confirmed rate: {confirmed/total:.0%}")

    # Write scoring log
    if not args.dry_run:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        log = {
            "metadata": {
                "scored_at": now,
                "workspace": str(workspace),
                "files_processed": len(json_files),
            },
            "summary": dict(total_tiers),
            "changes": all_changes,
        }
        log_dir = workspace / "evidence"
        log_dir.mkdir(exist_ok=True)
        log_path = log_dir / "scoring-log.json"
        log_path.write_text(json.dumps(log, indent=2), encoding="utf-8")
        print(f"\n  Scoring log: {log_path}")


if __name__ == "__main__":
    main()

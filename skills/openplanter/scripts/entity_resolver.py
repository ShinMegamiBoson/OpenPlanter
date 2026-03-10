#!/usr/bin/env python3
"""Fuzzy entity matching and canonical map builder.

Reads all CSV/JSON files in a workspace's datasets/ directory, extracts
entity names, normalizes them, performs pairwise fuzzy matching, and
outputs a canonical entity map to entities/canonical.json.

Uses Python stdlib only — zero external dependencies.

Usage:
    python3 entity_resolver.py /path/to/investigation
    python3 entity_resolver.py /path/to/investigation --threshold 0.80
    python3 entity_resolver.py /path/to/investigation --name-columns "name,contributor_name,registrant"
"""
from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# --- Name Normalization ---

# Legal suffix patterns — ordered longest first for greedy matching
SUFFIX_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\blimited\s+liability\s+company\b", re.I), ""),
    (re.compile(r"\blimited\s+liability\s+partnership\b", re.I), ""),
    (re.compile(r"\blimited\s+partnership\b", re.I), ""),
    (re.compile(r"\bpublic\s+limited\s+company\b", re.I), ""),
    (re.compile(r"\bprofessional\s+corporation\b", re.I), ""),
    (re.compile(r"\bprofessional\s+association\b", re.I), ""),
    (re.compile(r"\bincorporated\b", re.I), ""),
    (re.compile(r"\bcorporation\b", re.I), ""),
    (re.compile(r"\bcompany\b", re.I), ""),
    (re.compile(r"\blimited\b", re.I), ""),
    (re.compile(r"\bl\.?l\.?c\.?\b", re.I), ""),
    (re.compile(r"\bl\.?l\.?p\.?\b", re.I), ""),
    (re.compile(r"\bl\.?p\.?\b", re.I), ""),
    (re.compile(r"\bp\.?l\.?c\.?\b", re.I), ""),
    (re.compile(r"\bp\.?c\.?\b", re.I), ""),
    (re.compile(r"\bp\.?a\.?\b", re.I), ""),
    (re.compile(r"\binc\.?\b", re.I), ""),
    (re.compile(r"\bcorp\.?\b", re.I), ""),
    (re.compile(r"\bltd\.?\b", re.I), ""),
    (re.compile(r"\bco\.?\b", re.I), ""),
]

NOISE_WORDS = re.compile(r"\b(?:the|a|an|of)\b", re.I)
PUNCT = re.compile(r"[^\w\s-]")
MULTI_SPACE = re.compile(r"\s+")

# Common name columns to auto-detect
DEFAULT_NAME_COLUMNS = [
    "name",
    "entity_name",
    "company_name",
    "organization_name",
    "org_name",
    "contributor_name",
    "registrant_name",
    "registrant",
    "client_name",
    "client",
    "vendor_name",
    "vendor",
    "employer_name",
    "employer",
    "recipient_name",
    "recipient",
    "lobbyist_name",
    "lobbyist",
    "owner_name",
    "owner",
    "grantee",
    "contractor",
]


def strip_diacritics(s: str) -> str:
    decomposed = unicodedata.normalize("NFKD", s)
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return unicodedata.normalize("NFKC", stripped)


def canonical_key(name: str) -> str:
    """Produce a normalized key for entity deduplication."""
    s = strip_diacritics(name)
    s = s.lower()
    # Normalize ampersand BEFORE noise word removal
    s = s.replace("&", " and ")
    # Strip legal suffixes
    for pat, repl in SUFFIX_PATTERNS:
        s = pat.sub(repl, s)
    # Remove noise words (not "and" — it's a real token in entity names)
    s = NOISE_WORDS.sub("", s)
    # Strip punctuation except hyphens
    s = PUNCT.sub(" ", s)
    # Collapse whitespace
    s = MULTI_SPACE.sub(" ", s).strip()
    return s


def entity_similarity(a: str, b: str, cutoff: float = 0.5) -> float:
    """Cascading similarity check using difflib.SequenceMatcher.

    Stages: real_quick_ratio (O(1)) → quick_ratio (O(min(N,M))) → ratio (O(N*M)).
    Returns 0.0 if below cutoff at any stage.
    """
    ka, kb = canonical_key(a), canonical_key(b)
    if ka == kb:
        return 1.0
    if not ka or not kb:
        return 0.0
    sm = difflib.SequenceMatcher(None, ka, kb, autojunk=False)
    if sm.real_quick_ratio() < cutoff:
        return 0.0
    if sm.quick_ratio() < cutoff:
        return 0.0
    return round(sm.ratio(), 4)


# --- Data Loading ---


@dataclass
class EntityRecord:
    name: str
    normalized: str
    source_file: str
    source_location: str  # "row:42" or "$.path[3].name"
    fields: dict[str, str] = field(default_factory=dict)


@dataclass
class CanonicalEntity:
    canonical_id: str
    canonical_name: str
    variants: list[dict[str, Any]] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    confidence: str = "unresolved"


def detect_name_columns(headers: list[str], explicit: list[str] | None) -> list[str]:
    """Find which columns contain entity names."""
    if explicit:
        return [h for h in headers if h.lower() in [e.lower() for e in explicit]]
    lower_headers = {h.lower(): h for h in headers}
    found = []
    for candidate in DEFAULT_NAME_COLUMNS:
        if candidate in lower_headers:
            found.append(lower_headers[candidate])
    return found


def load_csv(filepath: Path, name_columns: list[str] | None) -> list[EntityRecord]:
    """Load entities from a CSV file."""
    records: list[EntityRecord] = []
    # Try multiple encodings
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            with open(filepath, newline="", encoding=encoding) as f:
                sample = f.read(4096)
                f.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample[:2048], delimiters=",\t|;")
                except csv.Error:
                    dialect = csv.excel
                reader = csv.DictReader(f, dialect=dialect)
                if reader.fieldnames is None:
                    return records
                cols = detect_name_columns(list(reader.fieldnames), name_columns)
                if not cols:
                    print(f"  Warning: No name columns found in {filepath.name}")
                    return records
                for row_num, row in enumerate(reader, start=2):
                    for col in cols:
                        val = (row.get(col) or "").strip()
                        if val and len(val) > 1:
                            records.append(
                                EntityRecord(
                                    name=val,
                                    normalized=canonical_key(val),
                                    source_file=filepath.name,
                                    source_location=f"row:{row_num}",
                                    fields={
                                        k: (v or "").strip()
                                        for k, v in row.items()
                                        if v and v.strip()
                                    },
                                )
                            )
                return records
        except UnicodeDecodeError:
            continue
    print(f"  Error: Cannot decode {filepath.name}")
    return records


def load_json(filepath: Path, name_columns: list[str] | None) -> list[EntityRecord]:
    """Load entities from a JSON file (array of objects or nested)."""
    records: list[EntityRecord] = []
    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"  Error reading {filepath.name}: {e}")
        return records

    if isinstance(data, list):
        items = data
        path_prefix = "$"
    elif isinstance(data, dict):
        # Try common wrapper patterns
        for key in ("data", "results", "records", "items", "registrants", "filings"):
            if key in data and isinstance(data[key], list):
                items = data[key]
                path_prefix = f"$.{key}"
                break
        else:
            items = [data]
            path_prefix = "$"
    else:
        return records

    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        cols = detect_name_columns(list(item.keys()), name_columns)
        if not cols and idx == 0:
            print(f"  Warning: No name columns found in {filepath.name}")
        for col in cols:
            val = str(item.get(col, "")).strip()
            if val and len(val) > 1:
                records.append(
                    EntityRecord(
                        name=val,
                        normalized=canonical_key(val),
                        source_file=filepath.name,
                        source_location=f"{path_prefix}[{idx}].{col}",
                        fields={
                            k: str(v).strip()
                            for k, v in item.items()
                            if v is not None and str(v).strip()
                        },
                    )
                )
    return records


# --- Entity Resolution ---


class UnionFind:
    """Disjoint-set data structure for entity clustering."""

    def __init__(self) -> None:
        self.parent: dict[int, int] = {}
        self.rank: dict[int, int] = {}

    def find(self, x: int) -> int:
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])  # path compression
        return self.parent[x]

    def union(self, x: int, y: int) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        # union by rank
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1

    def clusters(self, indices: list[int]) -> dict[int, list[int]]:
        groups: dict[int, list[int]] = defaultdict(list)
        for i in indices:
            groups[self.find(i)].append(i)
        return dict(groups)


def resolve_entities(
    records: list[EntityRecord], threshold: float
) -> list[CanonicalEntity]:
    """Group records into canonical entities using fuzzy matching."""
    if not records:
        return []

    # --- Blocking: group by first 3 chars of normalized name ---
    blocks: dict[str, list[int]] = defaultdict(list)
    for idx, rec in enumerate(records):
        key = rec.normalized[:3] if len(rec.normalized) >= 3 else rec.normalized
        blocks[key].append(idx)

    # --- Pairwise comparison within blocks ---
    uf = UnionFind()
    comparisons = 0
    matches = 0

    for block_key, indices in blocks.items():
        for i in range(len(indices)):
            for j in range(i + 1, len(indices)):
                a_idx, b_idx = indices[i], indices[j]
                comparisons += 1
                score = entity_similarity(
                    records[a_idx].name, records[b_idx].name, cutoff=threshold
                )
                if score >= threshold:
                    uf.union(a_idx, b_idx)
                    matches += 1

    # Also compare across adjacent blocks (sorted neighborhood window=1)
    sorted_blocks = sorted(blocks.keys())
    for k in range(len(sorted_blocks) - 1):
        key_a, key_b = sorted_blocks[k], sorted_blocks[k + 1]
        # Only compare first few from each block to limit cost
        for a_idx in blocks[key_a][:5]:
            for b_idx in blocks[key_b][:5]:
                comparisons += 1
                score = entity_similarity(
                    records[a_idx].name, records[b_idx].name, cutoff=threshold
                )
                if score >= threshold:
                    uf.union(a_idx, b_idx)
                    matches += 1

    # --- Build canonical entities from clusters ---
    clusters = uf.clusters(list(range(len(records))))
    entities: list[CanonicalEntity] = []

    for cluster_id, (root, members) in enumerate(
        sorted(clusters.items(), key=lambda x: -len(x[1])), start=1
    ):
        # Pick the most common name variant as canonical
        name_counts: dict[str, int] = defaultdict(int)
        for idx in members:
            name_counts[records[idx].name] += 1
        canonical_name = max(name_counts, key=name_counts.get)  # type: ignore[arg-type]

        variants = []
        sources = set()
        for idx in members:
            rec = records[idx]
            sources.add(rec.source_file)
            variants.append(
                {
                    "name": rec.name,
                    "source": rec.source_file,
                    "location": rec.source_location,
                    "similarity": entity_similarity(canonical_name, rec.name),
                }
            )

        # Determine confidence based on source diversity AND match quality
        unique_sources = len(sources)
        sims = [v.get("similarity", 0) for v in variants if isinstance(v.get("similarity"), (int, float))]
        avg_sim = sum(sims) / len(sims) if sims else 0

        if unique_sources >= 2 and avg_sim >= 0.85:
            confidence = "confirmed"
        elif unique_sources >= 2:
            confidence = "probable"
        elif len(members) >= 3:
            confidence = "probable"
        elif len(members) >= 2:
            confidence = "possible"
        else:
            confidence = "unresolved"

        entities.append(
            CanonicalEntity(
                canonical_id=f"entity-{cluster_id:04d}",
                canonical_name=canonical_name,
                variants=variants,
                sources=sorted(sources),
                confidence=confidence,
            )
        )

    print(f"  Comparisons: {comparisons:,}")
    print(f"  Matches found: {matches:,}")
    print(f"  Canonical entities: {len(entities):,}")
    return entities


# --- Main ---


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resolve entities across datasets in an investigation workspace"
    )
    parser.add_argument("workspace", type=Path, help="Path to investigation workspace")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.85,
        help="Similarity threshold for matching (default: 0.85)",
    )
    parser.add_argument(
        "--name-columns",
        type=str,
        default=None,
        help="Comma-separated list of column names containing entity names",
    )
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    datasets_dir = workspace / "datasets"
    if not datasets_dir.exists():
        print(f"Error: {datasets_dir} does not exist", file=sys.stderr)
        sys.exit(1)

    name_cols = args.name_columns.split(",") if args.name_columns else None

    # Load all datasets
    all_records: list[EntityRecord] = []
    data_files = list(datasets_dir.glob("*.csv")) + list(datasets_dir.glob("*.json"))

    if not data_files:
        print(f"No CSV or JSON files found in {datasets_dir}")
        sys.exit(0)

    print(f"Loading datasets from {datasets_dir}:")
    for fp in sorted(data_files):
        print(f"  {fp.name}...", end=" ")
        if fp.suffix == ".csv":
            recs = load_csv(fp, name_cols)
        elif fp.suffix == ".json":
            recs = load_json(fp, name_cols)
        else:
            recs = []
        all_records.extend(recs)
        print(f"{len(recs)} entities")

    print(f"\nTotal entity records: {len(all_records):,}")
    print(f"Resolving with threshold: {args.threshold}")

    entities = resolve_entities(all_records, args.threshold)

    # Write output
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    output = {
        "metadata": {
            "created": now,
            "workspace": str(workspace),
            "datasets_processed": sorted({r.source_file for r in all_records}),
            "total_entities": len(entities),
            "total_records": len(all_records),
            "resolution_threshold": args.threshold,
        },
        "entities": [asdict(e) for e in entities],
    }

    out_path = workspace / "entities" / "canonical.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nCanonical map written: {out_path}")

    # Summary
    by_confidence = defaultdict(int)
    for e in entities:
        by_confidence[e.confidence] += 1
    print("\nConfidence breakdown:")
    for tier in ("confirmed", "probable", "possible", "unresolved"):
        count = by_confidence.get(tier, 0)
        print(f"  {tier}: {count}")


if __name__ == "__main__":
    main()

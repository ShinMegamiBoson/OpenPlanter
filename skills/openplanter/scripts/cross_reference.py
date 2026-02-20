#!/usr/bin/env python3
"""Cross-dataset record linking.

Loads the canonical entity map from entities/canonical.json and finds
records across datasets that share canonical entities. Outputs a
cross-reference report to findings/cross-references.json.

Uses Python stdlib only — zero external dependencies.

Usage:
    python3 cross_reference.py /path/to/investigation
    python3 cross_reference.py /path/to/investigation --datasets campaign.csv lobby.json
    python3 cross_reference.py /path/to/investigation --min-datasets 2
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_canonical_map(workspace: Path) -> dict[str, Any]:
    """Load the canonical entity map."""
    path = workspace / "entities" / "canonical.json"
    if not path.exists():
        print(f"Error: {path} not found. Run entity_resolver.py first.", file=sys.stderr)
        sys.exit(1)
    return json.loads(path.read_text(encoding="utf-8"))


def load_dataset_records(filepath: Path) -> list[dict[str, str]]:
    """Load all records from a CSV or JSON file."""
    if filepath.suffix == ".csv":
        return _load_csv_records(filepath)
    elif filepath.suffix == ".json":
        return _load_json_records(filepath)
    return []


def _load_csv_records(filepath: Path) -> list[dict[str, str]]:
    records = []
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
                for row_num, row in enumerate(reader, start=2):
                    rec = {k: (v or "").strip() for k, v in row.items()}
                    rec["__source_file"] = filepath.name
                    rec["__source_location"] = f"row:{row_num}"
                    records.append(rec)
                return records
        except UnicodeDecodeError:
            continue
    print(f"  Error: Cannot decode {filepath.name}")
    return records


def _load_json_records(filepath: Path) -> list[dict[str, str]]:
    records = []
    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return records

    items: list[dict] = []
    path_prefix = "$"
    if isinstance(data, list):
        items = [d for d in data if isinstance(d, dict)]
    elif isinstance(data, dict):
        for key in ("data", "results", "records", "items", "registrants", "filings"):
            if key in data and isinstance(data[key], list):
                items = [d for d in data[key] if isinstance(d, dict)]
                path_prefix = f"$.{key}"
                break
        else:
            items = [data]

    for idx, item in enumerate(items):
        rec = {k: str(v).strip() for k, v in item.items() if v is not None}
        rec["__source_file"] = filepath.name
        rec["__source_location"] = f"{path_prefix}[{idx}]"
        records.append(rec)
    return records


def find_cross_references(
    canonical_map: dict[str, Any],
    all_records: dict[str, list[dict[str, str]]],
    min_datasets: int = 2,
    dataset_filter: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Find records across datasets that share canonical entities."""
    entities = canonical_map.get("entities", [])
    cross_refs: list[dict[str, Any]] = []

    for entity in entities:
        canonical_name = entity["canonical_name"]
        canonical_id = entity["canonical_id"]
        variants = entity.get("variants", [])
        sources = entity.get("sources", [])

        if dataset_filter:
            sources = [s for s in sources if s in dataset_filter]

        if len(sources) < min_datasets:
            continue

        # Collect matching records from each dataset
        dataset_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for variant in variants:
            src = variant["source"]
            if dataset_filter and src not in dataset_filter:
                continue

            # Find the actual record in the loaded data
            loc = variant.get("location", "")
            for rec in all_records.get(src, []):
                if rec.get("__source_location") == loc:
                    dataset_records[src].append(
                        {
                            "variant_name": variant["name"],
                            "location": loc,
                            "similarity": variant.get("similarity", 0),
                            "fields": {
                                k: v
                                for k, v in rec.items()
                                if not k.startswith("__") and v
                            },
                        }
                    )
                    break

        if len(dataset_records) >= min_datasets:
            # Build cross-reference entry
            pairs: list[dict[str, Any]] = []
            ds_list = sorted(dataset_records.keys())
            for i in range(len(ds_list)):
                for j in range(i + 1, len(ds_list)):
                    ds_a, ds_b = ds_list[i], ds_list[j]
                    for rec_a in dataset_records[ds_a]:
                        for rec_b in dataset_records[ds_b]:
                            # Find common fields
                            common_fields = set(rec_a["fields"].keys()) & set(
                                rec_b["fields"].keys()
                            )
                            matching_fields = {
                                f: {
                                    "a": rec_a["fields"][f],
                                    "b": rec_b["fields"][f],
                                    "match": rec_a["fields"][f].lower().strip()
                                    == rec_b["fields"][f].lower().strip(),
                                }
                                for f in common_fields
                                if not f.startswith("__")
                            }
                            pairs.append(
                                {
                                    "dataset_a": ds_a,
                                    "record_a": rec_a,
                                    "dataset_b": ds_b,
                                    "record_b": rec_b,
                                    "matching_fields": matching_fields,
                                    "common_field_count": len(matching_fields),
                                    "exact_match_count": sum(
                                        1
                                        for v in matching_fields.values()
                                        if v["match"]
                                    ),
                                }
                            )

            cross_refs.append(
                {
                    "entity_id": canonical_id,
                    "entity_name": canonical_name,
                    "datasets": ds_list,
                    "dataset_count": len(ds_list),
                    "records_by_dataset": {
                        ds: len(recs) for ds, recs in dataset_records.items()
                    },
                    "cross_reference_pairs": pairs,
                    "confidence": entity.get("confidence", "unresolved"),
                }
            )

    return cross_refs


def generate_summary(
    cross_refs: list[dict[str, Any]], datasets: list[str]
) -> dict[str, Any]:
    """Generate summary statistics."""
    by_confidence = defaultdict(int)
    by_dataset_pair: dict[str, int] = defaultdict(int)

    for xref in cross_refs:
        by_confidence[xref["confidence"]] += 1
        for pair in xref.get("cross_reference_pairs", []):
            key = f"{pair['dataset_a']} <-> {pair['dataset_b']}"
            by_dataset_pair[key] += 1

    return {
        "total_cross_references": len(cross_refs),
        "by_confidence": dict(by_confidence),
        "by_dataset_pair": dict(by_dataset_pair),
        "datasets_analyzed": datasets,
        "entities_in_all_datasets": sum(
            1 for x in cross_refs if x["dataset_count"] == len(datasets)
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cross-reference records across datasets using canonical entity map"
    )
    parser.add_argument("workspace", type=Path, help="Path to investigation workspace")
    parser.add_argument(
        "--datasets",
        type=str,
        nargs="*",
        default=None,
        help="Specific dataset filenames to cross-reference (default: all)",
    )
    parser.add_argument(
        "--min-datasets",
        type=int,
        default=2,
        help="Minimum number of datasets an entity must appear in (default: 2)",
    )
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    datasets_dir = workspace / "datasets"

    # Load canonical map
    print("Loading canonical entity map...")
    canonical_map = load_canonical_map(workspace)
    entity_count = len(canonical_map.get("entities", []))
    print(f"  {entity_count} canonical entities loaded")

    # Load dataset records
    data_files = list(datasets_dir.glob("*.csv")) + list(datasets_dir.glob("*.json"))
    if args.datasets:
        data_files = [f for f in data_files if f.name in args.datasets]

    all_records: dict[str, list[dict[str, str]]] = {}
    print("Loading dataset records:")
    for fp in sorted(data_files):
        recs = load_dataset_records(fp)
        all_records[fp.name] = recs
        print(f"  {fp.name}: {len(recs)} records")

    # Find cross-references
    print(f"\nCross-referencing (min {args.min_datasets} datasets)...")
    cross_refs = find_cross_references(
        canonical_map, all_records, args.min_datasets, args.datasets
    )

    # Generate summary
    summary = generate_summary(cross_refs, [f.name for f in data_files])

    # Write output
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    output = {
        "metadata": {
            "created": now,
            "workspace": str(workspace),
            "min_datasets": args.min_datasets,
            "dataset_filter": args.datasets,
        },
        "summary": summary,
        "cross_references": cross_refs,
    }

    findings_dir = workspace / "findings"
    findings_dir.mkdir(exist_ok=True)
    out_path = findings_dir / "cross-references.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nCross-reference report: {out_path}")
    print(f"  Total cross-references: {summary['total_cross_references']}")
    print(f"  Entities in all datasets: {summary['entities_in_all_datasets']}")
    if summary["by_confidence"]:
        print("  By confidence:")
        for tier, count in sorted(summary["by_confidence"].items()):
            print(f"    {tier}: {count}")
    if summary["by_dataset_pair"]:
        print("  By dataset pair:")
        for pair, count in sorted(
            summary["by_dataset_pair"].items(), key=lambda x: -x[1]
        ):
            print(f"    {pair}: {count}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Fetch ICIJ Offshore Leaks Database records.

Queries the International Consortium of Investigative Journalists' Offshore
Leaks Database for entities, officers, intermediaries, and addresses linked
to offshore structures. Covers Panama Papers, Paradise Papers, Pandora Papers,
and Offshore Leaks datasets.

Critical for sanctions evasion investigations — links entity names to
offshore jurisdictions, registered agents, and beneficial ownership chains.

Uses Python stdlib only — zero external dependencies.

API: https://offshoreleaks.icij.org/search (public search)
     https://offshoreleaks-data.icij.org/offshoreleaks/search (JSON API)
Auth: None required (free public database).
Rate limit: Undocumented, ~1 req/sec recommended.

Usage:
    python3 fetch_icij.py /path/to/investigation --entity "Acme Holdings"
    python3 fetch_icij.py /path/to/investigation --entity "Mossack" --type intermediary
    python3 fetch_icij.py /path/to/investigation --entity "Iran" --jurisdiction
    python3 fetch_icij.py /path/to/investigation --list
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SEARCH_URL = "https://offshoreleaks.icij.org/api/v1/search"

# Entity types in the ICIJ database
ENTITY_TYPES = {
    "entity": "Offshore entities (companies, trusts, foundations)",
    "officer": "Officers and beneficial owners",
    "intermediary": "Intermediaries (law firms, banks, agents)",
    "address": "Registered addresses",
}

# Datasets available
DATASETS = {
    "panama_papers": "Mossack Fonseca leak (2016)",
    "paradise_papers": "Appleby + Asiaciti Trust (2017)",
    "pandora_papers": "14 offshore service providers (2021)",
    "offshore_leaks": "Original ICIJ leak (2013)",
    "bahamas_leaks": "Bahamas corporate registry (2016)",
}


def search_icij(
    query: str,
    entity_type: str | None = None,
    country: str | None = None,
    jurisdiction: str | None = None,
    dataset: str | None = None,
    limit: int = 100,
    timeout: int = 30,
) -> list[dict]:
    """Search the ICIJ Offshore Leaks Database."""
    params: dict[str, str] = {
        "q": query,
        "limit": str(limit),
    }
    if entity_type:
        params["type"] = entity_type
    if country:
        params["country"] = country
    if jurisdiction:
        params["jurisdiction"] = jurisdiction
    if dataset:
        params["dataset"] = dataset

    url = f"{SEARCH_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "OpenPlanter/1.0 (OSINT research tool)",
        "Accept": "application/json",
    })

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print("Rate limited by ICIJ — wait 60s and retry", file=sys.stderr)
            sys.exit(1)
        print(f"ERROR: ICIJ API returned {e.code}: {e.reason}", file=sys.stderr)
        raise

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: try scraping the public search HTML for structured data
        print("WARN: JSON parse failed, ICIJ may require browser access", file=sys.stderr)
        return _fallback_search(query, entity_type, timeout)

    # Handle different response shapes
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("results", data.get("data", [data]))

    return []


def _fallback_search(query: str, entity_type: str | None, timeout: int) -> list[dict]:
    """Fallback: scrape the public search page for basic results."""
    params = {"q": query}
    if entity_type:
        params["e"] = entity_type
    url = f"https://offshoreleaks.icij.org/search?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "OpenPlanter/1.0"})

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8")
    except urllib.error.HTTPError:
        return []

    # Extract JSON-LD or structured data if present
    import re
    ld_match = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
    if ld_match:
        try:
            return json.loads(ld_match.group(1))
        except json.JSONDecodeError:
            pass

    # Return empty — the web interface may require JavaScript
    print("WARN: ICIJ web interface may require JavaScript rendering", file=sys.stderr)
    return []


def normalize_records(records: list[dict]) -> list[dict]:
    """Normalize ICIJ records to a consistent schema."""
    normalized = []
    for rec in records:
        entry = {
            "icij_id": rec.get("id", rec.get("node_id", "")),
            "name": rec.get("name", rec.get("entity_name", "")),
            "type": rec.get("type", rec.get("entity_type", "")),
            "jurisdiction": rec.get("jurisdiction", rec.get("jurisdiction_description", "")),
            "country": rec.get("country_codes", rec.get("countries", "")),
            "dataset": rec.get("dataset", rec.get("sourceID", "")),
            "address": rec.get("address", rec.get("registered_address", "")),
            "incorporation_date": rec.get("incorporation_date", ""),
            "inactivation_date": rec.get("inactivation_date", ""),
            "status": rec.get("status", ""),
            "service_provider": rec.get("service_provider", ""),
            "linked_to": rec.get("connected_to", rec.get("linked_entities", [])),
            "note": rec.get("note", rec.get("internal_id", "")),
        }
        normalized.append(entry)
    return normalized


def write_results(
    workspace: Path,
    records: list[dict],
    query_params: dict,
) -> Path:
    """Write results to workspace with provenance."""
    out_dir = workspace / "datasets" / "scraped" / "icij"
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_query = query_params["query"][:40].replace(" ", "_").replace("/", "_")
    entity_type = query_params.get("entity_type") or "all"
    filename = f"icij-{safe_query}-{entity_type}.json"

    content = json.dumps(records, indent=2)
    out_path = out_dir / filename
    out_path.write_text(content, encoding="utf-8")

    provenance = {
        "source_id": "icij",
        "name": "ICIJ Offshore Leaks Database",
        "url": SEARCH_URL,
        "format": "json",
        "linking_keys": ["icij_id", "name", "jurisdiction", "country", "dataset"],
        "query_params": query_params,
        "download_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "file": filename,
        "size_bytes": len(content.encode("utf-8")),
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "record_count": len(records),
    }
    prov_path = out_dir / "provenance.json"
    prov_path.write_text(json.dumps(provenance, indent=2), encoding="utf-8")

    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search ICIJ Offshore Leaks Database for offshore entities and ownership"
    )
    parser.add_argument(
        "workspace", type=Path,
        help="Path to investigation workspace directory",
    )
    parser.add_argument("--entity", "-e", required=False, help="Entity name to search")
    parser.add_argument(
        "--type", "-t", dest="entity_type",
        choices=list(ENTITY_TYPES.keys()),
        help="Filter by entity type",
    )
    parser.add_argument("--country", help="Filter by country code (e.g., IR, RU, CN)")
    parser.add_argument("--jurisdiction", help="Filter by jurisdiction")
    parser.add_argument("--dataset", choices=list(DATASETS.keys()), help="Filter by leak dataset")
    parser.add_argument("--limit", type=int, default=100, help="Max results (default: 100)")
    parser.add_argument("--timeout", type=int, default=30, help="Request timeout (default: 30s)")
    parser.add_argument("--dry-run", action="store_true", help="Print query without fetching")
    parser.add_argument("--list", dest="list_info", action="store_true", help="Show entity types and datasets")

    args = parser.parse_args()

    if args.list_info:
        print("ICIJ Entity Types:")
        for k, v in ENTITY_TYPES.items():
            print(f"  {k:15s} {v}")
        print("\nDatasets:")
        for k, v in DATASETS.items():
            print(f"  {k:20s} {v}")
        return

    if not args.entity:
        print("ERROR: --entity is required", file=sys.stderr)
        sys.exit(1)

    workspace = args.workspace.resolve()
    if not workspace.exists():
        print(f"ERROR: Workspace does not exist: {workspace}", file=sys.stderr)
        sys.exit(1)

    query_params = {
        "query": args.entity,
        "entity_type": args.entity_type,
        "country": args.country,
        "jurisdiction": args.jurisdiction,
        "dataset": args.dataset,
    }

    if args.dry_run:
        print("Would search ICIJ Offshore Leaks:")
        for k, v in query_params.items():
            if v:
                print(f"  {k}: {v}")
        return

    print(f"Searching ICIJ Offshore Leaks for '{args.entity}'...")
    records = search_icij(
        query=args.entity,
        entity_type=args.entity_type,
        country=args.country,
        jurisdiction=args.jurisdiction,
        dataset=args.dataset,
        limit=args.limit,
        timeout=args.timeout,
    )

    if not records:
        print("No records found", file=sys.stderr)
        sys.exit(1)

    normalized = normalize_records(records)
    out_path = write_results(workspace, normalized, query_params)
    print(f"ICIJ: {len(normalized)} records → {out_path}")


if __name__ == "__main__":
    main()

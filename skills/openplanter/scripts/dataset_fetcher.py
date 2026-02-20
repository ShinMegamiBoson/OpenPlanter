#!/usr/bin/env python3
"""Download common public datasets for OSINT investigations.

Fetches bulk datasets from US government portals and open data sources
into a workspace's datasets/bulk/ directory with provenance metadata.

Uses Python stdlib only — zero external dependencies.

Supported sources:
    sec       — SEC EDGAR company tickers (CIK lookup table)
    fec       — FEC committee master file (current cycle)
    ofac      — OFAC SDN list (Treasury sanctions)
    sanctions — OpenSanctions simplified sanctions CSV
    lda       — Senate LDA registrant list (current year)

Usage:
    python3 dataset_fetcher.py /path/to/investigation --sources sec,fec,ofac
    python3 dataset_fetcher.py /path/to/investigation --sources all
    python3 dataset_fetcher.py /path/to/investigation --list
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Source registry — each entry defines a downloadable dataset
# ---------------------------------------------------------------------------

SOURCES: dict[str, dict] = {
    "sec": {
        "name": "SEC EDGAR Company Tickers",
        "description": "Ticker-to-CIK mapping for all SEC-registered entities",
        "url": "https://www.sec.gov/files/company_tickers.json",
        "filename": "company_tickers.json",
        "format": "json",
        "linking_keys": ["cik", "ticker"],
        "headers": {"User-Agent": "OpenPlanter/1.0 openplanter@investigation.local"},
    },
    "fec": {
        "name": "FEC Committee Master File",
        "description": "All registered political committees (current election cycle)",
        "url": "https://www.fec.gov/files/bulk-downloads/2024/committee_master_2024.csv",
        "filename": "committee_master.csv",
        "format": "csv",
        "linking_keys": ["committee_id", "committee_name", "treasurer_name"],
        "headers": {},
    },
    "ofac": {
        "name": "OFAC SDN List",
        "description": "Treasury Specially Designated Nationals and Blocked Persons",
        "url": "https://www.treasury.gov/ofac/downloads/sdn.csv",
        "filename": "sdn.csv",
        "format": "csv",
        "linking_keys": ["uid", "name", "sdnType", "programs"],
        "headers": {},
    },
    "sanctions": {
        "name": "OpenSanctions Simplified",
        "description": "Consolidated sanctions targets (non-commercial use)",
        "url": "https://data.opensanctions.org/datasets/latest/sanctions/targets.simple.csv",
        "filename": "sanctions_targets.csv",
        "format": "csv",
        "linking_keys": ["id", "name", "countries", "identifiers"],
        "headers": {},
    },
    "lda": {
        "name": "Senate LDA Registrants",
        "description": "Lobbying registrants from Senate Lobbying Disclosure Act filings",
        "url": "https://lda.senate.gov/api/v1/registrants/?format=json&page_size=100",
        "filename": "lda_registrants.json",
        "format": "json",
        "linking_keys": ["id", "name", "house_registrant_id"],
        "headers": {},
        "paginated": True,
    },
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _download(url: str, headers: dict[str, str], timeout: int = 60) -> bytes:
    """Download a URL and return raw bytes."""
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _download_paginated(
    base_url: str, headers: dict[str, str], timeout: int = 60, max_pages: int = 50
) -> list[dict]:
    """Download paginated JSON API (Senate LDA style: {next, results})."""
    all_results: list[dict] = []
    url: str | None = base_url
    page = 0

    while url and page < max_pages:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        results = data.get("results", [])
        all_results.extend(results)
        url = data.get("next")
        page += 1

        if url:
            time.sleep(0.5)  # polite rate limiting

    if url:
        print(f"    WARNING: Truncated at {max_pages} pages; more data available")

    return all_results


def fetch_source(
    source_id: str,
    workspace: Path,
    timeout: int = 120,
    dry_run: bool = False,
) -> dict:
    """Fetch a single source and write to datasets/bulk/{source_id}/."""
    spec = SOURCES[source_id]
    dest_dir = workspace / "datasets" / "bulk" / source_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest_file = dest_dir / spec["filename"]
    provenance_file = dest_dir / "provenance.json"

    if dry_run:
        print(f"  [dry-run] Would download: {spec['url']}")
        print(f"  [dry-run] Destination: {dest_file}")
        return {"source": source_id, "status": "dry-run"}

    print(f"  Downloading {spec['name']}...")
    print(f"    URL: {spec['url']}")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        if spec.get("paginated"):
            results = _download_paginated(
                spec["url"], spec.get("headers", {}), timeout=timeout
            )
            data = json.dumps(results, indent=2).encode("utf-8")
        else:
            data = _download(spec["url"], spec.get("headers", {}), timeout=timeout)

        dest_file.write_bytes(data)

        provenance = {
            "source_id": source_id,
            "name": spec["name"],
            "description": spec["description"],
            "url": spec["url"],
            "format": spec["format"],
            "linking_keys": spec["linking_keys"],
            "download_timestamp": now,
            "file": spec["filename"],
            "size_bytes": len(data),
            "sha256": _sha256(data),
        }
        provenance_file.write_text(json.dumps(provenance, indent=2), encoding="utf-8")

        print(f"    Saved: {dest_file} ({len(data):,} bytes)")
        return {"source": source_id, "status": "ok", "size": len(data)}

    except urllib.error.URLError as e:
        msg = f"Download failed: {e}"
        print(f"    ERROR: {msg}", file=sys.stderr)
        return {"source": source_id, "status": "error", "error": msg}
    except Exception as e:
        msg = f"Unexpected error: {e}"
        print(f"    ERROR: {msg}", file=sys.stderr)
        return {"source": source_id, "status": "error", "error": msg}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download public datasets for OSINT investigations"
    )
    parser.add_argument("workspace", type=Path, help="Path to investigation workspace")
    parser.add_argument(
        "--sources",
        type=str,
        default="all",
        help="Comma-separated source IDs, or 'all' (default: all)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_sources",
        help="List available sources and exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be downloaded without fetching",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="HTTP timeout in seconds (default: 120)",
    )
    args = parser.parse_args()

    if args.list_sources:
        print("Available sources:\n")
        for sid, spec in SOURCES.items():
            print(f"  {sid:12s}  {spec['name']}")
            print(f"  {'':<12s}  {spec['description']}")
            print(f"  {'':<12s}  Format: {spec['format']}  Keys: {', '.join(spec['linking_keys'])}")
            print()
        return

    workspace = args.workspace.resolve()
    if not workspace.exists():
        print(f"Error: workspace does not exist: {workspace}", file=sys.stderr)
        sys.exit(1)

    if args.sources == "all":
        source_ids = list(SOURCES.keys())
    else:
        source_ids = [s.strip() for s in args.sources.split(",")]
        unknown = [s for s in source_ids if s not in SOURCES]
        if unknown:
            print(
                f"Error: unknown source(s): {', '.join(unknown)}\n"
                f"Available: {', '.join(SOURCES.keys())}",
                file=sys.stderr,
            )
            sys.exit(1)

    print(f"Fetching {len(source_ids)} source(s) into {workspace / 'datasets' / 'bulk'}/\n")
    results = []
    for sid in source_ids:
        result = fetch_source(sid, workspace, timeout=args.timeout, dry_run=args.dry_run)
        results.append(result)
        print()

    ok = sum(1 for r in results if r["status"] == "ok")
    errs = sum(1 for r in results if r["status"] == "error")
    print(f"Done: {ok} succeeded, {errs} failed out of {len(results)} source(s)")

    if errs:
        sys.exit(1)


if __name__ == "__main__":
    main()

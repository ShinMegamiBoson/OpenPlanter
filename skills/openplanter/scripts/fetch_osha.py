#!/usr/bin/env python3
"""Fetch OSHA inspection and violation data.

Queries the Occupational Safety and Health Administration enforcement data
for workplace inspection records, violations, and penalties. Links
establishment names to SIC codes, inspection types, and penalty amounts.

Uses Python stdlib only — zero external dependencies.

API: https://enforcedata.dol.gov/homePage/api_dataset
     OSHA dataset via DOL Enforcement API
Auth: None required (free public API).
Rate limit: Undocumented, ~2 req/sec recommended.

Usage:
    python3 fetch_osha.py /path/to/investigation --query "Acme Manufacturing"
    python3 fetch_osha.py /path/to/investigation --state NY --sic 2911
    python3 fetch_osha.py /path/to/investigation --establishment "BP" --state TX
    python3 fetch_osha.py /path/to/investigation --list
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# DOL Enforcement Data API
DOL_BASE = "https://enforcedata.dol.gov/api/enforcement"
OSHA_DATASET = "inspection"

# Key SIC codes for WW Watcher investigations
RELEVANT_SIC_CODES = {
    "1311": "Crude petroleum and natural gas",
    "1381": "Drilling oil and gas wells",
    "2911": "Petroleum refining",
    "3312": "Steel works, blast furnaces",
    "3489": "Ordnance and accessories NEC",
    "3699": "Electronic components NEC",
    "3724": "Aircraft engines and engine parts",
    "3761": "Guided missiles and space vehicles",
    "4412": "Deep sea foreign transport—freight",
    "4911": "Electric services",
    "4922": "Natural gas distribution",
    "4923": "Natural gas transmission and distribution",
    "4924": "Natural gas distribution",
    "4953": "Refuse systems (hazardous waste)",
}


def search_inspections(
    query: str | None = None,
    state: str | None = None,
    sic: str | None = None,
    limit: int = 25,
    timeout: int = 30,
) -> list[dict]:
    """Search OSHA inspection records."""
    # DOL API uses a specific query format
    filters = []
    if query:
        filters.append(f"estab_name eq '{query}'")
    if state:
        filters.append(f"site_state eq '{state}'")
    if sic:
        filters.append(f"sic_code eq '{sic}'")

    params: dict[str, str] = {
        "dataset": OSHA_DATASET,
        "$top": str(limit),
        "$orderby": "open_date desc",
    }
    if filters:
        params["$filter"] = " and ".join(filters)

    url = f"{DOL_BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "OpenPlanter/1.0",
        "Accept": "application/json",
    })

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 400:
            # Try alternative: OSHA public search
            return _fallback_search(query, state, sic, limit, timeout)
        print(f"ERROR: DOL API returned {e.code}: {e.reason}", file=sys.stderr)
        raise

    # DOL API returns {"d": {"results": [...]}} or flat array
    if isinstance(data, dict):
        results = data.get("d", data).get("results", data.get("data", []))
    elif isinstance(data, list):
        results = data
    else:
        results = []

    records = []
    for item in results:
        record = {
            "activity_nr": str(item.get("activity_nr", "")),
            "estab_name": item.get("estab_name", ""),
            "site_address": item.get("site_address", ""),
            "site_city": item.get("site_city", ""),
            "site_state": item.get("site_state", ""),
            "site_zip": item.get("site_zip", ""),
            "sic_code": item.get("sic_code", ""),
            "naics_code": item.get("naics_code", ""),
            "insp_type": item.get("insp_type", ""),
            "open_date": item.get("open_date", ""),
            "close_case_date": item.get("close_case_date", ""),
            "total_violations": item.get("total_violations", 0),
            "total_serious": item.get("total_serious", 0),
            "total_willful": item.get("total_willful", 0),
            "total_repeat": item.get("total_repeat", 0),
            "total_penalty": item.get("total_current_penalty", item.get("total_penalty", 0)),
            "nr_in_estab": item.get("nr_in_estab", ""),
        }
        records.append(record)

    return records


def _fallback_search(
    query: str | None,
    state: str | None,
    sic: str | None,
    limit: int,
    timeout: int,
) -> list[dict]:
    """Fallback: try the OSHA public establishment search."""
    if not query:
        return []

    params = {
        "p_search_type": "A",
        "p_search_text": query,
        "p_format": "json",
    }
    if state:
        params["p_state"] = state

    url = f"https://www.osha.gov/pls/imis/establishment.search?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "OpenPlanter/1.0"})

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError:
        return []

    try:
        return json.loads(raw) if raw.strip().startswith("[") else []
    except json.JSONDecodeError:
        return []


def write_results(
    workspace: Path,
    records: list[dict],
    query_params: dict,
) -> Path:
    """Write results to workspace with provenance."""
    out_dir = workspace / "datasets" / "scraped" / "osha"
    out_dir.mkdir(parents=True, exist_ok=True)

    parts = ["osha"]
    if query_params.get("query"):
        safe = query_params["query"][:40].replace(" ", "_").replace("/", "_")
        parts.append(safe)
    if query_params.get("state"):
        parts.append(query_params["state"])
    if query_params.get("sic"):
        parts.append(f"sic{query_params['sic']}")
    filename = "-".join(parts) + ".json"

    content = json.dumps(records, indent=2)
    out_path = out_dir / filename
    out_path.write_text(content, encoding="utf-8")

    provenance = {
        "source_id": "osha",
        "name": "OSHA Inspection Data",
        "url": DOL_BASE,
        "format": "json",
        "linking_keys": ["activity_nr", "estab_name", "sic_code", "naics_code", "site_state"],
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
        description="Fetch OSHA inspection and violation data"
    )
    parser.add_argument(
        "workspace", type=Path,
        help="Path to investigation workspace directory",
    )
    parser.add_argument("--query", "-q", help="Establishment name search")
    parser.add_argument("--state", help="State abbreviation (e.g., TX)")
    parser.add_argument("--sic", help="SIC code (e.g., 2911 for petroleum refining)")
    parser.add_argument("--limit", type=int, default=25, help="Max results (default: 25)")
    parser.add_argument("--timeout", type=int, default=30, help="Request timeout (default: 30s)")
    parser.add_argument("--dry-run", action="store_true", help="Print query without fetching")
    parser.add_argument("--list", dest="list_info", action="store_true", help="Show relevant SIC codes")

    args = parser.parse_args()

    if args.list_info:
        print("Relevant SIC Codes for WW Watcher:")
        for code, desc in sorted(RELEVANT_SIC_CODES.items()):
            print(f"  {code}  {desc}")
        return

    workspace = args.workspace.resolve()
    if not workspace.exists():
        print(f"ERROR: Workspace does not exist: {workspace}", file=sys.stderr)
        sys.exit(1)

    if not any([args.query, args.state, args.sic]):
        print("ERROR: Provide at least one search criterion", file=sys.stderr)
        sys.exit(1)

    query_params = {
        "query": args.query,
        "state": args.state,
        "sic": args.sic,
    }

    if args.dry_run:
        print("Would search OSHA inspections:")
        for k, v in query_params.items():
            if v:
                print(f"  {k}: {v}")
        return

    print("Searching OSHA inspections...")
    records = search_inspections(
        query=args.query,
        state=args.state,
        sic=args.sic,
        limit=args.limit,
        timeout=args.timeout,
    )

    if not records:
        print("No inspections found", file=sys.stderr)
        sys.exit(1)

    out_path = write_results(workspace, records, query_params)
    print(f"OSHA: {len(records)} inspections → {out_path}")


if __name__ == "__main__":
    main()

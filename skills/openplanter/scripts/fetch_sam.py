#!/usr/bin/env python3
"""Fetch SAM.gov entity registration data.

Queries the System for Award Management (SAM.gov) Entity Management API
for federal contractor registrations. Links DUNS/UEI numbers to entity
names, CAGE codes, NAICS codes, and federal contract eligibility.

Critical for defense contractor investigations — every entity doing
business with the US government must register in SAM.gov.

Uses Python stdlib only — zero external dependencies.

API: https://api.sam.gov/entity-information/v3/entities
Auth: SAM_GOV_API_KEY env var required (free registration at api.data.gov).
Rate limit: 1000 req/day with key.

Usage:
    python3 fetch_sam.py /path/to/investigation --query "Raytheon"
    python3 fetch_sam.py /path/to/investigation --uei "ABCDEF123456"
    python3 fetch_sam.py /path/to/investigation --cage "1ABC2"
    python3 fetch_sam.py /path/to/investigation --naics 336411 --state CT
    python3 fetch_sam.py /path/to/investigation --list
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SAM_BASE = "https://api.sam.gov/entity-information/v3/entities"

# NAICS codes for defense/infrastructure investigations
RELEVANT_NAICS = {
    "336411": "Aircraft manufacturing",
    "336412": "Aircraft engine and engine parts manufacturing",
    "336414": "Guided missile and space vehicle manufacturing",
    "336415": "Guided missile and space vehicle propulsion",
    "336419": "Other guided missile and space vehicle parts",
    "332993": "Ammunition manufacturing",
    "332994": "Small arms, ordnance, and accessories",
    "334511": "Search, detection, navigation instruments",
    "334519": "Other measuring and controlling devices",
    "541330": "Engineering services",
    "541511": "Custom computer programming services",
    "541512": "Computer systems design services",
    "541519": "Other computer related services",
    "541690": "Other scientific and technical consulting",
    "541715": "R&D in physical, engineering, and life sciences",
    "561210": "Facilities support services",
    "561612": "Security guards and patrol services",
    "562211": "Hazardous waste treatment and disposal",
    "324110": "Petroleum refineries",
    "486110": "Pipeline transportation of crude oil",
    "486210": "Pipeline transportation of natural gas",
}


def search_entities(
    query: str | None = None,
    uei: str | None = None,
    cage: str | None = None,
    naics: str | None = None,
    state: str | None = None,
    country: str | None = None,
    api_key: str | None = None,
    limit: int = 25,
    timeout: int = 30,
) -> list[dict]:
    """Search SAM.gov entity registrations."""
    if not api_key:
        api_key = os.environ.get("SAM_GOV_API_KEY") or os.environ.get("SAM_API_KEY")
    if not api_key:
        print(
            "ERROR: SAM_GOV_API_KEY required. Register free at https://api.data.gov",
            file=sys.stderr,
        )
        sys.exit(1)

    params: dict[str, str] = {
        "api_key": api_key,
        "registrationStatus": "A",  # Active
        "includeSections": "entityRegistration,coreData",
        "page": "0",
        "size": str(limit),
    }
    if query:
        params["legalBusinessName"] = query
    if uei:
        params["ueiSAM"] = uei
    if cage:
        params["cageCode"] = cage
    if naics:
        params["naicsCode"] = naics
    if state:
        params["physicalAddressStateCode"] = state
    if country:
        params["physicalAddressCountryCode"] = country

    url = f"{SAM_BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "OpenPlanter/1.0",
        "Accept": "application/json",
    })

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 403:
            print("ERROR: Invalid SAM.gov API key", file=sys.stderr)
        elif e.code == 429:
            print("ERROR: SAM.gov rate limit exceeded (1000/day)", file=sys.stderr)
        else:
            print(f"ERROR: SAM.gov API returned {e.code}: {e.reason}", file=sys.stderr)
        raise

    entities = data.get("entityData", [])
    total = data.get("totalRecords", 0)

    records = []
    for entity in entities:
        reg = entity.get("entityRegistration", {})
        core = entity.get("coreData", {})
        phys_addr = core.get("physicalAddress", {})
        bus_types = core.get("businessTypes", {})
        naics_list = core.get("naicsCode", [])

        record = {
            "uei": reg.get("ueiSAM", ""),
            "cage_code": reg.get("cageCode", ""),
            "legal_business_name": reg.get("legalBusinessName", ""),
            "dba_name": reg.get("dbaName", ""),
            "registration_status": reg.get("registrationStatus", ""),
            "registration_date": reg.get("registrationDate", ""),
            "expiration_date": reg.get("expirationDate", ""),
            "activation_date": reg.get("activationDate", ""),
            "entity_type": reg.get("entityType", ""),
            "entity_structure": reg.get("entityStructure", ""),
            "exclusion_status": reg.get("exclusionStatusFlag", ""),
            "address_line1": phys_addr.get("addressLine1", ""),
            "city": phys_addr.get("city", ""),
            "state": phys_addr.get("stateOrProvinceCode", ""),
            "zip": phys_addr.get("zipCode", ""),
            "country": phys_addr.get("countryCode", ""),
            "naics_codes": [n.get("naicsCode", "") for n in naics_list] if isinstance(naics_list, list) else [],
            "primary_naics": core.get("primaryNaics", ""),
            "business_type_list": bus_types.get("businessTypeList", []),
            "sba_business_types": bus_types.get("sbaBusinessTypeList", []),
        }
        records.append(record)

    if total > limit:
        print(f"  (showing {len(records)} of {total} total)", file=sys.stderr)

    return records


def write_results(
    workspace: Path,
    records: list[dict],
    query_params: dict,
) -> Path:
    """Write results to workspace with provenance."""
    out_dir = workspace / "datasets" / "scraped" / "sam"
    out_dir.mkdir(parents=True, exist_ok=True)

    parts = ["sam"]
    if query_params.get("query"):
        safe = query_params["query"][:40].replace(" ", "_").replace("/", "_")
        parts.append(safe)
    if query_params.get("uei"):
        parts.append(f"uei{query_params['uei']}")
    if query_params.get("cage"):
        parts.append(f"cage{query_params['cage']}")
    if query_params.get("naics"):
        parts.append(f"naics{query_params['naics']}")
    filename = "-".join(parts) + ".json"

    content = json.dumps(records, indent=2)
    out_path = out_dir / filename
    out_path.write_text(content, encoding="utf-8")

    provenance = {
        "source_id": "sam",
        "name": "SAM.gov Entity Registration",
        "url": SAM_BASE,
        "format": "json",
        "linking_keys": ["uei", "cage_code", "legal_business_name", "naics_codes", "state"],
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
        description="Fetch SAM.gov federal contractor registration data"
    )
    parser.add_argument(
        "workspace", type=Path,
        help="Path to investigation workspace directory",
    )
    parser.add_argument("--query", "-q", help="Legal business name search")
    parser.add_argument("--uei", help="Unique Entity Identifier (UEI)")
    parser.add_argument("--cage", help="CAGE code")
    parser.add_argument("--naics", help="NAICS code (e.g., 336411)")
    parser.add_argument("--state", help="State abbreviation (e.g., CT)")
    parser.add_argument("--country", default="USA", help="Country code (default: USA)")
    parser.add_argument("--limit", type=int, default=25, help="Max results (default: 25)")
    parser.add_argument("--timeout", type=int, default=30, help="Request timeout (default: 30s)")
    parser.add_argument("--dry-run", action="store_true", help="Print query without fetching")
    parser.add_argument("--list", dest="list_info", action="store_true", help="Show relevant NAICS codes")

    args = parser.parse_args()

    if args.list_info:
        print("Relevant NAICS Codes for Defense/Infrastructure:")
        for code, desc in sorted(RELEVANT_NAICS.items()):
            print(f"  {code}  {desc}")
        return

    workspace = args.workspace.resolve()
    if not workspace.exists():
        print(f"ERROR: Workspace does not exist: {workspace}", file=sys.stderr)
        sys.exit(1)

    if not any([args.query, args.uei, args.cage, args.naics]):
        print("ERROR: Provide at least one search criterion", file=sys.stderr)
        sys.exit(1)

    query_params = {
        "query": args.query,
        "uei": args.uei,
        "cage": args.cage,
        "naics": args.naics,
        "state": args.state,
        "country": args.country,
    }

    if args.dry_run:
        print("Would search SAM.gov:")
        for k, v in query_params.items():
            if v:
                print(f"  {k}: {v}")
        return

    print("Searching SAM.gov entity registrations...")
    records = search_entities(
        query=args.query,
        uei=args.uei,
        cage=args.cage,
        naics=args.naics,
        state=args.state,
        country=args.country,
        limit=args.limit,
        timeout=args.timeout,
    )

    if not records:
        print("No entities found", file=sys.stderr)
        sys.exit(1)

    out_path = write_results(workspace, records, query_params)
    print(f"SAM.gov: {len(records)} entities → {out_path}")


if __name__ == "__main__":
    main()

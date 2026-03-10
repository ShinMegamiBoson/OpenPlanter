#!/usr/bin/env python3
"""Fetch EPA ECHO facility data for environmental compliance investigations.

Queries the EPA Enforcement and Compliance History Online (ECHO) API for
facility records, violations, inspections, and enforcement actions.
Critical for infrastructure investigations — links facility IDs to
geographic coordinates, SIC codes, and compliance history.

Uses Python stdlib only — zero external dependencies.

API: https://echo.epa.gov/tools/data-downloads
ECHO API: https://echodata.epa.gov/echo/dfr_rest_services.get_facility_info
Auth: None required (free public API).
Rate limit: Undocumented, ~2 req/sec recommended.

Usage:
    python3 fetch_epa.py /path/to/investigation --query "Acme Chemical"
    python3 fetch_epa.py /path/to/investigation --zipcode 12508
    python3 fetch_epa.py /path/to/investigation --state NY --city Beacon
    python3 fetch_epa.py /path/to/investigation --registry-id 110070416170
    python3 fetch_epa.py /path/to/investigation --list
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

# ECHO Detailed Facility Report API
ECHO_BASE = "https://echodata.epa.gov/echo"
FACILITY_SEARCH = f"{ECHO_BASE}/echo_rest_services.get_facilities"
FACILITY_INFO = f"{ECHO_BASE}/dfr_rest_services.get_facility_info"

# FRS (Facility Registry Service) for cross-referencing
FRS_BASE = "https://ofmpub.epa.gov/frs_public2/frs_rest_services.get_facilities"


def search_facilities(
    query: str | None = None,
    state: str | None = None,
    city: str | None = None,
    zipcode: str | None = None,
    registry_id: str | None = None,
    page_size: int = 25,
    timeout: int = 30,
) -> list[dict]:
    """Search ECHO for facilities matching criteria."""
    params: dict[str, str] = {
        "output": "JSON",
        "p_act": "Y",  # Active facilities
    }
    if query:
        params["p_fn"] = query  # Facility name
    if state:
        params["p_st"] = state
    if city:
        params["p_ct"] = city
    if zipcode:
        params["p_zip"] = zipcode
    if registry_id:
        params["p_frs"] = registry_id

    url = f"{FACILITY_SEARCH}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "OpenPlanter/1.0"})

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"ERROR: ECHO API returned {e.code}: {e.reason}", file=sys.stderr)
        raise

    # ECHO wraps results in Results.Facilities
    results = data.get("Results", {})
    facilities = results.get("Facilities", [])

    records = []
    for fac in facilities:
        record = {
            "registry_id": fac.get("RegistryId", ""),
            "facility_name": fac.get("FacilityName", ""),
            "street": fac.get("Street", ""),
            "city": fac.get("City", ""),
            "state": fac.get("State", ""),
            "zip": fac.get("Zip", ""),
            "county": fac.get("County", ""),
            "lat": fac.get("Lat", ""),
            "lon": fac.get("Lon", ""),
            "sic_codes": fac.get("SICCodes", ""),
            "naics_codes": fac.get("NAICSCodes", ""),
            "facility_type": fac.get("FacilityType", ""),
            "air_flag": fac.get("AirFlag", ""),
            "water_flag": fac.get("CWAFlag", ""),
            "rcra_flag": fac.get("RCRAFlag", ""),
            "tri_flag": fac.get("TRIFlag", ""),
            "current_violations": fac.get("CurrVioFlag", ""),
            "qtrs_in_nc": fac.get("QtrsInNC", ""),
            "inspection_count": fac.get("InspectionCount", ""),
            "formal_action_count": fac.get("FormalActionCount", ""),
        }
        records.append(record)

    return records


def write_results(
    workspace: Path,
    records: list[dict],
    query_params: dict,
) -> Path:
    """Write results to workspace with provenance."""
    out_dir = workspace / "datasets" / "scraped" / "epa"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build filename
    parts = ["echo"]
    if query_params.get("query"):
        safe = query_params["query"][:40].replace(" ", "_").replace("/", "_")
        parts.append(safe)
    if query_params.get("state"):
        parts.append(query_params["state"])
    if query_params.get("zipcode"):
        parts.append(f"zip{query_params['zipcode']}")
    filename = "-".join(parts) + ".json"

    content = json.dumps(records, indent=2)
    out_path = out_dir / filename
    out_path.write_text(content, encoding="utf-8")

    provenance = {
        "source_id": "epa",
        "name": "EPA ECHO Facility Search",
        "url": FACILITY_SEARCH,
        "format": "json",
        "linking_keys": ["registry_id", "facility_name", "sic_codes", "naics_codes", "lat", "lon"],
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
        description="Fetch EPA ECHO facility data for environmental compliance investigations"
    )
    parser.add_argument(
        "workspace", type=Path,
        help="Path to investigation workspace directory",
    )
    parser.add_argument("--query", "-q", help="Facility name search")
    parser.add_argument("--state", help="State abbreviation (e.g., NY)")
    parser.add_argument("--city", help="City name")
    parser.add_argument("--zipcode", help="ZIP code")
    parser.add_argument("--registry-id", help="EPA FRS Registry ID")
    parser.add_argument("--timeout", type=int, default=30, help="Request timeout (default: 30s)")
    parser.add_argument("--dry-run", action="store_true", help="Print query without fetching")
    parser.add_argument("--list", dest="list_info", action="store_true", help="Show available fields")

    args = parser.parse_args()

    if args.list_info:
        print("EPA ECHO Facility Fields:")
        print("  registry_id          EPA Facility Registry Service ID")
        print("  facility_name        Official facility name")
        print("  sic_codes            Standard Industrial Classification")
        print("  naics_codes          North American Industry Classification")
        print("  lat, lon             Geographic coordinates")
        print("  current_violations   Active violation flag")
        print("  qtrs_in_nc           Quarters in non-compliance")
        print("  inspection_count     Total inspections")
        print("  formal_action_count  Formal enforcement actions")
        print("\nProgram flags: air_flag, water_flag (CWA), rcra_flag, tri_flag")
        return

    workspace = args.workspace.resolve()
    if not workspace.exists():
        print(f"ERROR: Workspace does not exist: {workspace}", file=sys.stderr)
        sys.exit(1)

    if not any([args.query, args.state, args.city, args.zipcode, args.registry_id]):
        print("ERROR: Provide at least one search criterion", file=sys.stderr)
        sys.exit(1)

    query_params = {
        "query": args.query,
        "state": args.state,
        "city": args.city,
        "zipcode": args.zipcode,
        "registry_id": args.registry_id,
    }

    if args.dry_run:
        print("Would search EPA ECHO:")
        for k, v in query_params.items():
            if v:
                print(f"  {k}: {v}")
        return

    print("Searching EPA ECHO facilities...")
    records = search_facilities(
        query=args.query,
        state=args.state,
        city=args.city,
        zipcode=args.zipcode,
        registry_id=args.registry_id,
        timeout=args.timeout,
    )

    if not records:
        print("No facilities found", file=sys.stderr)
        sys.exit(1)

    out_path = write_results(workspace, records, query_params)
    print(f"EPA: {len(records)} facilities → {out_path}")


if __name__ == "__main__":
    main()

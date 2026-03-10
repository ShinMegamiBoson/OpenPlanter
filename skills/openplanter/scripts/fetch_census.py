#!/usr/bin/env python3
"""Fetch US Census Bureau American Community Survey (ACS) data.

Queries the Census Bureau API for demographic and economic data by geography.
Useful for investigations involving population context, income distribution,
housing patterns, and demographic profiling of areas linked to entities.

Uses Python stdlib only — zero external dependencies.

API: https://api.census.gov/data/{year}/acs/acs5
Auth: Optional API key (CENSUS_API_KEY env var) — works without key at lower rate limits.
Rate limit: ~500 req/day without key, unlimited with key.

Usage:
    python3 fetch_census.py /path/to/investigation --state 36 --county 027
    python3 fetch_census.py /path/to/investigation --state 36 --place "New York city"
    python3 fetch_census.py /path/to/investigation --zipcode 10001
    python3 fetch_census.py /path/to/investigation --list
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ACS 5-year variables of investigative interest
DEFAULT_VARIABLES = [
    "NAME",               # Geography name
    "B01003_001E",        # Total population
    "B19013_001E",        # Median household income
    "B25077_001E",        # Median home value
    "B25064_001E",        # Median gross rent
    "B23025_002E",        # In labor force
    "B23025_005E",        # Unemployed
    "B15003_022E",        # Bachelor's degree
    "B15003_023E",        # Master's degree
    "B15003_025E",        # Doctorate degree
    "B02001_002E",        # White alone
    "B02001_003E",        # Black alone
    "B03003_003E",        # Hispanic or Latino
]

VARIABLE_LABELS = {
    "NAME": "Geography Name",
    "B01003_001E": "Total Population",
    "B19013_001E": "Median Household Income ($)",
    "B25077_001E": "Median Home Value ($)",
    "B25064_001E": "Median Gross Rent ($)",
    "B23025_002E": "In Labor Force",
    "B23025_005E": "Unemployed",
    "B15003_022E": "Bachelor's Degree",
    "B15003_023E": "Master's Degree",
    "B15003_025E": "Doctorate Degree",
    "B02001_002E": "White Alone",
    "B02001_003E": "Black or African American Alone",
    "B03003_003E": "Hispanic or Latino",
}

BASE_URL = "https://api.census.gov/data"
DEFAULT_YEAR = 2022  # Latest available 5-year ACS


def fetch_acs(
    year: int,
    variables: list[str],
    state: str | None = None,
    county: str | None = None,
    zipcode: str | None = None,
    api_key: str | None = None,
    timeout: int = 30,
) -> list[dict]:
    """Query ACS 5-year estimates."""
    url = f"{BASE_URL}/{year}/acs/acs5"
    params: dict[str, str] = {
        "get": ",".join(variables),
    }

    # Build geography
    if zipcode:
        params["for"] = f"zip code tabulation area:{zipcode}"
    elif county and state:
        params["for"] = f"county:{county}"
        params["in"] = f"state:{state}"
    elif state:
        params["for"] = f"county:*"
        params["in"] = f"state:{state}"
    else:
        params["for"] = "us:*"

    if api_key:
        params["key"] = api_key

    query = urllib.parse.urlencode(params)
    full_url = f"{url}?{query}"

    req = urllib.request.Request(full_url, headers={"User-Agent": "OpenPlanter/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"ERROR: Census API returned {e.code}: {e.reason}", file=sys.stderr)
        if e.code == 204:
            print("No data available for this geography", file=sys.stderr)
            return []
        raise

    if not data or len(data) < 2:
        return []

    headers = data[0]
    records = []
    for row in data[1:]:
        record = dict(zip(headers, row))
        records.append(record)

    return records


def write_results(
    workspace: Path,
    records: list[dict],
    query_params: dict,
    year: int,
) -> Path:
    """Write results to workspace with provenance."""
    out_dir = workspace / "datasets" / "bulk" / "census"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build filename from query params
    parts = [f"acs5-{year}"]
    if query_params.get("state"):
        parts.append(f"state{query_params['state']}")
    if query_params.get("county"):
        parts.append(f"county{query_params['county']}")
    if query_params.get("zipcode"):
        parts.append(f"zip{query_params['zipcode']}")
    filename = "-".join(parts) + ".json"

    content = json.dumps(records, indent=2)
    out_path = out_dir / filename
    out_path.write_text(content, encoding="utf-8")

    # Provenance sidecar
    provenance = {
        "source_id": "census",
        "name": f"US Census ACS 5-Year Estimates ({year})",
        "url": f"{BASE_URL}/{year}/acs/acs5",
        "format": "json",
        "linking_keys": ["state", "county", "zip code tabulation area", "NAME"],
        "query_params": query_params,
        "download_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "file": filename,
        "size_bytes": len(content.encode("utf-8")),
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "record_count": len(records),
        "variables": list(VARIABLE_LABELS.keys()),
    }
    prov_path = out_dir / "provenance.json"
    prov_path.write_text(json.dumps(provenance, indent=2), encoding="utf-8")

    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch US Census ACS demographic data for investigation context"
    )
    parser.add_argument(
        "workspace", type=Path,
        help="Path to investigation workspace directory",
    )
    parser.add_argument("--state", help="FIPS state code (e.g., 36 for NY)")
    parser.add_argument("--county", help="FIPS county code (e.g., 027 for Dutchess)")
    parser.add_argument("--zipcode", help="ZIP code tabulation area")
    parser.add_argument(
        "--year", type=int, default=DEFAULT_YEAR,
        help=f"ACS year (default: {DEFAULT_YEAR})",
    )
    parser.add_argument(
        "--variables", help="Comma-separated ACS variable codes (default: demographic set)",
    )
    parser.add_argument("--timeout", type=int, default=30, help="Request timeout (default: 30s)")
    parser.add_argument("--dry-run", action="store_true", help="Print URL without fetching")
    parser.add_argument("--list", dest="list_vars", action="store_true", help="List available variables")

    args = parser.parse_args()

    if args.list_vars:
        print("Default ACS 5-Year Variables:")
        for code, label in VARIABLE_LABELS.items():
            print(f"  {code:16s} {label}")
        return

    workspace = args.workspace.resolve()
    if not workspace.exists():
        print(f"ERROR: Workspace does not exist: {workspace}", file=sys.stderr)
        sys.exit(1)

    variables = args.variables.split(",") if args.variables else DEFAULT_VARIABLES
    api_key = os.environ.get("CENSUS_API_KEY")

    query_params = {
        "state": args.state,
        "county": args.county,
        "zipcode": args.zipcode,
        "year": args.year,
    }

    if args.dry_run:
        print(f"Would fetch ACS {args.year} data:")
        print(f"  Variables: {len(variables)}")
        print(f"  State: {args.state or 'all'}")
        print(f"  County: {args.county or 'all'}")
        print(f"  ZIP: {args.zipcode or 'n/a'}")
        print(f"  API key: {'set' if api_key else 'not set (rate-limited)'}")
        return

    print(f"Fetching Census ACS {args.year} data...")
    records = fetch_acs(
        year=args.year,
        variables=variables,
        state=args.state,
        county=args.county,
        zipcode=args.zipcode,
        api_key=api_key,
        timeout=args.timeout,
    )

    if not records:
        print("No records returned", file=sys.stderr)
        sys.exit(1)

    out_path = write_results(workspace, records, query_params, args.year)
    print(f"Census: {len(records)} records → {out_path}")


if __name__ == "__main__":
    main()

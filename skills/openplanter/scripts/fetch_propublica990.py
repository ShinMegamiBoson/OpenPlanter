#!/usr/bin/env python3
"""Fetch nonprofit tax filing data from ProPublica Nonprofit Explorer.

Queries the ProPublica Nonprofit Explorer API for IRS Form 990 data —
organizational finances, compensation, program expenses, and governance.
Links EINs to organization names, revenue, and executive compensation.

Critical for investigations involving nonprofits, foundations, think tanks,
and dark money flows in defense/intelligence circles.

Uses Python stdlib only — zero external dependencies.

API: https://projects.propublica.org/nonprofits/api/v2
Auth: None required (free public API).
Rate limit: Undocumented, ~1 req/sec recommended.

Usage:
    python3 fetch_propublica990.py /path/to/investigation --query "Heritage Foundation"
    python3 fetch_propublica990.py /path/to/investigation --ein 237327340
    python3 fetch_propublica990.py /path/to/investigation --query "defense" --state DC --ntee U
    python3 fetch_propublica990.py /path/to/investigation --list
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

PP_BASE = "https://projects.propublica.org/nonprofits/api/v2"

# NTEE codes relevant to defense/intelligence/policy investigations
RELEVANT_NTEE = {
    "Q": "International, Foreign Affairs, and National Security",
    "R": "Civil Rights, Social Action, Advocacy",
    "S": "Community Improvement, Capacity Building",
    "U": "Science and Technology Research Institutes",
    "W": "Public, Society Benefit — Multipurpose and Other",
    "X": "Religion Related, Spiritual Development",
}


def search_organizations(
    query: str,
    state: str | None = None,
    ntee: str | None = None,
    page: int = 0,
    timeout: int = 30,
) -> list[dict]:
    """Search ProPublica Nonprofit Explorer."""
    params: dict[str, str] = {
        "q": query,
        "page": str(page),
    }
    if state:
        params["state[id]"] = state
    if ntee:
        params["ntee[id]"] = ntee

    url = f"{PP_BASE}/search.json?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "OpenPlanter/1.0",
        "Accept": "application/json",
    })

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"ERROR: ProPublica API returned {e.code}: {e.reason}", file=sys.stderr)
        raise

    organizations = data.get("organizations", [])
    records = []
    for org in organizations:
        record = {
            "ein": str(org.get("ein", "")),
            "name": org.get("name", ""),
            "city": org.get("city", ""),
            "state": org.get("state", ""),
            "ntee_code": org.get("ntee_code", ""),
            "subsection_code": org.get("subsection_code", ""),
            "classification_codes": org.get("classification_codes", ""),
            "ruling_date": org.get("ruling_date", ""),
            "deductibility_code": org.get("deductibility_code", ""),
            "foundation_code": org.get("foundation_code", ""),
            "activity_codes": org.get("activity_codes", ""),
            "organization_code": org.get("organization_code", ""),
            "exempt_organization_status_code": org.get("exempt_organization_status_code", ""),
            "tax_period": org.get("tax_period", ""),
            "asset_amount": org.get("asset_amount", 0),
            "income_amount": org.get("income_amount", 0),
            "revenue_amount": org.get("revenue_amount", 0),
            "score": org.get("score", 0),
        }
        records.append(record)

    return records


def get_organization(ein: str, timeout: int = 30) -> dict | None:
    """Get detailed organization data by EIN."""
    url = f"{PP_BASE}/organizations/{ein}.json"
    req = urllib.request.Request(url, headers={
        "User-Agent": "OpenPlanter/1.0",
        "Accept": "application/json",
    })

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        print(f"ERROR: ProPublica API returned {e.code}: {e.reason}", file=sys.stderr)
        raise

    org = data.get("organization", {})
    filings = data.get("filings_with_data", [])

    record = {
        "ein": str(org.get("ein", "")),
        "name": org.get("name", ""),
        "address": org.get("address", ""),
        "city": org.get("city", ""),
        "state": org.get("state", ""),
        "zipcode": org.get("zipcode", ""),
        "ntee_code": org.get("ntee_code", ""),
        "subsection_code": org.get("subsection_code", ""),
        "total_revenue": org.get("total_revenue", 0),
        "total_expenses": org.get("total_expenses", 0),
        "total_assets": org.get("total_assets", 0),
        "tax_period": org.get("tax_period", ""),
        "filing_count": len(filings),
        "latest_filing": {},
    }

    if filings:
        latest = filings[0]
        record["latest_filing"] = {
            "tax_prd": latest.get("tax_prd", ""),
            "tax_prd_yr": latest.get("tax_prd_yr", ""),
            "totrevenue": latest.get("totrevenue", 0),
            "totfuncexpns": latest.get("totfuncexpns", 0),
            "totassetsend": latest.get("totassetsend", 0),
            "totliabend": latest.get("totliabend", 0),
            "compnsatncurrofcrs": latest.get("compnsatncurrofcrs", 0),
            "pdf_url": latest.get("pdf_url", ""),
        }

    return record


def write_results(
    workspace: Path,
    records: list[dict],
    query_params: dict,
) -> Path:
    """Write results to workspace with provenance."""
    out_dir = workspace / "datasets" / "scraped" / "propublica990"
    out_dir.mkdir(parents=True, exist_ok=True)

    if query_params.get("ein"):
        filename = f"990-ein{query_params['ein']}.json"
    else:
        safe = query_params.get("query", "search")[:40].replace(" ", "_").replace("/", "_")
        filename = f"990-{safe}.json"

    content = json.dumps(records, indent=2)
    out_path = out_dir / filename
    out_path.write_text(content, encoding="utf-8")

    provenance = {
        "source_id": "propublica990",
        "name": "ProPublica Nonprofit Explorer (IRS 990)",
        "url": PP_BASE,
        "format": "json",
        "linking_keys": ["ein", "name", "ntee_code", "state"],
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
        description="Fetch nonprofit IRS 990 data from ProPublica Nonprofit Explorer"
    )
    parser.add_argument(
        "workspace", type=Path,
        help="Path to investigation workspace directory",
    )
    parser.add_argument("--query", "-q", help="Organization name search")
    parser.add_argument("--ein", help="Employer Identification Number (direct lookup)")
    parser.add_argument("--state", help="State abbreviation (e.g., DC)")
    parser.add_argument("--ntee", help="NTEE classification code (e.g., Q, U)")
    parser.add_argument("--page", type=int, default=0, help="Results page (default: 0)")
    parser.add_argument("--timeout", type=int, default=30, help="Request timeout (default: 30s)")
    parser.add_argument("--dry-run", action="store_true", help="Print query without fetching")
    parser.add_argument("--list", dest="list_info", action="store_true", help="Show relevant NTEE codes")

    args = parser.parse_args()

    if args.list_info:
        print("Relevant NTEE Codes:")
        for code, desc in sorted(RELEVANT_NTEE.items()):
            print(f"  {code}  {desc}")
        return

    if not args.query and not args.ein:
        print("ERROR: Provide --query or --ein", file=sys.stderr)
        sys.exit(1)

    workspace = args.workspace.resolve()
    if not workspace.exists():
        print(f"ERROR: Workspace does not exist: {workspace}", file=sys.stderr)
        sys.exit(1)

    query_params = {
        "query": args.query,
        "ein": args.ein,
        "state": args.state,
        "ntee": args.ntee,
    }

    if args.dry_run:
        print("Would search ProPublica 990:")
        for k, v in query_params.items():
            if v:
                print(f"  {k}: {v}")
        return

    if args.ein:
        print(f"Fetching 990 for EIN {args.ein}...")
        record = get_organization(args.ein, timeout=args.timeout)
        if not record:
            print(f"No organization found for EIN {args.ein}", file=sys.stderr)
            sys.exit(1)
        records = [record]
    else:
        print(f"Searching nonprofits for '{args.query}'...")
        records = search_organizations(
            query=args.query,
            state=args.state,
            ntee=args.ntee,
            page=args.page,
            timeout=args.timeout,
        )

    if not records:
        print("No records found", file=sys.stderr)
        sys.exit(1)

    out_path = write_results(workspace, records, query_params)
    print(f"ProPublica 990: {len(records)} organizations → {out_path}")


if __name__ == "__main__":
    main()

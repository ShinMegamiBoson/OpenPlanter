#!/usr/bin/env python3
"""
OSHA Inspection Data Fetcher

Queries the U.S. Department of Labor's Open Data Portal API for OSHA inspection records.
Uses only Python standard library (urllib, json, argparse).

API Documentation: https://dataportal.dol.gov/pdf/dol-api-user-guide.pdf
API Key Registration: https://dataportal.dol.gov/api-keys

Usage:
    python fetch_osha.py --api-key YOUR_KEY --limit 10
    python fetch_osha.py --state MA --year 2024 --output inspections.json
    python fetch_osha.py --establishment "ABC Corp" --format csv
"""

import argparse
import json
import sys
import urllib.request
import urllib.parse
import urllib.error
from typing import Any, Dict, List, Optional
from datetime import datetime


BASE_URL = "https://data.dol.gov/get/inspection"


def build_filter(
    state: Optional[str] = None,
    year: Optional[int] = None,
    establishment: Optional[str] = None,
    open_after: Optional[str] = None,
) -> Optional[str]:
    """
    Build DOL API filter JSON string.

    Filter syntax: [{"field": "field_name", "operator": "eq|gt|lt|in|like", "value": "val"}]
    """
    filters = []

    if state:
        filters.append({
            "field": "site_state",
            "operator": "eq",
            "value": state.upper()
        })

    if year:
        # Filter for inspections opened in the specified year
        filters.append({
            "field": "open_date",
            "operator": "gt",
            "value": f"{year}-01-01"
        })
        filters.append({
            "field": "open_date",
            "operator": "lt",
            "value": f"{year}-12-31"
        })

    if establishment:
        filters.append({
            "field": "estab_name",
            "operator": "like",
            "value": establishment
        })

    if open_after:
        filters.append({
            "field": "open_date",
            "operator": "gt",
            "value": open_after
        })

    return json.dumps(filters) if filters else None


def fetch_inspections(
    api_key: str,
    top: int = 100,
    skip: int = 0,
    filter_json: Optional[str] = None,
    fields: Optional[str] = None,
    sort_by: str = "open_date",
    sort_order: str = "desc",
) -> Dict[str, Any]:
    """
    Query the DOL OSHA inspection API.

    Args:
        api_key: DOL API key (register at dataportal.dol.gov/api-keys)
        top: Number of records to return (max 200)
        skip: Number of records to skip (for pagination)
        filter_json: JSON-encoded filter array
        fields: Comma-separated field list
        sort_by: Field name to sort by
        sort_order: 'asc' or 'desc'

    Returns:
        Parsed JSON response from API
    """
    params = {
        "top": str(min(top, 200)),  # API enforces max 200
        "skip": str(skip),
        "sort_by": sort_by,
        "sort": sort_order,
    }

    if filter_json:
        params["filter"] = filter_json

    if fields:
        params["fields"] = fields

    query_string = urllib.parse.urlencode(params)
    url = f"{BASE_URL}?{query_string}"

    request = urllib.request.Request(url)
    request.add_header("X-API-KEY", api_key)
    request.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read()
            return json.loads(data.decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.reason}", file=sys.stderr)
        print(f"URL: {url}", file=sys.stderr)
        if e.code == 401:
            print("Authentication failed. Check your API key.", file=sys.stderr)
        elif e.code == 400:
            print("Bad request. Check filter syntax.", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"URL Error: {e.reason}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}", file=sys.stderr)
        sys.exit(1)


def format_as_csv(records: List[Dict[str, Any]]) -> str:
    """Convert inspection records to CSV format."""
    if not records:
        return ""

    # Extract headers from first record
    headers = list(records[0].keys())
    csv_lines = [",".join(headers)]

    for record in records:
        values = []
        for header in headers:
            val = record.get(header, "")
            # Escape commas and quotes
            val_str = str(val) if val is not None else ""
            if "," in val_str or '"' in val_str:
                val_str = '"' + val_str.replace('"', '""') + '"'
            values.append(val_str)
        csv_lines.append(",".join(values))

    return "\n".join(csv_lines)


def main():
    parser = argparse.ArgumentParser(
        description="Fetch OSHA inspection data from DOL Open Data Portal",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Fetch 50 most recent inspections
  python fetch_osha.py --api-key YOUR_KEY --limit 50

  # Fetch Massachusetts inspections from 2024
  python fetch_osha.py --api-key YOUR_KEY --state MA --year 2024

  # Search by establishment name
  python fetch_osha.py --api-key YOUR_KEY --establishment "ABC Corp"

  # Export to CSV
  python fetch_osha.py --api-key YOUR_KEY --limit 100 --format csv --output osha.csv

  # Get specific fields only
  python fetch_osha.py --api-key YOUR_KEY --fields activity_nr,estab_name,open_date,site_city

Environment Variables:
  DOL_API_KEY - API key (alternative to --api-key flag)

API Key Registration:
  https://dataportal.dol.gov/api-keys
        """
    )

    parser.add_argument(
        "--api-key",
        help="DOL API key (or set DOL_API_KEY env var)",
        default=None
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Number of records to fetch (default: 100, max: 200)"
    )
    parser.add_argument(
        "--skip",
        type=int,
        default=0,
        help="Number of records to skip (for pagination)"
    )
    parser.add_argument(
        "--state",
        help="Filter by state (2-letter code, e.g., MA, CA, TX)"
    )
    parser.add_argument(
        "--year",
        type=int,
        help="Filter by inspection year (e.g., 2024)"
    )
    parser.add_argument(
        "--establishment",
        help="Filter by establishment name (partial match)"
    )
    parser.add_argument(
        "--open-after",
        help="Filter inspections opened after date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--fields",
        help="Comma-separated list of fields to return (default: all fields)"
    )
    parser.add_argument(
        "--sort-by",
        default="open_date",
        help="Field to sort by (default: open_date)"
    )
    parser.add_argument(
        "--sort-order",
        choices=["asc", "desc"],
        default="desc",
        help="Sort order (default: desc)"
    )
    parser.add_argument(
        "--format",
        choices=["json", "csv"],
        default="json",
        help="Output format (default: json)"
    )
    parser.add_argument(
        "--output",
        help="Output file path (default: stdout)"
    )

    args = parser.parse_args()

    # Get API key from args or environment
    import os
    api_key = args.api_key or os.environ.get("DOL_API_KEY")
    if not api_key:
        print("Error: API key required. Use --api-key or set DOL_API_KEY environment variable.", file=sys.stderr)
        print("Register for a free API key at: https://dataportal.dol.gov/api-keys", file=sys.stderr)
        sys.exit(1)

    # Build filter
    filter_json = build_filter(
        state=args.state,
        year=args.year,
        establishment=args.establishment,
        open_after=args.open_after
    )

    # Fetch data
    print(f"Fetching up to {args.limit} records from DOL OSHA API...", file=sys.stderr)
    if filter_json:
        print(f"Filter: {filter_json}", file=sys.stderr)

    result = fetch_inspections(
        api_key=api_key,
        top=args.limit,
        skip=args.skip,
        filter_json=filter_json,
        fields=args.fields,
        sort_by=args.sort_by,
        sort_order=args.sort_order
    )

    # Extract records from response
    # DOL API returns different response structures; handle both
    if isinstance(result, list):
        records = result
    elif isinstance(result, dict):
        # Common structures: {"results": [...]} or {"data": [...]} or just the records
        records = result.get("results") or result.get("data") or result.get("inspection") or []
    else:
        records = []

    print(f"Retrieved {len(records)} inspection records.", file=sys.stderr)

    # Format output
    if args.format == "csv":
        output_content = format_as_csv(records)
    else:
        output_content = json.dumps(records, indent=2, default=str)

    # Write output
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_content)
        print(f"Output written to {args.output}", file=sys.stderr)
    else:
        print(output_content)


if __name__ == "__main__":
    main()

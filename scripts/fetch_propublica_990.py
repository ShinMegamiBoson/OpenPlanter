#!/usr/bin/env python3
"""
Fetch nonprofit 990 data from ProPublica's Nonprofit Explorer API v2.

This script queries the ProPublica API for organization searches and individual
EIN lookups. Uses only Python standard library (urllib.request, json).

Usage:
    python fetch_propublica_990.py search "keyword"
    python fetch_propublica_990.py search --state MA --ntee 3
    python fetch_propublica_990.py org 043318186
    python fetch_propublica_990.py org 043318186 --output results.json

API Documentation: https://projects.propublica.org/nonprofits/api
"""

import argparse
import json
import sys
import urllib.parse
import urllib.request
from typing import Any


API_BASE = "https://projects.propublica.org/nonprofits/api/v2"


def fetch_json(url: str) -> dict[str, Any]:
    """
    Fetch JSON from a URL using urllib.request.

    Args:
        url: Full URL to fetch

    Returns:
        Parsed JSON response as dict

    Raises:
        urllib.error.URLError: On network errors
        json.JSONDecodeError: On invalid JSON response
    """
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "OpenPlanter/1.0 (Investigation Research Tool)",
            "Accept": "application/json",
        }
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        data = response.read()
        return json.loads(data.decode("utf-8"))


def search_organizations(
    query: str | None = None,
    state: str | None = None,
    ntee: str | None = None,
    c_code: str | None = None,
    page: int = 0,
) -> dict[str, Any]:
    """
    Search for nonprofit organizations via ProPublica API.

    Args:
        query: Keyword search (supports quoted phrases, +/- modifiers)
        state: Two-letter state postal code (e.g., "MA", "CA")
        ntee: NTEE major group code (1-10)
        c_code: IRS subsection code (e.g., "3" for 501(c)(3))
        page: Zero-indexed page number (25 results per page)

    Returns:
        API response dict with 'organizations' array and pagination metadata
    """
    params = {}

    if query:
        params["q"] = query
    if state:
        params["state[id]"] = state.upper()
    if ntee:
        params["ntee[id]"] = str(ntee)
    if c_code:
        params["c_code[id]"] = str(c_code)
    if page > 0:
        params["page"] = str(page)

    query_string = urllib.parse.urlencode(params)
    url = f"{API_BASE}/search.json"
    if query_string:
        url += f"?{query_string}"

    return fetch_json(url)


def get_organization(ein: str) -> dict[str, Any]:
    """
    Retrieve complete data for a single organization by EIN.

    Args:
        ein: 9-digit Employer Identification Number (with or without hyphen)

    Returns:
        Organization profile with 'filings' array containing all 990 submissions
    """
    # Strip hyphens and whitespace
    ein_clean = ein.replace("-", "").strip()

    if not ein_clean.isdigit() or len(ein_clean) != 9:
        raise ValueError(f"Invalid EIN format: {ein}. Expected 9 digits.")

    url = f"{API_BASE}/organizations/{ein_clean}.json"
    return fetch_json(url)


def print_search_results(results: dict[str, Any]) -> None:
    """Print formatted search results to stdout."""
    total = results.get("total_results", 0)
    num_pages = results.get("num_pages", 0)
    page = results.get("page", 0)

    print(f"Found {total} organizations ({num_pages} pages, showing page {page})\n")

    orgs = results.get("organizations", [])
    for org in orgs:
        ein = org.get("ein", "N/A")
        name = org.get("name", "Unknown")
        city = org.get("city", "")
        state = org.get("state", "")
        subsection = org.get("subseccd", "")

        location = f"{city}, {state}" if city and state else ""
        subsection_label = f"501(c)({subsection})" if subsection else ""

        print(f"EIN: {ein}")
        print(f"Name: {name}")
        if location:
            print(f"Location: {location}")
        if subsection_label:
            print(f"Type: {subsection_label}")
        print()


def print_organization_profile(org_data: dict[str, Any]) -> None:
    """Print formatted organization profile to stdout."""
    org = org_data.get("organization", {})

    ein = org.get("strein", org.get("ein", "N/A"))
    name = org.get("name", "Unknown")
    address = org.get("address", "")
    city = org.get("city", "")
    state = org.get("state", "")
    zipcode = org.get("zipcode", "")
    subsection = org.get("subsection_code", "")
    ntee = org.get("ntee_code", "")

    print(f"EIN: {ein}")
    print(f"Name: {name}")

    if address:
        full_address = f"{address}, {city}, {state} {zipcode}".strip(", ")
        print(f"Address: {full_address}")

    if subsection:
        print(f"IRS Subsection: 501(c)({subsection})")
    if ntee:
        print(f"NTEE Code: {ntee}")

    filings = org_data.get("filings_with_data", [])
    if filings:
        print(f"\nFilings: {len(filings)} total")
        print("\nRecent filings:")
        for filing in filings[:5]:
            tax_year = filing.get("tax_prd_yr", "N/A")
            form_type = filing.get("formtype", "N/A")
            revenue = filing.get("totrevenue", 0)
            assets = filing.get("totassetsend", 0)

            revenue_str = f"${revenue:,}" if revenue else "N/A"
            assets_str = f"${assets:,}" if assets else "N/A"

            print(f"  {tax_year} - Form {form_type}: Revenue={revenue_str}, Assets={assets_str}")


def main() -> int:
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Fetch nonprofit 990 data from ProPublica Nonprofit Explorer API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Search by keyword
  %(prog)s search "American Red Cross"

  # Search by state
  %(prog)s search --state MA

  # Search by keyword and state
  %(prog)s search "hospital" --state CA

  # Search by NTEE code (3 = Human Services)
  %(prog)s search --ntee 3 --state MA

  # Get organization by EIN
  %(prog)s org 043318186

  # Save organization data to JSON file
  %(prog)s org 043318186 --output redcross.json

  # Get second page of search results
  %(prog)s search "foundation" --page 1
""",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Search command
    search_parser = subparsers.add_parser(
        "search",
        help="Search for organizations by keyword, state, or category",
    )
    search_parser.add_argument(
        "query",
        nargs="?",
        help='Keyword search (use quotes for phrases, + for required terms)',
    )
    search_parser.add_argument(
        "--state",
        help="Two-letter state code (e.g., MA, CA)",
    )
    search_parser.add_argument(
        "--ntee",
        help="NTEE major group code (1-10)",
    )
    search_parser.add_argument(
        "--c-code",
        help="IRS subsection code (e.g., 3 for 501(c)(3))",
    )
    search_parser.add_argument(
        "--page",
        type=int,
        default=0,
        help="Page number (0-indexed, 25 results per page)",
    )
    search_parser.add_argument(
        "--output",
        help="Save raw JSON response to file",
    )

    # Organization command
    org_parser = subparsers.add_parser(
        "org",
        help="Get complete data for a single organization by EIN",
    )
    org_parser.add_argument(
        "ein",
        help="9-digit Employer Identification Number",
    )
    org_parser.add_argument(
        "--output",
        help="Save raw JSON response to file",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    try:
        if args.command == "search":
            if not any([args.query, args.state, args.ntee, args.c_code]):
                search_parser.error("At least one search parameter required")

            results = search_organizations(
                query=args.query,
                state=args.state,
                ntee=args.ntee,
                c_code=args.c_code,
                page=args.page,
            )

            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    json.dump(results, f, indent=2)
                print(f"Results saved to {args.output}")
            else:
                print_search_results(results)

        elif args.command == "org":
            org_data = get_organization(args.ein)

            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    json.dump(org_data, f, indent=2)
                print(f"Organization data saved to {args.output}")
            else:
                print_organization_profile(org_data)

        return 0

    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.reason}", file=sys.stderr)
        if e.code == 404:
            print("Organization not found or API endpoint invalid.", file=sys.stderr)
        return 1

    except urllib.error.URLError as e:
        print(f"Network error: {e.reason}", file=sys.stderr)
        return 1

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    except json.JSONDecodeError as e:
        print(f"Invalid JSON response: {e}", file=sys.stderr)
        return 1

    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

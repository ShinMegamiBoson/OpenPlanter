#!/usr/bin/env python3
"""
USASpending.gov Data Acquisition Script

Fetches federal contract and award data from the USASpending.gov API.
Uses only Python standard library (urllib, json, argparse).

Example usage:
    # Search for contracts by recipient
    python fetch_usaspending.py --recipient "Acme Corporation" --limit 10

    # Search by date range and award type
    python fetch_usaspending.py --start-date 2023-01-01 --end-date 2023-12-31 \
        --award-type contracts --limit 100 --output contracts_2023.json

    # Search by awarding agency
    python fetch_usaspending.py --agency "Department of Defense" --limit 50
"""

import argparse
import json
import sys
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime


API_BASE = "https://api.usaspending.gov/api/v2"
USER_AGENT = "OpenPlanter-USASpending-Fetcher/1.0"


def make_api_request(endpoint, method="GET", data=None):
    """
    Make a request to the USASpending API.

    Args:
        endpoint: API endpoint path (e.g., "/search/spending_by_award/")
        method: HTTP method (GET or POST)
        data: Dictionary to send as JSON body (for POST requests)

    Returns:
        Parsed JSON response as dictionary

    Raises:
        urllib.error.HTTPError: On HTTP error responses
        json.JSONDecodeError: On invalid JSON response
    """
    url = API_BASE + endpoint
    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json"
    }

    if method == "POST" and data:
        json_data = json.dumps(data).encode('utf-8')
        req = urllib.request.Request(url, data=json_data, headers=headers, method="POST")
    else:
        req = urllib.request.Request(url, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            response_data = response.read().decode('utf-8')
            return json.loads(response_data)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else "No error details"
        print(f"HTTP Error {e.code}: {e.reason}", file=sys.stderr)
        print(f"Response: {error_body}", file=sys.stderr)
        raise
    except urllib.error.URLError as e:
        print(f"URL Error: {e.reason}", file=sys.stderr)
        raise


def search_awards(filters, fields, limit=10, page=1, sort="Award Amount", order="desc"):
    """
    Search for awards using the spending_by_award endpoint.

    Args:
        filters: Dictionary of filter criteria (award types, dates, recipients, etc.)
        fields: List of field names to return
        limit: Number of results per page (default 10, max 500)
        page: Page number (1-indexed)
        sort: Field name to sort by
        order: Sort order ("asc" or "desc")

    Returns:
        Dictionary with 'results' list and pagination metadata
    """
    endpoint = "/search/spending_by_award/"

    request_body = {
        "filters": filters,
        "fields": fields,
        "limit": limit,
        "page": page,
        "sort": sort,
        "order": order,
        "subawards": False
    }

    return make_api_request(endpoint, method="POST", data=request_body)


def build_filters(award_types=None, start_date=None, end_date=None, recipient=None, agency=None):
    """
    Build a filters dictionary for the API request.

    Args:
        award_types: List of award type codes (e.g., ["A", "B", "C"] for contracts)
        start_date: Start date string (YYYY-MM-DD)
        end_date: End date string (YYYY-MM-DD)
        recipient: Recipient name search string
        agency: Awarding agency name search string

    Returns:
        Filters dictionary for API request
    """
    filters = {}

    # Award type codes: A=BPA, B=Purchase Order, C=Contract, D=Definitive Contract
    # IDV types: IDV_A through IDV_E
    # Grants: 02-06, Loans: 07-08, etc.
    if award_types:
        filters["award_type_codes"] = award_types

    # Time period filter
    if start_date or end_date:
        time_period = {}
        if start_date:
            time_period["start_date"] = start_date
        if end_date:
            time_period["end_date"] = end_date
        filters["time_period"] = [time_period]

    # Recipient search (searches across all recipients)
    if recipient:
        filters["recipient_search_text"] = [recipient]

    # Agency search
    if agency:
        filters["agencies"] = [{"type": "awarding", "tier": "toptier", "name": agency}]

    return filters


def get_default_fields():
    """Return a standard set of fields for award queries."""
    return [
        "Award ID",
        "Recipient Name",
        "Recipient UEI",
        "Start Date",
        "End Date",
        "Award Amount",
        "Total Outlays",
        "Awarding Agency",
        "Awarding Sub Agency",
        "Award Type",
        "Description",
        "NAICS",
        "PSC",
        "Place of Performance State Code",
        "Place of Performance City Code",
        "Place of Performance Zip5",
        "Last Modified Date"
    ]


def validate_date(date_string):
    """
    Validate date string is in YYYY-MM-DD format.

    Args:
        date_string: Date string to validate

    Returns:
        date_string if valid

    Raises:
        argparse.ArgumentTypeError: If date format is invalid
    """
    try:
        datetime.strptime(date_string, "%Y-%m-%d")
        return date_string
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid date format: {date_string}. Use YYYY-MM-DD.")


def parse_award_type(award_type_string):
    """
    Convert human-readable award type to API codes.

    Args:
        award_type_string: One of "contracts", "grants", "loans", "direct_payments", "other"

    Returns:
        List of award type codes
    """
    type_map = {
        "contracts": ["A", "B", "C", "D"],
        "idvs": ["IDV_A", "IDV_B", "IDV_B_A", "IDV_B_B", "IDV_B_C", "IDV_C", "IDV_D", "IDV_E"],
        "grants": ["02", "03", "04", "05"],
        "loans": ["07", "08"],
        "direct_payments": ["06", "10"],
        "other": ["09", "11"]
    }

    award_type_lower = award_type_string.lower()
    if award_type_lower in type_map:
        return type_map[award_type_lower]
    else:
        raise ValueError(f"Unknown award type: {award_type_string}. Valid types: {', '.join(type_map.keys())}")


def main():
    parser = argparse.ArgumentParser(
        description="Fetch federal spending data from USASpending.gov API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Fetch 10 contracts for a specific recipient
  %(prog)s --recipient "IBM Corporation" --award-type contracts --limit 10

  # Fetch contracts from 2023 fiscal year
  %(prog)s --start-date 2022-10-01 --end-date 2023-09-30 --award-type contracts

  # Search Department of Defense contracts
  %(prog)s --agency "Department of Defense" --award-type contracts --limit 50

Award Types:
  contracts       - Federal procurement contracts (types A, B, C, D)
  idvs           - Indefinite Delivery Vehicles
  grants         - Grant awards
  loans          - Loan awards
  direct_payments - Direct payment awards
  other          - Other financial assistance
        """
    )

    # Search filters
    parser.add_argument("--recipient", type=str, help="Recipient organization name (partial match)")
    parser.add_argument("--agency", type=str, help="Awarding agency name")
    parser.add_argument("--award-type", type=str,
                       help="Award type (contracts, grants, loans, direct_payments, idvs, other)")
    parser.add_argument("--start-date", type=validate_date,
                       help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=validate_date,
                       help="End date (YYYY-MM-DD)")

    # Pagination and output
    parser.add_argument("--limit", type=int, default=10,
                       help="Number of results to return (default: 10, max: 500)")
    parser.add_argument("--page", type=int, default=1,
                       help="Page number for pagination (default: 1)")
    parser.add_argument("--output", type=str,
                       help="Output file path (JSON format). If not specified, prints to stdout")

    # Sorting
    parser.add_argument("--sort", type=str, default="Award Amount",
                       help="Field to sort by (default: 'Award Amount')")
    parser.add_argument("--order", type=str, choices=["asc", "desc"], default="desc",
                       help="Sort order: asc or desc (default: desc)")

    args = parser.parse_args()

    # Validate that at least one filter is specified
    if not any([args.recipient, args.agency, args.award_type, args.start_date, args.end_date]):
        parser.error("At least one filter (--recipient, --agency, --award-type, --start-date, --end-date) is required")

    # Build award type codes
    award_types = None
    if args.award_type:
        try:
            award_types = parse_award_type(args.award_type)
        except ValueError as e:
            parser.error(str(e))

    # Build filters
    filters = build_filters(
        award_types=award_types,
        start_date=args.start_date,
        end_date=args.end_date,
        recipient=args.recipient,
        agency=args.agency
    )

    # Get default fields
    fields = get_default_fields()

    try:
        print(f"Searching USASpending.gov with filters: {json.dumps(filters, indent=2)}", file=sys.stderr)

        # Make the API request
        response = search_awards(
            filters=filters,
            fields=fields,
            limit=args.limit,
            page=args.page,
            sort=args.sort,
            order=args.order
        )

        # Extract results
        results = response.get("results", [])
        page_metadata = response.get("page_metadata", {})

        print(f"\nFound {page_metadata.get('total', 0)} total results", file=sys.stderr)
        print(f"Showing page {args.page} ({len(results)} results)\n", file=sys.stderr)

        # Prepare output
        output_data = {
            "metadata": {
                "query_date": datetime.utcnow().isoformat() + "Z",
                "filters": filters,
                "total_results": page_metadata.get("total", 0),
                "page": args.page,
                "limit": args.limit,
                "num_results": len(results)
            },
            "results": results
        }

        # Write output
        output_json = json.dumps(output_data, indent=2)

        if args.output:
            with open(args.output, 'w') as f:
                f.write(output_json)
            print(f"Results written to {args.output}", file=sys.stderr)
        else:
            print(output_json)

        return 0

    except urllib.error.HTTPError as e:
        print(f"\nAPI request failed with HTTP {e.code}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

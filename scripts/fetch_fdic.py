#!/usr/bin/env python3
"""
FDIC BankFind Suite API Client

Fetch data from the FDIC BankFind API for institutions, failures, locations,
history, summary, and financials. Uses only Python standard library.

Usage:
    python fetch_fdic.py institutions --limit 10
    python fetch_fdic.py failures --filter "FAILDATE:[2020-01-01 TO *]"
    python fetch_fdic.py locations --filter "CERT:14" --fields "NAME,CITY,STALP"
    python fetch_fdic.py history --offset 100 --limit 50
    python fetch_fdic.py summary --filter "STNAME:Massachusetts"
    python fetch_fdic.py financials --filter "CERT:14" --limit 4

For more information, see: wiki/financial/fdic-bankfind.md
"""

import argparse
import json
import sys
import urllib.request
import urllib.parse
import urllib.error


BASE_URL = "https://api.fdic.gov/banks"

ENDPOINTS = {
    "institutions": "/institutions",
    "failures": "/failures",
    "locations": "/locations",
    "history": "/history",
    "summary": "/summary",
    "financials": "/financials"
}


def build_url(endpoint, filters=None, fields=None, limit=None, offset=None,
              sort_by=None, sort_order=None, output_format="json"):
    """
    Build FDIC API URL with query parameters.

    Args:
        endpoint: One of ENDPOINTS keys
        filters: Elasticsearch query string (e.g., "STALP:MA AND ACTIVE:1")
        fields: Comma-separated field list
        limit: Max records to return (default 10, max 10000)
        offset: Pagination offset
        sort_by: Field name to sort on
        sort_order: "ASC" or "DESC"
        output_format: "json" or "csv"

    Returns:
        Full URL with encoded query parameters
    """
    if endpoint not in ENDPOINTS:
        raise ValueError(f"Invalid endpoint: {endpoint}. Choose from {list(ENDPOINTS.keys())}")

    url = BASE_URL + ENDPOINTS[endpoint]
    params = {}

    if filters:
        params["filters"] = filters
    if fields:
        params["fields"] = fields
    if limit is not None:
        params["limit"] = str(limit)
    if offset is not None:
        params["offset"] = str(offset)
    if sort_by:
        params["sort_by"] = sort_by
    if sort_order:
        params["sort_order"] = sort_order
    if output_format:
        params["format"] = output_format

    if params:
        url += "?" + urllib.parse.urlencode(params, safe=":[]")

    return url


def fetch_fdic(endpoint, filters=None, fields=None, limit=None, offset=None,
               sort_by=None, sort_order=None, output_format="json"):
    """
    Fetch data from FDIC BankFind API.

    Args:
        endpoint: API endpoint name
        filters: Filter string
        fields: Field selection
        limit: Max records
        offset: Pagination offset
        sort_by: Sort field
        sort_order: Sort direction
        output_format: Response format

    Returns:
        Parsed JSON dict or CSV string

    Raises:
        urllib.error.HTTPError: On HTTP errors
        urllib.error.URLError: On network errors
        json.JSONDecodeError: On invalid JSON (if format=json)
    """
    url = build_url(endpoint, filters, fields, limit, offset, sort_by,
                    sort_order, output_format)

    print(f"Fetching: {url}", file=sys.stderr)

    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            content = response.read()

            if output_format == "json":
                return json.loads(content)
            else:
                return content.decode("utf-8")

    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.reason}", file=sys.stderr)
        print(f"URL: {url}", file=sys.stderr)
        try:
            error_body = e.read().decode("utf-8")
            print(f"Response: {error_body}", file=sys.stderr)
        except:
            pass
        raise

    except urllib.error.URLError as e:
        print(f"URL Error: {e.reason}", file=sys.stderr)
        raise


def print_results(data, output_format="json", pretty=True):
    """
    Print API results to stdout.

    Args:
        data: Response data (dict or string)
        output_format: "json" or "csv"
        pretty: Pretty-print JSON if True
    """
    if output_format == "json":
        if pretty:
            print(json.dumps(data, indent=2))
        else:
            print(json.dumps(data))
    else:
        # CSV is already a string
        print(data)


def main():
    parser = argparse.ArgumentParser(
        description="Fetch data from FDIC BankFind Suite API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Get 10 active banks in Massachusetts
  %(prog)s institutions --filter "STALP:MA AND ACTIVE:1" --limit 10

  # Get recent bank failures
  %(prog)s failures --filter "FAILDATE:[2020-01-01 TO *]" --limit 50

  # Get all branches for a specific bank (CERT=14)
  %(prog)s locations --filter "CERT:14" --limit 500

  # Get specific fields only
  %(prog)s institutions --fields "NAME,CITY,STALP,CERT" --limit 5

  # Paginate through results
  %(prog)s history --limit 100 --offset 200

  # Get CSV output
  %(prog)s institutions --format csv --limit 5

Filter syntax (Elasticsearch query string):
  - Field match: STALP:MA
  - Boolean: STALP:MA AND ACTIVE:1
  - Phrase: NAME:"First Bank"
  - Exclusion: !(STNAME:"Virginia")
  - Date range: FAILDATE:[2020-01-01 TO 2023-12-31]
  - Numeric range: DEP:[50000 TO *]  (deposits > 50M, in thousands)
  - Wildcard: NAME:First*

Available endpoints:
  institutions  - Institution profiles and regulatory data
  failures      - Failed institutions since 1934
  locations     - Branch and office locations
  history       - Structure change events (mergers, acquisitions)
  summary       - Aggregate financial data by year
  financials    - Detailed quarterly Call Report data

See wiki/financial/fdic-bankfind.md for full documentation.
        """
    )

    parser.add_argument(
        "endpoint",
        choices=list(ENDPOINTS.keys()),
        help="API endpoint to query"
    )

    parser.add_argument(
        "--filter", "-f",
        dest="filters",
        help="Elasticsearch query string filter"
    )

    parser.add_argument(
        "--fields",
        help="Comma-separated list of fields to return (default: all)"
    )

    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=10,
        help="Maximum number of records to return (default: 10, max: 10000)"
    )

    parser.add_argument(
        "--offset", "-o",
        type=int,
        default=0,
        help="Pagination offset (default: 0)"
    )

    parser.add_argument(
        "--sort-by",
        help="Field name to sort by"
    )

    parser.add_argument(
        "--sort-order",
        choices=["ASC", "DESC"],
        help="Sort order (ASC or DESC)"
    )

    parser.add_argument(
        "--format",
        choices=["json", "csv"],
        default="json",
        help="Output format (default: json)"
    )

    parser.add_argument(
        "--compact",
        action="store_true",
        help="Compact JSON output (no pretty printing)"
    )

    args = parser.parse_args()

    try:
        data = fetch_fdic(
            endpoint=args.endpoint,
            filters=args.filters,
            fields=args.fields,
            limit=args.limit,
            offset=args.offset,
            sort_by=args.sort_by,
            sort_order=args.sort_order,
            output_format=args.format
        )

        print_results(data, args.format, pretty=not args.compact)

        # Print summary stats to stderr for JSON responses
        if args.format == "json" and isinstance(data, dict):
            meta = data.get("meta", {})
            total = meta.get("total", "unknown")
            returned = len(data.get("data", []))
            print(f"\nReturned {returned} of {total} total records", file=sys.stderr)

        return 0

    except KeyboardInterrupt:
        print("\nInterrupted by user", file=sys.stderr)
        return 130

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

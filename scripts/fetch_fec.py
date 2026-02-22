#!/usr/bin/env python3
"""
FEC Federal Campaign Finance Data Fetcher

Downloads campaign finance data from the Federal Election Commission via:
- OpenFEC API (api.open.fec.gov/v1/)
- Bulk data downloads (fec.gov)

Uses only Python standard library (urllib, json, csv).
"""

import argparse
import csv
import json
import sys
import urllib.request
import urllib.parse
import urllib.error
from typing import Dict, List, Any, Optional


# API Configuration
API_BASE = "https://api.open.fec.gov/v1"
DEFAULT_API_KEY = "DEMO_KEY"  # Low rate limit; get free key at api.data.gov


class FECAPIClient:
    """Simple FEC API client using urllib."""

    def __init__(self, api_key: str = DEFAULT_API_KEY):
        self.api_key = api_key
        self.base_url = API_BASE

    def _build_url(self, endpoint: str, params: Dict[str, Any]) -> str:
        """Build full URL with query parameters."""
        params['api_key'] = self.api_key
        # Filter out None values
        params = {k: v for k, v in params.items() if v is not None}
        query_string = urllib.parse.urlencode(params)
        return f"{self.base_url}/{endpoint}/?{query_string}"

    def _request(self, url: str) -> Dict[str, Any]:
        """Make HTTP GET request and return parsed JSON."""
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                data = response.read()
                return json.loads(data.decode('utf-8'))
        except urllib.error.HTTPError as e:
            print(f"HTTP Error {e.code}: {e.reason}", file=sys.stderr)
            print(f"URL: {url}", file=sys.stderr)
            if e.code == 403:
                print("Hint: Check your API key or try a different endpoint", file=sys.stderr)
            raise
        except urllib.error.URLError as e:
            print(f"URL Error: {e.reason}", file=sys.stderr)
            raise

    def get_candidates(
        self,
        cycle: Optional[int] = None,
        office: Optional[str] = None,
        state: Optional[str] = None,
        page: int = 1,
        per_page: int = 20
    ) -> Dict[str, Any]:
        """
        Get candidates list.

        Args:
            cycle: Election cycle year (e.g., 2024)
            office: Office type (H=House, S=Senate, P=President)
            state: Two-letter state code
            page: Page number (1-indexed)
            per_page: Results per page (max 100)
        """
        params = {
            'cycle': cycle,
            'office': office,
            'state': state,
            'page': page,
            'per_page': per_page
        }
        url = self._build_url('candidates', params)
        return self._request(url)

    def get_committees(
        self,
        cycle: Optional[int] = None,
        committee_type: Optional[str] = None,
        page: int = 1,
        per_page: int = 20
    ) -> Dict[str, Any]:
        """
        Get committees list.

        Args:
            cycle: Election cycle year
            committee_type: Committee type (H, S, P, X, Y, Z, etc.)
            page: Page number
            per_page: Results per page
        """
        params = {
            'cycle': cycle,
            'committee_type': committee_type,
            'page': page,
            'per_page': per_page
        }
        url = self._build_url('committees', params)
        return self._request(url)

    def get_schedule_a(
        self,
        cycle: Optional[int] = None,
        committee_id: Optional[str] = None,
        min_amount: Optional[float] = None,
        max_amount: Optional[float] = None,
        page: int = 1,
        per_page: int = 20
    ) -> Dict[str, Any]:
        """
        Get Schedule A (contributions) data.

        Args:
            cycle: Election cycle year
            committee_id: Committee ID filter
            min_amount: Minimum contribution amount
            max_amount: Maximum contribution amount
            page: Page number
            per_page: Results per page
        """
        params = {
            'two_year_transaction_period': cycle,
            'committee_id': committee_id,
            'min_amount': min_amount,
            'max_amount': max_amount,
            'page': page,
            'per_page': per_page
        }
        url = self._build_url('schedules/schedule_a', params)
        return self._request(url)

    def get_totals(
        self,
        candidate_id: str,
        cycle: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get candidate financial totals.

        Args:
            candidate_id: FEC candidate ID
            cycle: Election cycle year
        """
        params = {'cycle': cycle}
        url = self._build_url(f'candidate/{candidate_id}/totals', params)
        return self._request(url)


def fetch_all_pages(
    client: FECAPIClient,
    endpoint_method: callable,
    max_pages: int = 10,
    **kwargs
) -> List[Dict[str, Any]]:
    """
    Fetch multiple pages from an API endpoint.

    Args:
        client: FECAPIClient instance
        endpoint_method: Client method to call (e.g., client.get_candidates)
        max_pages: Maximum pages to fetch (safety limit)
        **kwargs: Parameters to pass to endpoint method

    Returns:
        List of all results across pages
    """
    all_results = []
    page = 1

    while page <= max_pages:
        try:
            response = endpoint_method(page=page, **kwargs)
            results = response.get('results', [])

            if not results:
                break

            all_results.extend(results)

            pagination = response.get('pagination', {})
            total_pages = pagination.get('pages', 1)

            print(f"Fetched page {page}/{total_pages} ({len(results)} records)", file=sys.stderr)

            if page >= total_pages:
                break

            page += 1

        except Exception as e:
            print(f"Error fetching page {page}: {e}", file=sys.stderr)
            break

    return all_results


def output_json(data: List[Dict[str, Any]], output_file: Optional[str] = None):
    """Output data as JSON."""
    output = json.dumps(data, indent=2)
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(output)
        print(f"Wrote {len(data)} records to {output_file}", file=sys.stderr)
    else:
        print(output)


def output_csv(data: List[Dict[str, Any]], output_file: Optional[str] = None):
    """Output data as CSV."""
    if not data:
        print("No data to write", file=sys.stderr)
        return

    # Get all unique field names
    fieldnames = set()
    for record in data:
        fieldnames.update(record.keys())
    fieldnames = sorted(fieldnames)

    output = sys.stdout if output_file is None else open(output_file, 'w', encoding='utf-8', newline='')

    try:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)

        if output_file:
            print(f"Wrote {len(data)} records to {output_file}", file=sys.stderr)
    finally:
        if output_file:
            output.close()


def main():
    parser = argparse.ArgumentParser(
        description='Fetch FEC federal campaign finance data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Get 2024 House candidates from Massachusetts
  %(prog)s --endpoint candidates --cycle 2024 --office H --state MA

  # Get contributions to a specific committee
  %(prog)s --endpoint schedule_a --committee C00401224 --per-page 100

  # Get all committees, output as CSV
  %(prog)s --endpoint committees --format csv --output committees.csv

  # Get candidate financial totals (requires candidate ID)
  %(prog)s --endpoint totals --candidate P80001571 --cycle 2024

Environment:
  FEC_API_KEY: Set to use custom API key (default: DEMO_KEY)
        """
    )

    parser.add_argument(
        '--endpoint',
        required=True,
        choices=['candidates', 'committees', 'schedule_a', 'totals'],
        help='API endpoint to query'
    )

    parser.add_argument(
        '--api-key',
        default=DEFAULT_API_KEY,
        help=f'FEC API key (default: {DEFAULT_API_KEY})'
    )

    parser.add_argument(
        '--cycle',
        type=int,
        help='Election cycle year (e.g., 2024)'
    )

    parser.add_argument(
        '--office',
        choices=['H', 'S', 'P'],
        help='Office type: H=House, S=Senate, P=President'
    )

    parser.add_argument(
        '--state',
        help='Two-letter state code (e.g., MA)'
    )

    parser.add_argument(
        '--committee',
        help='Committee ID (e.g., C00401224)'
    )

    parser.add_argument(
        '--committee-type',
        help='Committee type code'
    )

    parser.add_argument(
        '--candidate',
        help='Candidate ID for totals endpoint (e.g., P80001571)'
    )

    parser.add_argument(
        '--min-amount',
        type=float,
        help='Minimum contribution amount (schedule_a only)'
    )

    parser.add_argument(
        '--max-amount',
        type=float,
        help='Maximum contribution amount (schedule_a only)'
    )

    parser.add_argument(
        '--per-page',
        type=int,
        default=20,
        help='Results per page (default: 20, max: 100)'
    )

    parser.add_argument(
        '--max-pages',
        type=int,
        default=10,
        help='Maximum pages to fetch (default: 10)'
    )

    parser.add_argument(
        '--format',
        choices=['json', 'csv'],
        default='json',
        help='Output format (default: json)'
    )

    parser.add_argument(
        '--output',
        help='Output file path (default: stdout)'
    )

    args = parser.parse_args()

    # Initialize client
    client = FECAPIClient(api_key=args.api_key)

    # Route to appropriate endpoint
    try:
        if args.endpoint == 'candidates':
            results = fetch_all_pages(
                client,
                client.get_candidates,
                max_pages=args.max_pages,
                cycle=args.cycle,
                office=args.office,
                state=args.state,
                per_page=args.per_page
            )

        elif args.endpoint == 'committees':
            results = fetch_all_pages(
                client,
                client.get_committees,
                max_pages=args.max_pages,
                cycle=args.cycle,
                committee_type=args.committee_type,
                per_page=args.per_page
            )

        elif args.endpoint == 'schedule_a':
            results = fetch_all_pages(
                client,
                client.get_schedule_a,
                max_pages=args.max_pages,
                cycle=args.cycle,
                committee_id=args.committee,
                min_amount=args.min_amount,
                max_amount=args.max_amount,
                per_page=args.per_page
            )

        elif args.endpoint == 'totals':
            if not args.candidate:
                print("Error: --candidate required for totals endpoint", file=sys.stderr)
                sys.exit(1)
            response = client.get_totals(args.candidate, cycle=args.cycle)
            results = response.get('results', [])

        else:
            print(f"Unknown endpoint: {args.endpoint}", file=sys.stderr)
            sys.exit(1)

        # Output results
        if args.format == 'json':
            output_json(results, args.output)
        else:
            output_csv(results, args.output)

    except KeyboardInterrupt:
        print("\nInterrupted by user", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()

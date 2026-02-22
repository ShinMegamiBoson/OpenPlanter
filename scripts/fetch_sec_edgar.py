#!/usr/bin/env python3
"""
SEC EDGAR Data Fetcher

Fetches company submissions and filing data from the SEC EDGAR API using only
Python standard library. Supports lookup by ticker symbol or CIK number.

Usage:
    python fetch_sec_edgar.py --ticker AAPL
    python fetch_sec_edgar.py --cik 0000320193
    python fetch_sec_edgar.py --ticker MSFT --output msft_filings.json
    python fetch_sec_edgar.py --list-tickers --limit 10
"""

import argparse
import json
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


# SEC requires a User-Agent header to identify automated requests
USER_AGENT = "OpenPlanter edgar-fetcher/1.0 (research@openplanter.org)"

# Base URLs for SEC EDGAR API
TICKER_LOOKUP_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_BASE_URL = "https://data.sec.gov/submissions/"


def fetch_json(url, headers=None):
    """
    Fetch JSON data from a URL using urllib.

    Args:
        url: The URL to fetch
        headers: Optional dict of HTTP headers

    Returns:
        Parsed JSON response as dict/list

    Raises:
        HTTPError: If the server returns an error status
        URLError: If there's a network problem
    """
    if headers is None:
        headers = {}

    # Always include User-Agent
    headers["User-Agent"] = USER_AGENT

    request = Request(url, headers=headers)

    try:
        with urlopen(request, timeout=30) as response:
            data = response.read()
            return json.loads(data.decode('utf-8'))
    except HTTPError as e:
        print(f"HTTP Error {e.code}: {e.reason}", file=sys.stderr)
        print(f"URL: {url}", file=sys.stderr)
        if e.code == 403:
            print("Note: SEC may have rate-limited this IP. Wait a moment and try again.", file=sys.stderr)
        raise
    except URLError as e:
        print(f"Network error: {e.reason}", file=sys.stderr)
        raise
    except json.JSONDecodeError as e:
        print(f"Failed to parse JSON response: {e}", file=sys.stderr)
        raise


def get_ticker_to_cik_mapping():
    """
    Fetch the complete ticker-to-CIK mapping from SEC.

    Returns:
        Dict mapping ticker symbols (uppercase) to CIK numbers (integers)
    """
    print("Fetching ticker-to-CIK mapping from SEC...", file=sys.stderr)
    data = fetch_json(TICKER_LOOKUP_URL)

    # SEC returns a dict with numeric keys like "0", "1", etc.
    # Each entry has "cik_str", "ticker", and "title"
    mapping = {}
    for entry in data.values():
        ticker = entry["ticker"].upper()
        cik = entry["cik_str"]
        mapping[ticker] = cik

    return mapping


def format_cik(cik):
    """
    Format CIK as 10-digit string with leading zeros.

    Args:
        cik: CIK as string or integer

    Returns:
        10-digit CIK string with leading zeros
    """
    return str(cik).zfill(10)


def get_company_submissions(cik):
    """
    Fetch complete filing history and metadata for a company.

    Args:
        cik: Company CIK (string or integer)

    Returns:
        Dict containing company metadata and filing history
    """
    cik_formatted = format_cik(cik)
    url = f"{SUBMISSIONS_BASE_URL}CIK{cik_formatted}.json"

    print(f"Fetching submissions for CIK {cik_formatted}...", file=sys.stderr)
    return fetch_json(url)


def print_company_summary(data):
    """
    Print a human-readable summary of company data.

    Args:
        data: Company submissions JSON from SEC API
    """
    print("\n" + "=" * 70)
    print(f"Company: {data.get('name', 'N/A')}")
    print(f"CIK: {data.get('cik', 'N/A')}")
    print(f"SIC: {data.get('sic', 'N/A')} - {data.get('sicDescription', 'N/A')}")
    print(f"Fiscal Year End: {data.get('fiscalYearEnd', 'N/A')}")

    if data.get('tickers'):
        print(f"Tickers: {', '.join(data['tickers'])}")
    if data.get('exchanges'):
        print(f"Exchanges: {', '.join(data['exchanges'])}")

    # Show recent filings
    if 'filings' in data and 'recent' in data['filings']:
        recent = data['filings']['recent']
        num_filings = len(recent.get('accessionNumber', []))
        print(f"\nTotal recent filings: {num_filings}")

        if num_filings > 0:
            print("\nMost recent filings:")
            print(f"{'Form':<12} {'Filing Date':<12} {'Report Date':<12} {'Accession Number'}")
            print("-" * 70)

            # Show up to 10 most recent
            for i in range(min(10, num_filings)):
                form = recent['form'][i]
                filing_date = recent['filingDate'][i]
                report_date = recent.get('reportDate', [''] * num_filings)[i]
                accession = recent['accessionNumber'][i]
                print(f"{form:<12} {filing_date:<12} {report_date:<12} {accession}")

    print("=" * 70 + "\n")


def list_tickers(limit=None):
    """
    List all available ticker symbols from SEC.

    Args:
        limit: Optional max number of tickers to display
    """
    mapping = get_ticker_to_cik_mapping()

    tickers = sorted(mapping.keys())
    if limit:
        tickers = tickers[:limit]

    print(f"\n{'Ticker':<10} {'CIK':<15}")
    print("-" * 25)
    for ticker in tickers:
        print(f"{ticker:<10} {mapping[ticker]:<15}")

    total = len(mapping)
    if limit and limit < total:
        print(f"\n(Showing {limit} of {total} total tickers)")
    else:
        print(f"\nTotal tickers: {total}")


def main():
    parser = argparse.ArgumentParser(
        description="Fetch SEC EDGAR company filings and metadata",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --ticker AAPL
  %(prog)s --cik 0000320193
  %(prog)s --ticker MSFT --output msft_filings.json
  %(prog)s --list-tickers --limit 20

Rate Limits:
  SEC limits automated requests to 10 per second. This script includes
  a small delay between requests to stay under the limit.

User-Agent:
  All requests include the User-Agent header: {user_agent}
  This identifies the source of automated requests to the SEC.
        """.format(user_agent=USER_AGENT)
    )

    parser.add_argument(
        "--ticker",
        help="Stock ticker symbol (e.g., AAPL, MSFT)"
    )

    parser.add_argument(
        "--cik",
        help="Company CIK number (with or without leading zeros)"
    )

    parser.add_argument(
        "--output",
        help="Write JSON output to file instead of stdout"
    )

    parser.add_argument(
        "--list-tickers",
        action="store_true",
        help="List all available ticker symbols"
    )

    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of results (for --list-tickers)"
    )

    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output (default: compact)"
    )

    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print human-readable summary instead of raw JSON"
    )

    args = parser.parse_args()

    # Validate arguments
    if args.list_tickers:
        list_tickers(limit=args.limit)
        return 0

    if not args.ticker and not args.cik:
        parser.error("Must specify either --ticker or --cik (or use --list-tickers)")

    if args.ticker and args.cik:
        parser.error("Cannot specify both --ticker and --cik")

    try:
        # Look up CIK from ticker if needed
        if args.ticker:
            ticker = args.ticker.upper()
            print(f"Looking up CIK for ticker {ticker}...", file=sys.stderr)
            mapping = get_ticker_to_cik_mapping()

            if ticker not in mapping:
                print(f"Error: Ticker '{ticker}' not found in SEC database", file=sys.stderr)
                return 1

            cik = mapping[ticker]
            print(f"Found CIK: {cik}", file=sys.stderr)
        else:
            cik = args.cik

        # Small delay to respect rate limits (10 req/sec = 100ms between requests)
        time.sleep(0.15)

        # Fetch company submissions
        data = get_company_submissions(cik)

        # Output results
        if args.summary:
            print_company_summary(data)
        else:
            if args.output:
                with open(args.output, 'w') as f:
                    if args.pretty:
                        json.dump(data, f, indent=2)
                    else:
                        json.dump(data, f)
                print(f"Output written to {args.output}", file=sys.stderr)
            else:
                if args.pretty:
                    print(json.dumps(data, indent=2))
                else:
                    print(json.dumps(data))

        return 0

    except (HTTPError, URLError) as e:
        print(f"\nFailed to fetch data from SEC: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted by user", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"\nUnexpected error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

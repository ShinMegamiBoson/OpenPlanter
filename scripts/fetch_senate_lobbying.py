#!/usr/bin/env python3
"""
Senate Lobbying Disclosure Fetcher

Downloads quarterly lobbying disclosure XML files from the Senate Office
of Public Records (SOPR). Data includes LD-1 registrations, LD-2 quarterly
activity reports, and LD-203 contribution reports.

Usage:
    python fetch_senate_lobbying.py --year 2024 --quarter 4 --output data/lobbying/
    python fetch_senate_lobbying.py --year 2023 --quarter 1 --output data/lobbying/ --verbose

Requirements:
    Python 3.7+ with stdlib only (no third-party dependencies)

Data source:
    http://soprweb.senate.gov/downloads/{YEAR}_{QUARTER}.zip
"""

import argparse
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path


def download_lobbying_data(year: int, quarter: int, output_dir: Path, verbose: bool = False) -> bool:
    """
    Download Senate lobbying disclosure data for a given year and quarter.

    Args:
        year: Year (1999-present)
        quarter: Quarter (1-4)
        output_dir: Directory to save the ZIP file
        verbose: Print progress messages

    Returns:
        True if download succeeded, False otherwise
    """
    # Validate inputs
    if quarter < 1 or quarter > 4:
        print(f"Error: Quarter must be 1-4, got {quarter}", file=sys.stderr)
        return False

    if year < 1999 or year > 2030:
        print(f"Error: Year {year} outside expected range (1999-2030)", file=sys.stderr)
        return False

    # Construct URL
    base_url = "http://soprweb.senate.gov/downloads"
    filename = f"{year}_{quarter}.zip"
    url = f"{base_url}/{filename}"

    # Prepare output path
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename

    if verbose:
        print(f"Downloading {url}")
        print(f"Saving to {output_path}")

    try:
        # Download with progress
        with urllib.request.urlopen(url, timeout=30) as response:
            # Check if successful
            if response.status != 200:
                print(f"Error: HTTP {response.status} from {url}", file=sys.stderr)
                return False

            # Get file size if available
            content_length = response.headers.get('Content-Length')
            total_size = int(content_length) if content_length else None

            # Download in chunks
            chunk_size = 8192
            downloaded = 0

            with open(output_path, 'wb') as f:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)

                    if verbose and total_size:
                        percent = (downloaded / total_size) * 100
                        print(f"\rProgress: {downloaded:,} / {total_size:,} bytes ({percent:.1f}%)", end='')

            if verbose:
                print()  # New line after progress
                print(f"Download complete: {output_path} ({downloaded:,} bytes)")

        return True

    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"Error: Data not found for {year} Q{quarter}. URL: {url}", file=sys.stderr)
            print("Note: Data may not be available yet or year/quarter may be invalid.", file=sys.stderr)
        else:
            print(f"Error: HTTP {e.code} {e.reason} from {url}", file=sys.stderr)
        return False

    except urllib.error.URLError as e:
        print(f"Error: Network error - {e.reason}", file=sys.stderr)
        return False

    except OSError as e:
        print(f"Error: File system error - {e}", file=sys.stderr)
        return False

    except Exception as e:
        print(f"Error: Unexpected error - {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Download Senate lobbying disclosure data (LD-1/LD-2/LD-203)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download 2024 Q4 data to data/lobbying/
  python fetch_senate_lobbying.py --year 2024 --quarter 4 --output data/lobbying/

  # Download 2023 Q1 with verbose output
  python fetch_senate_lobbying.py --year 2023 --quarter 1 --output data/lobbying/ --verbose

  # Download current year Q1 to current directory
  python fetch_senate_lobbying.py --year 2026 --quarter 1 --output .

Data source: http://soprweb.senate.gov/downloads/
Coverage: 1999 Q1 - present
        """
    )

    parser.add_argument(
        '--year',
        type=int,
        required=True,
        help='Year (1999-present)'
    )

    parser.add_argument(
        '--quarter',
        type=int,
        required=True,
        choices=[1, 2, 3, 4],
        help='Quarter (1-4)'
    )

    parser.add_argument(
        '--output',
        type=str,
        default='data/lobbying',
        help='Output directory (default: data/lobbying)'
    )

    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Print progress messages'
    )

    args = parser.parse_args()

    # Convert output to Path
    output_dir = Path(args.output)

    # Download
    success = download_lobbying_data(args.year, args.quarter, output_dir, args.verbose)

    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()

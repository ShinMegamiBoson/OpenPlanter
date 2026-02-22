#!/usr/bin/env python3
"""
OFAC SDN List Acquisition Script

Downloads all four OFAC SDN legacy CSV files from Treasury.gov:
- sdn.csv: Primary SDN records
- add.csv: Addresses
- alt.csv: Aliases
- sdn_comments.csv: Remarks overflow

All files must be downloaded together and joined on ent_num for complete data.

Usage:
    python fetch_ofac_sdn.py --output-dir ./data/ofac
    python fetch_ofac_sdn.py --help
"""

import argparse
import csv
import sys
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, List


BASE_URL = "https://www.treasury.gov/ofac/downloads/"

FILES = {
    "sdn": {
        "filename": "sdn.csv",
        "description": "Primary SDN records",
        "expected_fields": ["ent_num", "SDN_Name", "SDN_Type", "Program", "Title",
                          "Call_Sign", "Vess_type", "Tonnage", "GRT", "Vess_flag",
                          "Vess_owner", "Remarks"]
    },
    "add": {
        "filename": "add.csv",
        "description": "Address records",
        "expected_fields": ["Ent_num", "Add_num", "Address", "City/State/Province/Postal Code",
                          "Country", "Add_remarks"]
    },
    "alt": {
        "filename": "alt.csv",
        "description": "Alias records",
        "expected_fields": ["ent_num", "alt_num", "alt_type", "alt_name", "alt_remarks"]
    },
    "comments": {
        "filename": "sdn_comments.csv",
        "description": "Remarks overflow",
        "expected_fields": []  # May not exist or have varying schema
    }
}


def download_file(url: str, output_path: Path, verbose: bool = True) -> bool:
    """
    Download a file from URL to output_path using urllib.

    Args:
        url: Full URL to download
        output_path: Destination file path
        verbose: Print progress messages

    Returns:
        True if successful, False otherwise
    """
    try:
        if verbose:
            print(f"Downloading {url}...")

        # Create a request with a user agent to avoid 403 errors
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (compatible; OpenPlanter OFAC fetcher)'}
        )

        with urllib.request.urlopen(req, timeout=30) as response:
            content = response.read()

        # Write to file
        output_path.write_bytes(content)

        if verbose:
            size_kb = len(content) / 1024
            print(f"  ✓ Downloaded {size_kb:.1f} KB to {output_path}")

        return True

    except urllib.error.HTTPError as e:
        print(f"  ✗ HTTP Error {e.code}: {e.reason}", file=sys.stderr)
        return False
    except urllib.error.URLError as e:
        print(f"  ✗ URL Error: {e.reason}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"  ✗ Error: {e}", file=sys.stderr)
        return False


def validate_csv_schema(file_path: Path, expected_fields: List[str], verbose: bool = True) -> bool:
    """
    Validate that a CSV file has the expected number of fields.

    Note: OFAC SDN CSV files have NO header row, so this validates field count only.

    Args:
        file_path: Path to CSV file
        expected_fields: List of expected field names (used for count validation)
        verbose: Print validation messages

    Returns:
        True if field count matches or expected_fields is empty, False otherwise
    """
    if not expected_fields:
        if verbose:
            print(f"  → Skipping schema validation for {file_path.name}")
        return True

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            first_row = next(reader)

        expected_count = len(expected_fields)
        actual_count = len(first_row)

        if actual_count != expected_count:
            print(f"  ✗ Field count mismatch: expected {expected_count}, got {actual_count}", file=sys.stderr)
            return False

        if verbose:
            print(f"  ✓ Schema validated: {actual_count} fields (no header)")

        return True

    except Exception as e:
        print(f"  ✗ Validation error: {e}", file=sys.stderr)
        return False


def count_csv_records(file_path: Path, verbose: bool = True) -> int:
    """
    Count records in a CSV file.

    Note: OFAC SDN CSV files have NO header row, so all rows are counted.

    Args:
        file_path: Path to CSV file
        verbose: Print record count

    Returns:
        Number of records, or -1 on error
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            count = sum(1 for _ in reader)

        if verbose:
            print(f"  → {count:,} records")

        return count

    except Exception as e:
        print(f"  ✗ Count error: {e}", file=sys.stderr)
        return -1


def fetch_ofac_sdn(output_dir: Path, verbose: bool = True, validate: bool = True) -> Dict[str, bool]:
    """
    Download all OFAC SDN CSV files.

    Args:
        output_dir: Directory to save files
        verbose: Print progress messages
        validate: Validate CSV schemas after download

    Returns:
        Dict mapping file keys to success status
    """
    results = {}

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    if verbose:
        print(f"Fetching OFAC SDN files to: {output_dir.absolute()}\n")

    # Download each file
    for key, info in FILES.items():
        url = BASE_URL + info["filename"]
        output_path = output_dir / info["filename"]

        if verbose:
            print(f"{info['description']} ({info['filename']}):")

        success = download_file(url, output_path, verbose=verbose)
        results[key] = success

        if success and validate:
            # Validate schema
            validate_csv_schema(output_path, info["expected_fields"], verbose=verbose)
            # Count records
            count_csv_records(output_path, verbose=verbose)

        if verbose:
            print()

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Download OFAC SDN List CSV files from Treasury.gov",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download to ./data/ofac directory
  python fetch_ofac_sdn.py --output-dir ./data/ofac

  # Download without validation
  python fetch_ofac_sdn.py --output-dir ./ofac --no-validate

  # Quiet mode (errors only)
  python fetch_ofac_sdn.py --output-dir ./ofac --quiet

Files downloaded:
  - sdn.csv: Primary SDN records (names, programs, types)
  - add.csv: Addresses linked via ent_num
  - alt.csv: Aliases (AKA, FKA, NKA) linked via ent_num
  - sdn_comments.csv: Remarks overflow data

All four files must be joined in a relational database for complete data.
        """
    )

    parser.add_argument(
        '--output-dir',
        type=Path,
        default=Path('./data/ofac'),
        help='Directory to save downloaded files (default: ./data/ofac)'
    )

    parser.add_argument(
        '--no-validate',
        action='store_true',
        help='Skip CSV schema validation after download'
    )

    parser.add_argument(
        '--quiet',
        action='store_true',
        help='Suppress progress messages (errors only)'
    )

    args = parser.parse_args()

    # Download files
    results = fetch_ofac_sdn(
        output_dir=args.output_dir,
        verbose=not args.quiet,
        validate=not args.no_validate
    )

    # Summary
    successful = sum(1 for v in results.values() if v)
    total = len(results)

    if not args.quiet:
        print(f"{'='*60}")
        print(f"Download complete: {successful}/{total} files successful")

        if successful < total:
            failed = [k for k, v in results.items() if not v]
            print(f"Failed files: {', '.join(failed)}")

    # Exit code: 0 if all successful, 1 otherwise
    sys.exit(0 if successful == total else 1)


if __name__ == "__main__":
    main()

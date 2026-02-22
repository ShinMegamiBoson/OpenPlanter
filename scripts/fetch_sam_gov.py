#!/usr/bin/env python3
"""
SAM.gov Exclusions and Entity Data Fetcher

Fetches exclusion records and entity information from SAM.gov APIs.
Requires a free API key from https://sam.gov/profile/details

Usage:
    # Download latest exclusions extract (ZIP file)
    python fetch_sam_gov.py --api-key YOUR_KEY --file-type EXCLUSION --output exclusions.zip

    # Download exclusions for specific date
    python fetch_sam_gov.py --api-key YOUR_KEY --file-type EXCLUSION --date 02/21/2026 --output exclusions.zip

    # Search for specific excluded entity
    python fetch_sam_gov.py --api-key YOUR_KEY --search-exclusions --name "Company Name" --output results.json

    # Search for entity by UEI
    python fetch_sam_gov.py --api-key YOUR_KEY --search-entity --uei ABC123DEF456 --output entity.json
"""

import argparse
import json
import sys
import urllib.request
import urllib.parse
import urllib.error
from typing import Dict, Optional, Any


class SAMGovClient:
    """Client for interacting with SAM.gov APIs using only stdlib."""

    BASE_URL = "https://api.sam.gov"
    EXTRACT_ENDPOINT = "/data-services/v1/extracts"
    EXCLUSIONS_ENDPOINT = "/entity-information/v4/exclusions"
    ENTITY_ENDPOINT = "/entity-information/v3/entities"

    def __init__(self, api_key: str):
        """Initialize client with API key."""
        self.api_key = api_key

    def _make_request(self, url: str, output_file: Optional[str] = None) -> Any:
        """Make HTTP GET request and return response."""
        try:
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'OpenPlanter-SAM-Fetcher/1.0')
            req.add_header('Accept', 'application/json, application/zip')

            with urllib.request.urlopen(req, timeout=30) as response:
                content_type = response.headers.get('Content-Type', '')

                if output_file:
                    # Binary download (ZIP/CSV files)
                    with open(output_file, 'wb') as f:
                        while True:
                            chunk = response.read(8192)
                            if not chunk:
                                break
                            f.write(chunk)
                    return {'status': 'success', 'file': output_file}
                elif 'json' in content_type:
                    # JSON response
                    data = response.read().decode('utf-8')
                    return json.loads(data)
                else:
                    # Plain text or other
                    return response.read().decode('utf-8')

        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8', errors='ignore')
            print(f"HTTP Error {e.code}: {e.reason}", file=sys.stderr)
            print(f"Response: {error_body}", file=sys.stderr)
            sys.exit(1)
        except urllib.error.URLError as e:
            print(f"URL Error: {e.reason}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    def fetch_extract(self, file_type: str, date: Optional[str] = None,
                     file_name: Optional[str] = None, output_file: Optional[str] = None) -> Dict:
        """
        Fetch bulk extract file from SAM.gov.

        Args:
            file_type: EXCLUSION, ENTITY, SCR, or BIO
            date: Optional date in MM/DD/YYYY format
            file_name: Optional specific file name
            output_file: Path to save downloaded file

        Returns:
            Dict with download status
        """
        params = {'api_key': self.api_key}

        if file_name:
            params['fileName'] = file_name
        else:
            params['fileType'] = file_type
            if date:
                params['date'] = date

        query_string = urllib.parse.urlencode(params)
        url = f"{self.BASE_URL}{self.EXTRACT_ENDPOINT}?{query_string}"

        print(f"Fetching extract from: {url}", file=sys.stderr)
        return self._make_request(url, output_file=output_file)

    def search_exclusions(self, name: Optional[str] = None, uei: Optional[str] = None,
                         state: Optional[str] = None, classification: Optional[str] = None,
                         page: int = 0, size: int = 10) -> Dict:
        """
        Search exclusions records.

        Args:
            name: Entity or individual name to search
            uei: Unique Entity Identifier
            state: Two-letter state code
            classification: Firm, Individual, Vessel, Special Entity Designation
            page: Page number (0-indexed)
            size: Results per page (max 10)

        Returns:
            Dict with exclusion records
        """
        params = {
            'api_key': self.api_key,
            'page': str(page),
            'size': str(min(size, 10))
        }

        if name:
            params['exclusionName'] = name
        if uei:
            params['ueiSAM'] = uei
        if state:
            params['stateProvince'] = state
        if classification:
            params['classification'] = classification

        query_string = urllib.parse.urlencode(params)
        url = f"{self.BASE_URL}{self.EXCLUSIONS_ENDPOINT}?{query_string}"

        print(f"Searching exclusions: {url}", file=sys.stderr)
        return self._make_request(url)

    def search_entity(self, uei: Optional[str] = None, cage_code: Optional[str] = None,
                     legal_business_name: Optional[str] = None, page: int = 0) -> Dict:
        """
        Search entity registration records.

        Args:
            uei: Unique Entity Identifier
            cage_code: CAGE Code
            legal_business_name: Business name to search
            page: Page number (0-indexed)

        Returns:
            Dict with entity records
        """
        params = {
            'api_key': self.api_key,
            'page': str(page)
        }

        if uei:
            params['ueiSAM'] = uei
        if cage_code:
            params['cageCode'] = cage_code
        if legal_business_name:
            params['legalBusinessName'] = legal_business_name

        query_string = urllib.parse.urlencode(params)
        url = f"{self.BASE_URL}{self.ENTITY_ENDPOINT}?{query_string}"

        print(f"Searching entities: {url}", file=sys.stderr)
        return self._make_request(url)


def main():
    """Main entry point for CLI."""
    parser = argparse.ArgumentParser(
        description='Fetch exclusion and entity data from SAM.gov',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        '--api-key',
        required=True,
        help='SAM.gov API key (get from https://sam.gov/profile/details)'
    )

    parser.add_argument(
        '--output',
        required=True,
        help='Output file path'
    )

    # Extraction mode
    extract_group = parser.add_argument_group('Extract mode (bulk downloads)')
    extract_group.add_argument(
        '--file-type',
        choices=['EXCLUSION', 'ENTITY', 'SCR', 'BIO'],
        help='Type of extract file to download'
    )
    extract_group.add_argument(
        '--date',
        help='Date for extract file (MM/DD/YYYY format)'
    )
    extract_group.add_argument(
        '--file-name',
        help='Specific file name to download'
    )

    # Search modes
    search_group = parser.add_argument_group('Search mode')
    search_group.add_argument(
        '--search-exclusions',
        action='store_true',
        help='Search exclusions database'
    )
    search_group.add_argument(
        '--search-entity',
        action='store_true',
        help='Search entity registrations'
    )

    # Common search parameters
    search_params = parser.add_argument_group('Search parameters')
    search_params.add_argument('--name', help='Entity or individual name')
    search_params.add_argument('--uei', help='Unique Entity Identifier')
    search_params.add_argument('--cage-code', help='CAGE Code')
    search_params.add_argument('--state', help='Two-letter state code')
    search_params.add_argument('--classification', help='Entity classification')
    search_params.add_argument('--page', type=int, default=0, help='Page number (default: 0)')
    search_params.add_argument('--size', type=int, default=10, help='Results per page (default: 10)')

    args = parser.parse_args()

    # Validate mode selection
    mode_count = sum([
        bool(args.file_type or args.file_name),
        args.search_exclusions,
        args.search_entity
    ])

    if mode_count == 0:
        parser.error("Must specify one mode: --file-type/--file-name, --search-exclusions, or --search-entity")
    if mode_count > 1:
        parser.error("Cannot combine modes: choose only one of extract, search-exclusions, or search-entity")

    # Initialize client
    client = SAMGovClient(args.api_key)

    try:
        # Execute requested operation
        if args.file_type or args.file_name:
            # Extract mode
            result = client.fetch_extract(
                file_type=args.file_type,
                date=args.date,
                file_name=args.file_name,
                output_file=args.output
            )
            print(f"Successfully downloaded to: {args.output}")

        elif args.search_exclusions:
            # Exclusions search mode
            result = client.search_exclusions(
                name=args.name,
                uei=args.uei,
                state=args.state,
                classification=args.classification,
                page=args.page,
                size=args.size
            )
            with open(args.output, 'w') as f:
                json.dump(result, f, indent=2)
            print(f"Search results saved to: {args.output}")

        elif args.search_entity:
            # Entity search mode
            result = client.search_entity(
                uei=args.uei,
                cage_code=args.cage_code,
                legal_business_name=args.name,
                page=args.page
            )
            with open(args.output, 'w') as f:
                json.dump(result, f, indent=2)
            print(f"Search results saved to: {args.output}")

    except KeyboardInterrupt:
        print("\nOperation cancelled by user", file=sys.stderr)
        sys.exit(130)


if __name__ == '__main__':
    main()

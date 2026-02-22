#!/usr/bin/env python3
"""
EPA ECHO Facility Data Acquisition Script

Fetches facility compliance and enforcement data from the EPA ECHO API
using only Python standard library (urllib, json).

Usage examples:
  python scripts/fetch_epa_echo.py --state MA --output facilities.csv
  python scripts/fetch_epa_echo.py --city Boston --state MA --format json
  python scripts/fetch_epa_echo.py --zip 02101 --radius 10 --compliance SNC
  python scripts/fetch_epa_echo.py --facility-name "Acme Corp" --output acme.csv
"""

import argparse
import json
import sys
import urllib.request
import urllib.parse
import urllib.error
import csv
from typing import Dict, List, Any, Optional


BASE_URL = "https://echodata.epa.gov/echo/echo_rest_services.get_facilities"
QID_URL = "https://echodata.epa.gov/echo/echo_rest_services.get_qid"


def build_query_params(args: argparse.Namespace) -> Dict[str, str]:
    """Build query parameters from command-line arguments."""
    params = {
        "output": "JSON",
        "responseset": str(args.limit),
    }

    if args.facility_name:
        params["p_fn"] = args.facility_name

    if args.state:
        params["p_st"] = args.state.upper()

    if args.city:
        params["p_ct"] = args.city

    if args.zip_code:
        params["p_zip"] = args.zip_code

    if args.radius and (args.latitude and args.longitude):
        params["p_lat"] = str(args.latitude)
        params["p_long"] = str(args.longitude)
        params["p_radius"] = str(args.radius)

    if args.compliance:
        # Compliance status: SNC, HPV, etc.
        params["p_cs"] = args.compliance

    if args.major_only:
        params["p_maj"] = "Y"

    if args.program:
        # Program filter: AIR, NPDES, RCRA, SDWA, TRI
        params["p_med"] = args.program.upper()

    return params


def fetch_url(url: str) -> Dict[str, Any]:
    """Fetch and parse JSON from a URL."""
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read().decode('utf-8')
            return json.loads(data)
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.reason}", file=sys.stderr)
        print(f"URL: {url}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"URL Error: {e.reason}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


def fetch_facilities(params: Dict[str, str]) -> Dict[str, Any]:
    """
    Fetch facility data from ECHO API using two-step workflow:
    1. Call get_facilities to get QueryID
    2. Call get_qid with QueryID to retrieve actual facility records
    """
    # Step 1: Get QueryID
    query_string = urllib.parse.urlencode(params)
    url = f"{BASE_URL}?{query_string}"

    initial_response = fetch_url(url)

    # Extract QueryID
    if "Results" not in initial_response or "QueryID" not in initial_response["Results"]:
        return initial_response

    query_id = initial_response["Results"]["QueryID"]

    # Step 2: Get actual facilities using QueryID
    qid_params = {
        "qid": query_id,
        "output": params.get("output", "JSON"),
        "pageno": "1",
        "responseset": params.get("responseset", "100")
    }

    qid_query_string = urllib.parse.urlencode(qid_params)
    qid_url = f"{QID_URL}?{qid_query_string}"

    facilities_response = fetch_url(qid_url)

    # Merge summary stats from initial response with facilities from QID response
    if "Results" in initial_response and "Results" in facilities_response:
        facilities_response["Results"]["QueryRows"] = initial_response["Results"].get("QueryRows")
        facilities_response["Results"]["TotalPenalties"] = initial_response["Results"].get("TotalPenalties")

    return facilities_response


def extract_facility_records(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract facility records from API response."""
    if "Results" not in response:
        return []

    results = response["Results"]

    # Check if we have facilities or need to handle clusters
    if "Facilities" in results:
        return results["Facilities"]

    # Some responses use different key names
    if "FacilityInfo" in results:
        return results["FacilityInfo"]

    return []


def write_csv(facilities: List[Dict[str, Any]], output_file: str) -> None:
    """Write facility data to CSV file."""
    if not facilities:
        print("No facilities to write", file=sys.stderr)
        return

    # Determine all unique keys across all facilities
    all_keys = set()
    for facility in facilities:
        all_keys.update(facility.keys())

    fieldnames = sorted(all_keys)

    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(facilities)

    print(f"Wrote {len(facilities)} facilities to {output_file}")


def write_json(facilities: List[Dict[str, Any]], output_file: str) -> None:
    """Write facility data to JSON file."""
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(facilities, f, indent=2)

    print(f"Wrote {len(facilities)} facilities to {output_file}")


def print_summary(response: Dict[str, Any]) -> None:
    """Print summary statistics from API response."""
    if "Results" not in response:
        return

    results = response["Results"]

    if "QueryID" in results:
        print(f"Query ID: {results['QueryID']}")

    if "QueryRows" in results:
        print(f"Total matching facilities: {results['QueryRows']}")

    if "Facilities" in results or "FacilityInfo" in results:
        facilities = results.get("Facilities", results.get("FacilityInfo", []))
        print(f"Facilities returned: {len(facilities)}")


def main():
    parser = argparse.ArgumentParser(
        description="Fetch EPA ECHO facility compliance and enforcement data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Fetch all facilities in Massachusetts
  %(prog)s --state MA --output ma_facilities.csv

  # Fetch facilities in Boston, MA
  %(prog)s --city Boston --state MA --output boston.csv

  # Fetch major violators (Significant Noncompliance) in a ZIP code
  %(prog)s --zip 02101 --compliance SNC --output violators.csv

  # Fetch facilities within 10 miles of coordinates
  %(prog)s --latitude 42.3601 --longitude -71.0589 --radius 10 --output nearby.csv

  # Search for specific facility by name
  %(prog)s --facility-name "Acme Corporation" --output acme.json --format json

  # Fetch major facilities only
  %(prog)s --state MA --major-only --output major_facilities.csv

Output formats:
  csv  - Comma-separated values (default)
  json - JSON array of facility objects
        """
    )

    # Search criteria
    parser.add_argument("--facility-name", help="Facility name (supports partial matching)")
    parser.add_argument("--state", help="State postal code (e.g., MA, CA, TX)")
    parser.add_argument("--city", help="City name")
    parser.add_argument("--zip", dest="zip_code", help="5-digit ZIP code")
    parser.add_argument("--latitude", type=float, help="Latitude for radius search")
    parser.add_argument("--longitude", type=float, help="Longitude for radius search")
    parser.add_argument("--radius", type=float, help="Radius in miles (requires --latitude and --longitude, max 100)")
    parser.add_argument("--compliance", help="Compliance status filter (e.g., SNC, HPV)")
    parser.add_argument("--major-only", action="store_true", help="Only return major facilities")
    parser.add_argument("--program", help="Program filter (AIR, NPDES, RCRA, SDWA, TRI)")

    # Output options
    parser.add_argument("--output", "-o", help="Output file path (default: stdout)")
    parser.add_argument("--format", choices=["csv", "json"], default="csv", help="Output format (default: csv)")
    parser.add_argument("--limit", type=int, default=100, help="Maximum records to retrieve (default: 100, max: 1000)")
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress summary output")

    args = parser.parse_args()

    # Validate arguments
    if args.radius and not (args.latitude and args.longitude):
        parser.error("--radius requires both --latitude and --longitude")

    if args.radius and args.radius > 100:
        parser.error("--radius cannot exceed 100 miles")

    if args.limit > 1000:
        parser.error("--limit cannot exceed 1000")

    # Build query and fetch data
    params = build_query_params(args)

    if not args.quiet:
        print("Fetching ECHO facility data...", file=sys.stderr)

    response = fetch_facilities(params)

    if not args.quiet:
        print_summary(response)

    facilities = extract_facility_records(response)

    if not facilities:
        print("No facilities found matching criteria", file=sys.stderr)
        sys.exit(0)

    # Output results
    if args.output:
        if args.format == "json":
            write_json(facilities, args.output)
        else:
            write_csv(facilities, args.output)
    else:
        # Print to stdout
        if args.format == "json":
            print(json.dumps(facilities, indent=2))
        else:
            # Print CSV to stdout
            if facilities:
                fieldnames = sorted(set().union(*[f.keys() for f in facilities]))
                writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(facilities)


if __name__ == "__main__":
    main()

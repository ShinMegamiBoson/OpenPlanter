#!/usr/bin/env python3
"""
Fetch US Census Bureau American Community Survey (ACS) data via API.

This script queries the Census Data API for specified variables and geographies,
outputting results to CSV or JSON format. Uses only Python standard library.

Examples:
    # Get median income for all states (no API key needed for small queries)
    python fetch_census_acs.py --year 2023 --dataset acs5 \
        --variables B19013_001E --geography state:* \
        --output state_income.csv

    # Get poverty data for Boston metro area tracts with API key
    python fetch_census_acs.py --year 2023 --dataset acs5 \
        --variables B17001_002E,B17001_001E --geography tract:* \
        --state 25 --county 025 --key YOUR_KEY \
        --output boston_poverty.csv

    # Get full table group (all B01001 variables)
    python fetch_census_acs.py --year 2023 --dataset acs5 \
        --group B01001 --geography county:* --state 25 \
        --output ma_age_sex.csv
"""

import argparse
import csv
import json
import sys
import urllib.request
import urllib.parse
import urllib.error
from typing import List, Dict, Any, Optional


def build_api_url(
    year: int,
    dataset: str,
    variables: Optional[List[str]] = None,
    group: Optional[str] = None,
    geography: str = "*",
    state: Optional[str] = None,
    county: Optional[str] = None,
    api_key: Optional[str] = None
) -> str:
    """
    Build Census API URL from components.

    Args:
        year: Year of data (e.g., 2023)
        dataset: Dataset name (e.g., 'acs5', 'acs1')
        variables: List of variable codes (e.g., ['B19013_001E'])
        group: Table group code (e.g., 'B01001') - alternative to variables
        geography: Geographic level (e.g., 'state:*', 'county:*', 'tract:*')
        state: State FIPS code for filtering (e.g., '25' for MA)
        county: County FIPS code for filtering (e.g., '025' for Suffolk)
        api_key: Census API key (optional for <500 queries/day)

    Returns:
        Formatted API URL string
    """
    base_url = f"https://api.census.gov/data/{year}/acs/{dataset}"

    # Build get parameter
    get_parts = ["NAME"]
    if variables:
        get_parts.extend(variables)
    elif group:
        get_parts.append(f"group({group})")
    else:
        raise ValueError("Must specify either --variables or --group")

    params = {"get": ",".join(get_parts)}

    # Build geography parameter
    params["for"] = geography

    # Add geographic filters
    if state or county:
        in_parts = []
        if state:
            in_parts.append(f"state:{state}")
        if county:
            in_parts.append(f"county:{county}")
        params["in"] = "+".join(in_parts)

    # Add API key if provided
    if api_key:
        params["key"] = api_key

    query_string = urllib.parse.urlencode(params)
    return f"{base_url}?{query_string}"


def fetch_census_data(url: str) -> List[List[str]]:
    """
    Fetch data from Census API.

    Args:
        url: Complete API URL

    Returns:
        List of rows, where first row is headers

    Raises:
        urllib.error.HTTPError: If API request fails
    """
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            data = json.loads(response.read().decode('utf-8'))
            return data
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        print(f"API Error {e.code}: {e.reason}", file=sys.stderr)
        print(f"Response: {error_body}", file=sys.stderr)
        raise
    except urllib.error.URLError as e:
        print(f"Network error: {e.reason}", file=sys.stderr)
        raise
    except json.JSONDecodeError as e:
        print(f"Invalid JSON response: {e}", file=sys.stderr)
        raise


def write_csv(data: List[List[str]], output_path: str) -> None:
    """
    Write Census data to CSV file.

    Args:
        data: List of rows (first row is header)
        output_path: Output file path
    """
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerows(data)


def write_json(data: List[List[str]], output_path: str) -> None:
    """
    Write Census data to JSON file as list of dictionaries.

    Args:
        data: List of rows (first row is header)
        output_path: Output file path
    """
    headers = data[0]
    rows = data[1:]

    records = [dict(zip(headers, row)) for row in rows]

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(records, f, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description="Fetch US Census ACS data via API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Get median income for all Massachusetts counties
  %(prog)s --year 2023 --dataset acs5 --variables B19013_001E \\
      --geography county:* --state 25 --output ma_income.csv

  # Get poverty data for all tracts in Suffolk County (Boston)
  %(prog)s --year 2023 --dataset acs5 \\
      --variables B17001_002E,B17001_001E \\
      --geography tract:* --state 25 --county 025 \\
      --output boston_poverty.csv

  # Get full age/sex table for all states
  %(prog)s --year 2023 --dataset acs5 --group B01001 \\
      --geography state:* --output states_age_sex.json

Common variable codes:
  B01003_001E    Total population
  B19013_001E    Median household income
  B19301_001E    Per capita income
  B17001_002E    Population in poverty (numerator)
  B17001_001E    Population for whom poverty status determined (denominator)
  B25077_001E    Median home value
  B25064_001E    Median gross rent

Geography examples:
  state:*                All states
  county:*               All counties (use with --state to filter)
  tract:*                All tracts (requires --state and optionally --county)
  place:07000            Specific place (Boston FIPS)

Get your free API key at: https://api.census.gov/data/key_signup.html
        """
    )

    parser.add_argument("--year", type=int, required=True,
                        help="Data year (e.g., 2023)")
    parser.add_argument("--dataset", required=True,
                        choices=["acs1", "acs5", "acs1/profile", "acs5/profile", "acs5/subject"],
                        help="ACS dataset type")

    # Variable selection (mutually exclusive)
    var_group = parser.add_mutually_exclusive_group(required=True)
    var_group.add_argument("--variables",
                           help="Comma-separated variable codes (e.g., B19013_001E,B19013_001M)")
    var_group.add_argument("--group",
                           help="Table group code to fetch all variables (e.g., B01001)")

    # Geography
    parser.add_argument("--geography", required=True,
                        help="Geographic level (e.g., state:*, county:*, tract:*, place:07000)")
    parser.add_argument("--state",
                        help="State FIPS code filter (e.g., 25 for Massachusetts)")
    parser.add_argument("--county",
                        help="County FIPS code filter (e.g., 025 for Suffolk County)")

    # API key
    parser.add_argument("--key",
                        help="Census API key (optional, but recommended for >500 queries/day)")

    # Output
    parser.add_argument("--output", required=True,
                        help="Output file path (.csv or .json)")
    parser.add_argument("--format",
                        choices=["csv", "json"],
                        help="Output format (auto-detected from filename if not specified)")

    args = parser.parse_args()

    # Parse variables
    variables = None
    if args.variables:
        variables = [v.strip() for v in args.variables.split(",")]

    # Determine output format
    output_format = args.format
    if not output_format:
        if args.output.endswith(".json"):
            output_format = "json"
        elif args.output.endswith(".csv"):
            output_format = "csv"
        else:
            print("Error: Cannot determine output format. Use --format or name file .csv/.json",
                  file=sys.stderr)
            sys.exit(1)

    # Build URL
    try:
        url = build_api_url(
            year=args.year,
            dataset=args.dataset,
            variables=variables,
            group=args.group,
            geography=args.geography,
            state=args.state,
            county=args.county,
            api_key=args.key
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Fetching from: {url}", file=sys.stderr)

    # Fetch data
    try:
        data = fetch_census_data(url)
    except Exception as e:
        print(f"Failed to fetch data: {e}", file=sys.stderr)
        sys.exit(1)

    if not data or len(data) < 2:
        print("Warning: No data returned from API", file=sys.stderr)
        sys.exit(1)

    print(f"Retrieved {len(data) - 1} rows with {len(data[0])} columns", file=sys.stderr)

    # Write output
    try:
        if output_format == "csv":
            write_csv(data, args.output)
        else:
            write_json(data, args.output)
        print(f"Wrote {args.output}", file=sys.stderr)
    except Exception as e:
        print(f"Failed to write output: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

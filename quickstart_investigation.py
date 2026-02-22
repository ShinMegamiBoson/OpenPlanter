#!/usr/bin/env python3
"""
Boston Corruption Investigation — Quick Start Script
=====================================================
Downloads the two most accessible datasets (City Contracts + OCPF Campaign Finance)
and cross-references them to find potential pay-to-play indicators.

This is a starting point. See boston_corruption_investigation_playbook.md for the full methodology.

Usage:
    pip install pandas requests rapidfuzz
    python quickstart_investigation.py

Output:
    - data/contracts.csv          (downloaded)
    - data/ocpf_contributions/    (downloaded, one file per candidate)
    - output/donor_contractor_matches.csv
    - output/bundled_donations.csv
    - output/sole_source_contracts.csv
"""

import os
import sys
import csv
import json
from datetime import datetime, timedelta
from collections import defaultdict

# Check dependencies
try:
    import pandas as pd
    import requests
except ImportError:
    print("Install required packages: pip install pandas requests rapidfuzz")
    sys.exit(1)

try:
    from rapidfuzz import fuzz, process
except ImportError:
    print("Warning: rapidfuzz not installed. Falling back to exact matching only.")
    print("Install with: pip install rapidfuzz")
    fuzz = None

# ============================================================
# Configuration
# ============================================================

DATA_DIR = "data"
OUTPUT_DIR = "output"

# City of Boston Contract Award CSV (direct download from Analyze Boston)
CONTRACT_URL = "https://data.boston.gov/dataset/fbf8bda3-ccb1-4af4-84c8-6540f17edac3/resource/fe05fdc4-ea9d-43b1-a3cc-a87b55c1d6d5/download/contract_award_open_data_fy19q1_fy26q1.csv"

# OCPF Data Center bulk download page
OCPF_BASE_URL = "https://www.ocpf.us"

# Fuzzy match threshold (0-100, higher = stricter)
FUZZY_THRESHOLD = 85

# Time window for donation-contract correlation (days)
CORRELATION_WINDOW_DAYS = 180


def setup_dirs():
    """Create data and output directories."""
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "ocpf_contributions"), exist_ok=True)


def download_contracts():
    """Download City of Boston contract awards."""
    filepath = os.path.join(DATA_DIR, "contracts.csv")
    if os.path.exists(filepath):
        print(f"[✓] Contracts already downloaded: {filepath}")
        return filepath

    print("[↓] Downloading City of Boston contract awards...")
    try:
        resp = requests.get(CONTRACT_URL, timeout=60)
        resp.raise_for_status()
        with open(filepath, 'wb') as f:
            f.write(resp.content)
        print(f"[✓] Downloaded: {filepath} ({len(resp.content):,} bytes)")
        return filepath
    except Exception as e:
        print(f"[✗] Failed to download contracts: {e}")
        print(f"    Manual download: {CONTRACT_URL}")
        print(f"    Save to: {filepath}")
        return None


def normalize_org_name(name):
    """Normalize an organization name for matching."""
    if not name or not isinstance(name, str):
        return ""
    name = name.upper().strip()
    # Remove common suffixes
    for suffix in [' LLC', ' L.L.C.', ' INC.', ' INC', ' CORP.', ' CORP',
                   ' CO.', ' CO', ' LTD.', ' LTD', ' LP', ' L.P.',
                   ' LLP', ' L.L.P.', ', LLC', ', INC.', ', INC',
                   ', CORP.', ', CORP', ', CO.']:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    # Remove punctuation
    name = name.replace(',', '').replace('.', '').replace("'", '').replace('"', '')
    # Collapse whitespace
    name = ' '.join(name.split())
    return name


def analyze_contracts(filepath):
    """Load and analyze contract data."""
    print("\n[📊] Analyzing contracts...")
    df = pd.read_csv(filepath, low_memory=False)
    print(f"    Total contracts: {len(df):,}")
    print(f"    Columns: {list(df.columns)}")

    # Show some stats
    type_col = None
    for col in ['Procurement Type', 'procurement_type', 'contract_method_subcategory']:
        if col in df.columns:
            type_col = col
            break
    if type_col:
        print(f"\n    Procurement types:")
        for ptype, count in df[type_col].value_counts().head(10).items():
            print(f"      {ptype}: {count:,}")

    return df


def find_sole_source_contracts(contracts_df):
    """Identify sole-source and limited-competition contracts."""
    print("\n[🔍] Finding sole-source/limited-competition contracts...")

    # Try to find the procurement type column
    type_col = None
    for candidate in ['Procurement Type', 'procurement_type', 'Award Type', 'ContractType',
                      'contract_method_subcategory', 'procurement_or_other_category']:
        if candidate in contracts_df.columns:
            type_col = candidate
            break

    if type_col is None:
        print("    Could not identify procurement type column.")
        print(f"    Available columns: {list(contracts_df.columns)}")
        return pd.DataFrame()

    # Filter for non-competitive procurements
    sole_source = contracts_df[
        contracts_df[type_col].str.contains(
            'sole|limited|emergency|exempt|non.?competitive',
            case=False, na=False
        )
    ].copy()

    print(f"    Found {len(sole_source):,} non-competitive contracts")

    # Save
    output_path = os.path.join(OUTPUT_DIR, "sole_source_contracts.csv")
    sole_source.to_csv(output_path, index=False)
    print(f"    Saved to: {output_path}")

    return sole_source


def find_bundled_donations(contributions_df):
    """Find potential bundled donations (multiple people from same employer donating on same day)."""
    print("\n[🔍] Finding potential bundled donations...")

    if contributions_df.empty:
        print("    No contribution data to analyze.")
        return pd.DataFrame()

    # Identify employer column
    employer_col = None
    for candidate in ['Employer', 'employer', 'Donor Employer', 'contributor_employer']:
        if candidate in contributions_df.columns:
            employer_col = candidate
            break

    date_col = None
    for candidate in ['Date', 'date', 'Contribution Date', 'contribution_date']:
        if candidate in contributions_df.columns:
            date_col = candidate
            break

    if employer_col is None or date_col is None:
        print(f"    Could not identify required columns. Available: {list(contributions_df.columns)}")
        return pd.DataFrame()

    # Group by employer + date + recipient
    recipient_col = None
    for candidate in ['Recipient', 'recipient', 'Committee', 'committee', 'Candidate']:
        if candidate in contributions_df.columns:
            recipient_col = candidate
            break

    group_cols = [employer_col, date_col]
    if recipient_col:
        group_cols.append(recipient_col)

    # Filter out empty employers
    has_employer = contributions_df[contributions_df[employer_col].notna() &
                                    (contributions_df[employer_col] != '')]

    bundled = has_employer.groupby(group_cols).size().reset_index(name='num_donors')
    bundled = bundled[bundled['num_donors'] >= 3].sort_values('num_donors', ascending=False)

    print(f"    Found {len(bundled):,} potential bundled donation events (3+ from same employer on same day)")

    output_path = os.path.join(OUTPUT_DIR, "bundled_donations.csv")
    bundled.to_csv(output_path, index=False)
    print(f"    Saved to: {output_path}")

    return bundled


def cross_reference(contracts_df, contributions_df):
    """Cross-reference contract vendors with campaign donors/employers."""
    print("\n[🔗] Cross-referencing contractors with campaign donors...")

    if contributions_df.empty:
        print("    No contribution data available for cross-referencing.")
        return

    # Get unique vendor names from contracts
    vendor_col = None
    for candidate in ['Vendor Name', 'vendor_name', 'Vendor', 'VENDOR_NAME', 'Supplier Name', 'vendor_name1']:
        if candidate in contracts_df.columns:
            vendor_col = candidate
            break

    if vendor_col is None:
        print(f"    Could not find vendor column. Available: {list(contracts_df.columns)}")
        return

    # Get unique employer names from contributions
    employer_col = None
    for candidate in ['Employer', 'employer', 'Donor Employer', 'contributor_employer']:
        if candidate in contributions_df.columns:
            employer_col = candidate
            break

    vendors = contracts_df[vendor_col].dropna().unique()
    vendors_normalized = {normalize_org_name(v): v for v in vendors if v}

    employers = contributions_df[employer_col].dropna().unique()
    employers_normalized = {normalize_org_name(e): e for e in employers if e}

    # Find matches
    matches = []
    vendor_names = list(vendors_normalized.keys())

    for emp_norm, emp_orig in employers_normalized.items():
        if not emp_norm:
            continue

        # Exact match first
        if emp_norm in vendors_normalized:
            matches.append({
                'employer_original': emp_orig,
                'vendor_original': vendors_normalized[emp_norm],
                'match_type': 'exact_normalized',
                'score': 100
            })
        elif fuzz is not None:
            # Fuzzy match
            result = process.extractOne(emp_norm, vendor_names, scorer=fuzz.ratio)
            if result and result[1] >= FUZZY_THRESHOLD:
                matched_vendor_norm = result[0]
                matches.append({
                    'employer_original': emp_orig,
                    'vendor_original': vendors_normalized[matched_vendor_norm],
                    'match_type': 'fuzzy',
                    'score': result[1]
                })

    print(f"    Found {len(matches):,} employer-vendor matches")

    if matches:
        matches_df = pd.DataFrame(matches)
        output_path = os.path.join(OUTPUT_DIR, "donor_contractor_matches.csv")
        matches_df.to_csv(output_path, index=False)
        print(f"    Saved to: {output_path}")

        # Show top matches
        print("\n    Top matches:")
        for _, row in matches_df.head(20).iterrows():
            print(f"      [{row['match_type']}:{row['score']}] "
                  f"Donor employer: {row['employer_original']} ↔ Vendor: {row['vendor_original']}")


def print_instructions():
    """Print instructions for obtaining OCPF data."""
    print("""
╔══════════════════════════════════════════════════════════════════╗
║  OCPF Campaign Finance Data — Manual Download Instructions     ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  OCPF does not offer a single bulk download file. You need to   ║
║  download contribution data per candidate or committee.          ║
║                                                                  ║
║  Option A: OCPF Data Center (recommended)                        ║
║  1. Go to https://www.ocpf.us/Data                               ║
║  2. Use "Search by Candidate/Committee" to find Boston officials ║
║  3. Export contributions to CSV                                   ║
║  4. Save files to data/ocpf_contributions/                       ║
║                                                                  ║
║  Option B: Use the R package `maocpf`                            ║
║  1. install.packages("devtools")                                 ║
║  2. devtools::install_github("smach/maocpf")                     ║
║  3. Use get_local_candidates() to find Boston candidate IDs      ║
║  4. Use get_candidate_contribution_data(id) for each candidate   ║
║                                                                  ║
║  Key Boston candidates to download:                              ║
║  - Mayor (current + recent)                                      ║
║  - All 13 City Councilors (4 at-large + 9 district)             ║
║  - Any state reps/senators representing Boston districts          ║
║                                                                  ║
║  After downloading, re-run this script to cross-reference.       ║
╚══════════════════════════════════════════════════════════════════╝
""")


def load_ocpf_contributions():
    """Load any OCPF contribution files from the data directory."""
    contributions_dir = os.path.join(DATA_DIR, "ocpf_contributions")
    all_contributions = []

    if not os.path.exists(contributions_dir):
        return pd.DataFrame()

    for filename in os.listdir(contributions_dir):
        if filename.endswith('.csv'):
            filepath = os.path.join(contributions_dir, filename)
            try:
                df = pd.read_csv(filepath, low_memory=False)
                df['_source_file'] = filename
                all_contributions.append(df)
            except Exception as e:
                print(f"    Warning: Could not load {filename}: {e}")

    if all_contributions:
        combined = pd.concat(all_contributions, ignore_index=True)
        print(f"[✓] Loaded {len(combined):,} contribution records from {len(all_contributions)} files")
        return combined
    else:
        print("[!] No OCPF contribution files found in data/ocpf_contributions/")
        return pd.DataFrame()


def main():
    print("=" * 65)
    print("  Boston Local Politics — Corruption Indicator Analysis")
    print("  Quick Start Script")
    print("=" * 65)
    print()

    setup_dirs()

    # Step 1: Download contracts
    contracts_path = download_contracts()
    if contracts_path is None:
        print("\n[!] Cannot proceed without contract data. Download manually and retry.")
        return

    # Step 2: Load and analyze contracts
    contracts_df = analyze_contracts(contracts_path)

    # Step 3: Find sole-source contracts
    find_sole_source_contracts(contracts_df)

    # Step 4: Load OCPF data (if available)
    contributions_df = load_ocpf_contributions()

    if contributions_df.empty:
        print_instructions()
    else:
        # Step 5: Find bundled donations
        find_bundled_donations(contributions_df)

        # Step 6: Cross-reference
        cross_reference(contracts_df, contributions_df)

    print("\n" + "=" * 65)
    print("  Analysis complete. Check the output/ directory for results.")
    print("  See boston_corruption_investigation_playbook.md for full methodology.")
    print("=" * 65)


if __name__ == "__main__":
    main()

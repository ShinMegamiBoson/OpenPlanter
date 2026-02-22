#!/usr/bin/env python3
"""
Cross-link Boston city contracts with OCPF campaign finance data.
Identifies potential pay-to-play indicators.
"""

import csv
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime

import pandas as pd

# Try rapidfuzz for fuzzy matching
try:
    from rapidfuzz import fuzz, process
    HAS_FUZZ = True
except ImportError:
    HAS_FUZZ = False
    print("Warning: rapidfuzz not available, using exact matching only")

FUZZY_THRESHOLD = 82

# ============================================================
# Step 1: Identify Boston candidates from candidates.txt
# ============================================================
def load_boston_candidates():
    """Load candidates.txt and find Boston-area candidates."""
    candidates = {}
    boston_cpf_ids = set()
    
    with open('data/ocpf_contributions/candidates.txt', 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.DictReader(f, delimiter='\t')
        for row in reader:
            cpf_id = row.get('CPF ID', '').strip().strip('"')
            city = row.get('Candidate City', '').strip().strip('"').upper()
            office = row.get('Office Type Sought', '').strip().strip('"').upper()
            district = row.get('District Name Sought', '').strip().strip('"').upper()
            first = row.get('Candidate First Name', '').strip().strip('"')
            last = row.get('Candidate Last Name', '').strip().strip('"')
            comm_name = row.get('Comm_Name', '').strip().strip('"')
            
            if cpf_id:
                candidates[cpf_id] = {
                    'cpf_id': cpf_id,
                    'name': f"{first} {last}".strip(),
                    'city': city,
                    'office': office,
                    'district': district,
                    'comm_name': comm_name
                }
                
                # Boston candidates: city = BOSTON or district contains BOSTON or
                # office is municipal and city is Boston
                is_boston = False
                if city == 'BOSTON':
                    is_boston = True
                if 'BOSTON' in district:
                    is_boston = True
                if office in ('CITY COUNCIL', 'MAYOR', 'CITY COUNCILLOR', 'MUNICIPAL'):
                    if city == 'BOSTON':
                        is_boston = True
                
                if is_boston:
                    boston_cpf_ids.add(cpf_id)
    
    print(f"  Total candidates: {len(candidates):,}")
    print(f"  Boston-related candidates: {len(boston_cpf_ids):,}")
    return candidates, boston_cpf_ids


# ============================================================
# Step 2: Load reports to map Report_ID -> CPF_ID
# ============================================================
def load_reports(boston_cpf_ids):
    """Load reports.txt and find reports filed by Boston candidates."""
    report_to_cpf = {}
    boston_reports = set()
    
    with open('data/ocpf_contributions/reports.txt', 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.DictReader(f, delimiter='\t')
        for row in reader:
            report_id = row.get('Report_ID', '').strip().strip('"')
            cpf_id = row.get('CPF_ID', '').strip().strip('"')
            
            if report_id and cpf_id:
                report_to_cpf[report_id] = cpf_id
                if cpf_id in boston_cpf_ids:
                    boston_reports.add(report_id)
    
    print(f"  Total reports: {len(report_to_cpf):,}")
    print(f"  Boston candidate reports: {len(boston_reports):,}")
    return report_to_cpf, boston_reports


# ============================================================
# Step 3: Extract contributions to Boston candidates
# ============================================================
def load_boston_contributions(boston_reports, report_to_cpf, candidates):
    """Load report-items.txt, filter for contributions to Boston candidates."""
    # Contribution record types
    CONTRIBUTION_TYPES = {'201', '202', '203', '211'}  # Individual, Committee, Union, Business
    
    contributions = []
    total_items = 0
    
    with open('data/ocpf_contributions/report-items.txt', 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.DictReader(f, delimiter='\t')
        for row in reader:
            total_items += 1
            report_id = row.get('Report_ID', '').strip().strip('"')
            record_type = row.get('Record_Type_ID', '').strip().strip('"')
            
            if report_id in boston_reports and record_type in CONTRIBUTION_TYPES:
                cpf_id = report_to_cpf.get(report_id, '')
                candidate = candidates.get(cpf_id, {})
                
                amount_str = row.get('Amount', '0').strip().strip('"')
                try:
                    amount = float(amount_str)
                except:
                    amount = 0.0
                
                contributions.append({
                    'report_id': report_id,
                    'cpf_id': cpf_id,
                    'candidate_name': candidate.get('name', ''),
                    'candidate_office': candidate.get('office', ''),
                    'record_type': record_type,
                    'date': row.get('Date', '').strip().strip('"'),
                    'amount': amount,
                    'donor_last': row.get('Name', '').strip().strip('"'),
                    'donor_first': row.get('First_Name', '').strip().strip('"'),
                    'employer': row.get('Employer', '').strip().strip('"'),
                    'occupation': row.get('Occupation', '').strip().strip('"'),
                    'city': row.get('City', '').strip().strip('"'),
                    'state': row.get('State', '').strip().strip('"'),
                    'zip': row.get('Zip', '').strip().strip('"'),
                })
    
    print(f"  Total report items scanned: {total_items:,}")
    print(f"  Boston candidate contributions: {len(contributions):,}")
    if contributions:
        total_amt = sum(c['amount'] for c in contributions)
        print(f"  Total contribution amount: ${total_amt:,.2f}")
    return contributions


# ============================================================  
# Step 4: Normalize names for matching
# ============================================================
def normalize_name(name):
    """Normalize an organization/business name for matching."""
    if not name or not isinstance(name, str):
        return ""
    name = name.upper().strip()
    # Remove common suffixes
    for suffix in [' LLC', ' L.L.C.', ' INC.', ' INC', ' CORP.', ' CORP',
                   ' CO.', ' CO', ' LTD.', ' LTD', ' LP', ' L.P.',
                   ' LLP', ' L.L.P.', ', LLC', ', INC.', ', INC',
                   ', CORP.', ', CORP', ', CO.', ' COMPANY', ' CORPORATION',
                   ' INCORPORATED', ' LIMITED', ' ENTERPRISES', ' SERVICES',
                   ' GROUP', ' ASSOCIATES', ' CONSULTING', ' SOLUTIONS']:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    # Remove punctuation and extra whitespace
    name = re.sub(r'[,.\'"&\-/]', ' ', name)
    name = ' '.join(name.split())
    return name


# ============================================================
# Step 5: Build entity map from contracts
# ============================================================
def build_vendor_map(contracts_df):
    """Build normalized vendor name map from contracts."""
    vendor_map = {}
    for _, row in contracts_df.iterrows():
        vendor = str(row.get('vendor_name1', '')).strip()
        if vendor and vendor != 'nan':
            normalized = normalize_name(vendor)
            if normalized:
                if normalized not in vendor_map:
                    vendor_map[normalized] = {
                        'original_names': set(),
                        'total_value': 0.0,
                        'contract_count': 0,
                        'departments': set(),
                        'sole_source': False,
                        'contract_types': set(),
                    }
                vendor_map[normalized]['original_names'].add(vendor)
                try:
                    val = float(row.get('amt_cntrct_max', 0))
                except:
                    val = 0.0
                vendor_map[normalized]['total_value'] += val
                vendor_map[normalized]['contract_count'] += 1
                dept = str(row.get('dept_tbl_descr_3_digit', ''))
                if dept != 'nan':
                    vendor_map[normalized]['departments'].add(dept)
                method = str(row.get('contract_method_subcategory', ''))
                vendor_map[normalized]['contract_types'].add(method)
                if method in ('Limited Competition', 'Sole Source', 'Emergency', 'Exempt'):
                    vendor_map[normalized]['sole_source'] = True
    
    # Convert sets to lists for JSON serialization
    for k, v in vendor_map.items():
        v['original_names'] = list(v['original_names'])
        v['departments'] = list(v['departments'])
        v['contract_types'] = list(v['contract_types'])
    
    print(f"  Unique normalized vendor names: {len(vendor_map):,}")
    sole_source_vendors = sum(1 for v in vendor_map.values() if v['sole_source'])
    print(f"  Vendors with sole source contracts: {sole_source_vendors:,}")
    return vendor_map


# ============================================================
# Step 6: Cross-reference donors with contractors
# ============================================================
def cross_reference(contributions, vendor_map):
    """Match campaign donors (by employer) with city contractors."""
    matches = []
    vendor_names = list(vendor_map.keys())
    
    # Build employer index from contributions
    employer_donors = defaultdict(list)
    business_donors = defaultdict(list)
    
    for c in contributions:
        employer = normalize_name(c['employer'])
        if employer and len(employer) > 2:
            employer_donors[employer].append(c)
        
        # For business/corp contributions (record_type 211), also use the donor name itself
        if c['record_type'] == '211':
            biz_name = normalize_name(f"{c['donor_last']} {c['donor_first']}".strip())
            if biz_name and len(biz_name) > 2:
                business_donors[biz_name].append(c)
    
    print(f"  Unique employer names in contributions: {len(employer_donors):,}")
    print(f"  Business/corp donors: {len(business_donors):,}")
    
    # Exact matching first
    exact_matches = 0
    for vendor_norm, vendor_info in vendor_map.items():
        # Check employer match
        if vendor_norm in employer_donors:
            for c in employer_donors[vendor_norm]:
                matches.append({
                    'match_type': 'exact_employer',
                    'vendor_name': vendor_info['original_names'][0],
                    'vendor_normalized': vendor_norm,
                    'vendor_total_value': vendor_info['total_value'],
                    'vendor_sole_source': vendor_info['sole_source'],
                    'vendor_departments': '; '.join(vendor_info['departments']),
                    'donor_name': f"{c['donor_first']} {c['donor_last']}",
                    'employer': c['employer'],
                    'donation_amount': c['amount'],
                    'donation_date': c['date'],
                    'candidate_name': c['candidate_name'],
                    'candidate_office': c['candidate_office'],
                    'record_type': c['record_type'],
                    'confidence': 'high',
                })
                exact_matches += 1
        
        # Check business donor name match
        if vendor_norm in business_donors:
            for c in business_donors[vendor_norm]:
                matches.append({
                    'match_type': 'exact_business_donor',
                    'vendor_name': vendor_info['original_names'][0],
                    'vendor_normalized': vendor_norm,
                    'vendor_total_value': vendor_info['total_value'],
                    'vendor_sole_source': vendor_info['sole_source'],
                    'vendor_departments': '; '.join(vendor_info['departments']),
                    'donor_name': f"{c['donor_first']} {c['donor_last']}",
                    'employer': c['employer'],
                    'donation_amount': c['amount'],
                    'donation_date': c['date'],
                    'candidate_name': c['candidate_name'],
                    'candidate_office': c['candidate_office'],
                    'record_type': c['record_type'],
                    'confidence': 'high',
                })
                exact_matches += 1
    
    print(f"  Exact matches: {exact_matches:,}")
    
    # Fuzzy matching (only if rapidfuzz available and for employer names)
    fuzzy_matches = 0
    if HAS_FUZZ and vendor_names:
        # Only fuzzy match employers not already exactly matched
        unmatched_employers = [e for e in employer_donors.keys() if e not in vendor_map]
        print(f"  Running fuzzy matching on {len(unmatched_employers):,} unmatched employers...")
        
        for emp_norm in unmatched_employers:
            if len(emp_norm) < 4:
                continue
            result = process.extractOne(emp_norm, vendor_names, scorer=fuzz.token_sort_ratio)
            if result and result[1] >= FUZZY_THRESHOLD:
                matched_vendor = result[0]
                vendor_info = vendor_map[matched_vendor]
                for c in employer_donors[emp_norm]:
                    matches.append({
                        'match_type': 'fuzzy_employer',
                        'vendor_name': vendor_info['original_names'][0],
                        'vendor_normalized': matched_vendor,
                        'vendor_total_value': vendor_info['total_value'],
                        'vendor_sole_source': vendor_info['sole_source'],
                        'vendor_departments': '; '.join(vendor_info['departments']),
                        'donor_name': f"{c['donor_first']} {c['donor_last']}",
                        'employer': c['employer'],
                        'donation_amount': c['amount'],
                        'donation_date': c['date'],
                        'candidate_name': c['candidate_name'],
                        'candidate_office': c['candidate_office'],
                        'record_type': c['record_type'],
                        'confidence': 'probable',
                        'fuzzy_score': result[1],
                    })
                    fuzzy_matches += 1
        
        # Also fuzzy match business donors
        unmatched_biz = [b for b in business_donors.keys() if b not in vendor_map]
        for biz_norm in unmatched_biz:
            if len(biz_norm) < 4:
                continue
            result = process.extractOne(biz_norm, vendor_names, scorer=fuzz.token_sort_ratio)
            if result and result[1] >= FUZZY_THRESHOLD:
                matched_vendor = result[0]
                vendor_info = vendor_map[matched_vendor]
                for c in business_donors[biz_norm]:
                    matches.append({
                        'match_type': 'fuzzy_business_donor',
                        'vendor_name': vendor_info['original_names'][0],
                        'vendor_normalized': matched_vendor,
                        'vendor_total_value': vendor_info['total_value'],
                        'vendor_sole_source': vendor_info['sole_source'],
                        'vendor_departments': '; '.join(vendor_info['departments']),
                        'donor_name': f"{c['donor_first']} {c['donor_last']}",
                        'employer': c['employer'],
                        'donation_amount': c['amount'],
                        'donation_date': c['date'],
                        'candidate_name': c['candidate_name'],
                        'candidate_office': c['candidate_office'],
                        'record_type': c['record_type'],
                        'confidence': 'probable',
                        'fuzzy_score': result[1],
                    })
                    fuzzy_matches += 1
    
    print(f"  Fuzzy matches: {fuzzy_matches:,}")
    print(f"  Total cross-references: {len(matches):,}")
    return matches


# ============================================================
# Step 7: Identify bundled donations
# ============================================================
def find_bundled_donations(contributions):
    """Find potential bundled donations (multiple employees of same employer donating same day to same candidate)."""
    bundles = defaultdict(list)
    
    for c in contributions:
        employer = normalize_name(c['employer'])
        if employer and len(employer) > 3:
            key = (employer, c['date'], c['cpf_id'])
            bundles[key].append(c)
    
    # Filter to bundles of 3+ donations on same day from same employer
    bundled = []
    for (employer, date, cpf_id), donors in bundles.items():
        if len(donors) >= 3:
            total = sum(d['amount'] for d in donors)
            bundled.append({
                'employer': employer,
                'date': date,
                'candidate_name': donors[0]['candidate_name'],
                'candidate_office': donors[0]['candidate_office'],
                'num_donors': len(donors),
                'total_amount': total,
                'donor_names': '; '.join(f"{d['donor_first']} {d['donor_last']}" for d in donors),
            })
    
    bundled.sort(key=lambda x: x['total_amount'], reverse=True)
    print(f"  Bundled donation events (3+ donors, same employer/day): {len(bundled):,}")
    return bundled


# ============================================================
# Main
# ============================================================
def main():
    os.makedirs('output', exist_ok=True)
    os.makedirs('scripts', exist_ok=True)
    
    print("=" * 60)
    print("BOSTON CORRUPTION INVESTIGATION: CROSS-DATASET ANALYSIS")
    print("=" * 60)
    
    # Step 1: Load Boston candidates
    print("\n[1/7] Loading Boston candidates...")
    candidates, boston_cpf_ids = load_boston_candidates()
    
    # Step 2: Load reports
    print("\n[2/7] Loading campaign finance reports...")
    report_to_cpf, boston_reports = load_reports(boston_cpf_ids)
    
    # Step 3: Load contributions
    print("\n[3/7] Loading contributions to Boston candidates...")
    contributions = load_boston_contributions(boston_reports, report_to_cpf, candidates)
    
    # Step 4: Load contracts
    print("\n[4/7] Loading city contracts...")
    contracts_df = pd.read_csv('data/contracts.csv', low_memory=False)
    print(f"  Total contracts: {len(contracts_df):,}")
    
    # Step 5: Build vendor map
    print("\n[5/7] Building vendor entity map...")
    vendor_map = build_vendor_map(contracts_df)
    
    # Step 6: Cross-reference
    print("\n[6/7] Cross-referencing donors with contractors...")
    matches = cross_reference(contributions, vendor_map)
    
    # Step 7: Find bundled donations
    print("\n[7/7] Detecting bundled donations...")
    bundled = find_bundled_donations(contributions)
    
    # ============================================================
    # Output Results
    # ============================================================
    print("\n" + "=" * 60)
    print("WRITING OUTPUT FILES")
    print("=" * 60)
    
    # Write cross-reference matches
    if matches:
        matches_df = pd.DataFrame(matches)
        matches_df.to_csv('output/donor_contractor_matches.csv', index=False)
        print(f"\n[✓] output/donor_contractor_matches.csv ({len(matches)} records)")
        
        # Summary by vendor
        vendor_summary = matches_df.groupby('vendor_name').agg(
            total_donations=('donation_amount', 'sum'),
            num_donations=('donation_amount', 'count'),
            num_candidates=('candidate_name', 'nunique'),
            candidates=('candidate_name', lambda x: '; '.join(sorted(set(x)))),
            sole_source=('vendor_sole_source', 'first'),
            contract_value=('vendor_total_value', 'first'),
        ).sort_values('total_donations', ascending=False)
        vendor_summary.to_csv('output/vendor_donation_summary.csv')
        print(f"[✓] output/vendor_donation_summary.csv ({len(vendor_summary)} vendors)")
    else:
        print("\n[!] No cross-reference matches found")
    
    # Write bundled donations
    if bundled:
        bundled_df = pd.DataFrame(bundled)
        bundled_df.to_csv('output/bundled_donations.csv', index=False)
        print(f"[✓] output/bundled_donations.csv ({len(bundled)} events)")
    else:
        print("[!] No bundled donations detected")
    
    # Write red flags (sole source vendors who are also campaign donors)
    red_flags = [m for m in matches if m.get('vendor_sole_source')]
    if red_flags:
        red_flags_df = pd.DataFrame(red_flags)
        red_flags_df.to_csv('output/red_flags.csv', index=False)
        print(f"[✓] output/red_flags.csv ({len(red_flags)} records)")
    
    # Write comprehensive JSON summary
    summary = {
        'analysis_timestamp': datetime.now().isoformat(),
        'data_sources': {
            'contracts': {
                'file': 'data/contracts.csv',
                'record_count': len(contracts_df),
                'source': 'data.boston.gov'
            },
            'campaign_finance': {
                'file': 'data/ocpf_contributions/report-items.txt',
                'source': 'Massachusetts OCPF',
                'boston_candidates': len(boston_cpf_ids),
                'boston_contributions': len(contributions),
            }
        },
        'cross_reference_results': {
            'total_matches': len(matches),
            'exact_matches': sum(1 for m in matches if m.get('confidence') == 'high'),
            'fuzzy_matches': sum(1 for m in matches if m.get('confidence') == 'probable'),
            'unique_vendors_matched': len(set(m['vendor_name'] for m in matches)) if matches else 0,
            'sole_source_vendor_matches': len(red_flags),
        },
        'bundled_donations': {
            'total_events': len(bundled),
            'total_donations_bundled': sum(b['total_amount'] for b in bundled) if bundled else 0,
        },
        'top_matched_vendors': [],
        'top_bundled_employers': [],
        'red_flag_vendors': [],
    }
    
    if matches:
        # Top vendors by donation amount
        vendor_donations = defaultdict(lambda: {'total': 0, 'count': 0, 'candidates': set(), 'sole_source': False, 'contract_value': 0})
        for m in matches:
            v = vendor_donations[m['vendor_name']]
            v['total'] += m['donation_amount']
            v['count'] += 1
            v['candidates'].add(m['candidate_name'])
            v['sole_source'] = m['vendor_sole_source']
            v['contract_value'] = m['vendor_total_value']
        
        top_vendors = sorted(vendor_donations.items(), key=lambda x: x[1]['total'], reverse=True)[:20]
        summary['top_matched_vendors'] = [
            {
                'vendor': name,
                'total_donations': info['total'],
                'donation_count': info['count'],
                'candidates': list(info['candidates']),
                'sole_source': info['sole_source'],
                'contract_value': info['contract_value'],
            }
            for name, info in top_vendors
        ]
        
        # Red flag vendors (sole source + donations)
        rf_vendors = defaultdict(lambda: {'total_donations': 0, 'count': 0, 'contract_value': 0, 'candidates': set()})
        for m in red_flags:
            v = rf_vendors[m['vendor_name']]
            v['total_donations'] += m['donation_amount']
            v['count'] += 1
            v['contract_value'] = m['vendor_total_value']
            v['candidates'].add(m['candidate_name'])
        
        summary['red_flag_vendors'] = sorted([
            {
                'vendor': name,
                'total_donations': info['total_donations'],
                'donation_count': info['count'],
                'contract_value': info['contract_value'],
                'candidates': list(info['candidates']),
            }
            for name, info in rf_vendors.items()
        ], key=lambda x: x['contract_value'], reverse=True)[:20]
    
    if bundled:
        summary['top_bundled_employers'] = bundled[:20]
    
    with open('output/cross_link_analysis.json', 'w') as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"[✓] output/cross_link_analysis.json")
    
    # Print key findings
    print("\n" + "=" * 60)
    print("KEY FINDINGS")
    print("=" * 60)
    
    print(f"\n  Boston candidates identified: {len(boston_cpf_ids)}")
    print(f"  Contributions to Boston candidates: {len(contributions):,}")
    print(f"  Contractor-donor cross-references: {len(matches):,}")
    print(f"  Sole-source vendor red flags: {len(red_flags):,}")
    print(f"  Bundled donation events: {len(bundled):,}")
    
    if matches:
        print(f"\n  Top 5 matched vendors (by donation total):")
        seen = set()
        count = 0
        for m in sorted(matches, key=lambda x: x['donation_amount'], reverse=True):
            if m['vendor_name'] not in seen and count < 5:
                seen.add(m['vendor_name'])
                count += 1
                ss = " ⚠️ SOLE SOURCE" if m['vendor_sole_source'] else ""
                print(f"    {m['vendor_name']}: ${m['donation_amount']:,.2f} -> {m['candidate_name']}{ss}")


if __name__ == '__main__':
    main()

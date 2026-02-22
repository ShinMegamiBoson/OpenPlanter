#!/usr/bin/env python3
"""
Entity Resolution & Cross-Linking Pipeline
Links Boston contract vendors to OCPF campaign finance donors/employers.
"""

import csv
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime

# ============================================================
# STEP 1: Extract Boston candidate CPF_IDs from candidates.txt
# ============================================================

def load_boston_candidates(candidates_file):
    """Load Boston City Councilor and Mayoral candidates."""
    candidates = {}  # cpf_id -> {first, last, office, district}
    with open(candidates_file, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.reader(f, delimiter='\t')
        header = next(reader)
        # Find column indices
        cols = {h.strip().strip('"'): i for i, h in enumerate(header)}
        
        cpf_idx = 0  # CPF ID is first column
        first_idx = cols.get('Candidate First Name', 4)
        last_idx = cols.get('Candidate Last Name', 5)
        city_idx = cols.get('Candidate City', 7)
        office_idx = cols.get('Office Type Sought', 20)
        district_idx = cols.get('District Name Sought', 21)
        
        for row in reader:
            if len(row) <= max(cpf_idx, office_idx, district_idx, city_idx):
                continue
            cpf_id = row[cpf_idx].strip().strip('"')
            office = row[office_idx].strip().strip('"')
            district = row[district_idx].strip().strip('"')
            city = row[city_idx].strip().strip('"')
            first = row[first_idx].strip().strip('"')
            last = row[last_idx].strip().strip('"')
            
            is_boston = False
            if office in ('City Councilor', 'Mayoral'):
                if 'Boston' in district or 'Boston' in city:
                    is_boston = True
                # Also catch Boston mayoral candidates without Boston in address
                if office == 'Mayoral' and district in ('Boston', 'Local Filer', ''):
                    is_boston = True
            
            if is_boston:
                candidates[cpf_id] = {
                    'first_name': first,
                    'last_name': last,
                    'office': office,
                    'district': district,
                    'city': city,
                    'full_name': f"{first} {last}".strip()
                }
    
    return candidates


# ============================================================
# STEP 2: Link candidates to reports across all years
# ============================================================

def load_reports_for_candidates(years, base_dir, cpf_ids):
    """Load report_id -> cpf_id mapping for Boston candidates across all years."""
    report_to_cpf = {}  # report_id -> cpf_id
    report_info = {}    # report_id -> {year, filing_date, ...}
    
    for year in years:
        reports_file = os.path.join(base_dir, 'yearly', str(year), 'reports.txt')
        if not os.path.exists(reports_file):
            print(f"  Warning: {reports_file} not found")
            continue
        
        count = 0
        with open(reports_file, 'r', encoding='utf-8', errors='replace') as f:
            reader = csv.reader(f, delimiter='\t')
            header = next(reader)
            cols = {h.strip().strip('"'): i for i, h in enumerate(header)}
            
            report_id_idx = 0  # Report_ID
            cpf_id_idx = cols.get('CPF_ID', 2)
            filer_cpf_idx = cols.get('Filer_CPF_ID', 3)
            
            for row in reader:
                if len(row) <= max(report_id_idx, cpf_id_idx, filer_cpf_idx):
                    continue
                rid = row[report_id_idx].strip().strip('"')
                cpf = row[cpf_id_idx].strip().strip('"')
                filer_cpf = row[filer_cpf_idx].strip().strip('"')
                
                # Check if this report belongs to a Boston candidate
                if cpf in cpf_ids or filer_cpf in cpf_ids:
                    matched_cpf = cpf if cpf in cpf_ids else filer_cpf
                    report_to_cpf[rid] = matched_cpf
                    report_info[rid] = {'year': year}
                    count += 1
        
        print(f"  Year {year}: {count} reports matched to Boston candidates")
    
    return report_to_cpf, report_info


# ============================================================
# STEP 3: Extract contributions to Boston candidates
# ============================================================

CONTRIBUTION_TYPES = {
    '201': 'Individual Contribution',
    '202': 'Committee Contribution', 
    '203': 'Union/Association Contribution',
    '204': 'Non-contribution receipt',
    '211': 'Business/Corporation Contribution',
}

def extract_contributions(years, base_dir, report_to_cpf, candidates):
    """Extract all contributions to Boston candidates."""
    contributions = []
    
    for year in years:
        items_file = os.path.join(base_dir, 'yearly', str(year), 'report-items.txt')
        if not os.path.exists(items_file):
            print(f"  Warning: {items_file} not found")
            continue
        
        year_count = 0
        with open(items_file, 'r', encoding='utf-8', errors='replace') as f:
            reader = csv.reader(f, delimiter='\t')
            header = next(reader)
            cols = {h.strip().strip('"'): i for i, h in enumerate(header)}
            
            item_id_idx = 0
            report_id_idx = cols.get('Report_ID', 1)
            type_idx = cols.get('Record_Type_ID', 2)
            date_idx = cols.get('Date', 3)
            amount_idx = cols.get('Amount', 4)
            name_idx = cols.get('Name', 5)
            first_idx = cols.get('First_Name', 6)
            addr_idx = cols.get('Street_Address', 7)
            city_idx = cols.get('City', 8)
            state_idx = cols.get('State', 9)
            zip_idx = cols.get('Zip', 10)
            desc_idx = cols.get('Description', 11)
            occ_idx = cols.get('Occupation', 13)
            emp_idx = cols.get('Employer', 14)
            
            for row in reader:
                if len(row) <= max(report_id_idx, type_idx):
                    continue
                
                rid = row[report_id_idx].strip().strip('"')
                rtype = row[type_idx].strip().strip('"')
                
                # Only contribution types
                if rtype not in CONTRIBUTION_TYPES:
                    continue
                
                # Only Boston candidate reports
                if rid not in report_to_cpf:
                    continue
                
                cpf_id = report_to_cpf[rid]
                candidate = candidates.get(cpf_id, {})
                
                def safe_get(idx, default=''):
                    if idx < len(row):
                        return row[idx].strip().strip('"')
                    return default
                
                try:
                    amount = float(safe_get(amount_idx, '0').replace(',', ''))
                except (ValueError, TypeError):
                    amount = 0.0
                
                contributions.append({
                    'item_id': safe_get(item_id_idx),
                    'report_id': rid,
                    'record_type': rtype,
                    'record_type_desc': CONTRIBUTION_TYPES.get(rtype, 'Unknown'),
                    'date': safe_get(date_idx),
                    'amount': amount,
                    'donor_last_name': safe_get(name_idx),
                    'donor_first_name': safe_get(first_idx),
                    'donor_address': safe_get(addr_idx),
                    'donor_city': safe_get(city_idx),
                    'donor_state': safe_get(state_idx),
                    'donor_zip': safe_get(zip_idx),
                    'description': safe_get(desc_idx),
                    'occupation': safe_get(occ_idx),
                    'employer': safe_get(emp_idx),
                    'candidate_cpf_id': cpf_id,
                    'candidate_name': candidate.get('full_name', ''),
                    'candidate_office': candidate.get('office', ''),
                    'data_year': year,
                })
                year_count += 1
        
        print(f"  Year {year}: {year_count} contributions to Boston candidates")
    
    return contributions


# ============================================================
# STEP 4: Entity Resolution - match vendors to donors/employers
# ============================================================

def normalize_name(name):
    """Normalize a company/organization name for matching."""
    if not name:
        return ''
    name = name.upper().strip()
    # Remove quotes
    name = name.replace('"', '').replace("'", '')
    # Remove common suffixes
    suffixes = [
        r'\bINC\.?\b', r'\bLLC\.?\b', r'\bCORP\.?\b', r'\bLTD\.?\b',
        r'\bCO\.?\b', r'\bCOMPANY\b', r'\bCORPORATION\b', r'\bINCORPORATED\b',
        r'\bL\.?L\.?C\.?\b', r'\bLIMITED\b', r'\bGROUP\b', r'\bSERVICES\b',
        r'\bENTERPRISE[S]?\b', r'\bHOLDINGS?\b', r'\bINTERNATIONAL\b',
        r'\bAMERICA[S]?\b', r'\bASSOCIATES?\b', r'\bPARTNERS?\b',
        r'\bSOLUTIONS?\b', r'\bTECHNOLOG(Y|IES)\b', r'\bCONSULTING\b',
        r'\bMANAGEMENT\b',
    ]
    for suffix in suffixes:
        name = re.sub(suffix, '', name)
    # Remove punctuation
    name = re.sub(r'[.,;:!@#$%^&*()_\-+=\[\]{}|\\/<>~`]', ' ', name)
    # Collapse whitespace
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def normalize_name_aggressive(name):
    """Even more aggressive normalization - just alpha tokens sorted."""
    n = normalize_name(name)
    tokens = sorted(set(n.split()))
    return ' '.join(tokens)


def build_vendor_index(contracts_file):
    """Build vendor name index from contracts data."""
    vendors = {}  # normalized_name -> {original_names, total_value, contracts, depts, ...}
    
    with open(contracts_file, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.DictReader(f)
        for row in reader:
            vendor = row.get('vendor_name1', '').strip()
            if not vendor:
                continue
            
            method = row.get('contract_method_subcategory', '').strip()
            
            norm = normalize_name(vendor)
            if not norm:
                continue
            
            try:
                value = float(row.get('amt_cntrct_max', '0').replace(',', ''))
            except (ValueError, TypeError):
                value = 0.0
            
            dept = row.get('dept_tbl_descr_3_digit', '').strip()
            fy = row.get('fy_cntrct_begin_dt', '').strip()
            contract_id = row.get('cntrct_hdr_cntrct_id', '').strip()
            begin_date = row.get('cntrct_hdr_cntrct_begin_dt', '').strip()
            
            if norm not in vendors:
                vendors[norm] = {
                    'original_names': set(),
                    'total_value': 0,
                    'contract_count': 0,
                    'departments': set(),
                    'fiscal_years': set(),
                    'methods': set(),
                    'sole_source_value': 0,
                    'sole_source_count': 0,
                    'contracts': [],
                }
            
            vendors[norm]['original_names'].add(vendor)
            vendors[norm]['total_value'] += value
            vendors[norm]['contract_count'] += 1
            vendors[norm]['departments'].add(dept)
            vendors[norm]['fiscal_years'].add(fy)
            vendors[norm]['methods'].add(method)
            
            if method in ('Sole Source', 'Limited Competition', 'Emergency'):
                vendors[norm]['sole_source_value'] += value
                vendors[norm]['sole_source_count'] += 1
            
            vendors[norm]['contracts'].append({
                'id': contract_id,
                'value': value,
                'department': dept,
                'method': method,
                'fy': fy,
                'begin_date': begin_date,
            })
    
    return vendors


def match_entities(vendors, contributions):
    """Match contribution employers/donors to contract vendors."""
    
    # Build lookup indexes
    vendor_norm_index = {}  # normalized name -> vendor key
    vendor_token_index = defaultdict(set)  # token -> set of vendor keys
    
    for norm_name in vendors:
        vendor_norm_index[norm_name] = norm_name
        # Also build token index for fuzzy matching
        tokens = norm_name.split()
        for token in tokens:
            if len(token) >= 4:  # Skip short tokens
                vendor_token_index[token].add(norm_name)
    
    # Build aggressive normalization index
    vendor_aggressive_index = {}
    for norm_name in vendors:
        agg = normalize_name_aggressive(list(vendors[norm_name]['original_names'])[0])
        if agg and len(agg) >= 4:
            vendor_aggressive_index[agg] = norm_name
    
    matches = []
    match_stats = defaultdict(int)
    
    # Track unique employer matches
    seen_matches = set()
    
    for c in contributions:
        employer = c.get('employer', '')
        donor_name = f"{c.get('donor_last_name', '')} {c.get('donor_first_name', '')}".strip()
        record_type = c.get('record_type', '')
        
        # Strategy 1: Match employer to vendor (for individual contributions)
        if employer and record_type == '201':
            emp_norm = normalize_name(employer)
            if emp_norm and len(emp_norm) >= 3:
                # Exact match on normalized name
                if emp_norm in vendor_norm_index:
                    match_key = (emp_norm, c['candidate_cpf_id'], 'employer_exact')
                    if match_key not in seen_matches:
                        seen_matches.add(match_key)
                    matches.append({
                        'match_type': 'employer_exact',
                        'confidence': 'high',
                        'vendor_normalized': emp_norm,
                        'vendor_original': list(vendors[emp_norm]['original_names'])[0],
                        'donor_name': donor_name,
                        'employer_raw': employer,
                        'contribution': c,
                    })
                    match_stats['employer_exact'] += 1
                    continue
                
                # Aggressive match
                emp_agg = normalize_name_aggressive(employer)
                if emp_agg in vendor_aggressive_index:
                    vnorm = vendor_aggressive_index[emp_agg]
                    matches.append({
                        'match_type': 'employer_fuzzy',
                        'confidence': 'medium',
                        'vendor_normalized': vnorm,
                        'vendor_original': list(vendors[vnorm]['original_names'])[0],
                        'donor_name': donor_name,
                        'employer_raw': employer,
                        'contribution': c,
                    })
                    match_stats['employer_fuzzy'] += 1
                    continue
                
                # Token overlap match (require >50% of vendor tokens to match)
                emp_tokens = set(emp_norm.split())
                best_overlap = 0
                best_vendor = None
                for token in emp_tokens:
                    if len(token) >= 4 and token in vendor_token_index:
                        for vkey in vendor_token_index[token]:
                            vtokens = set(vkey.split())
                            overlap = len(emp_tokens & vtokens)
                            # Require overlap to be at least 60% of shorter name
                            min_len = min(len(emp_tokens), len(vtokens))
                            if min_len > 0 and overlap / min_len > 0.6 and overlap > best_overlap:
                                best_overlap = overlap
                                best_vendor = vkey
                
                if best_vendor and best_overlap >= 2:
                    matches.append({
                        'match_type': 'employer_token_overlap',
                        'confidence': 'low',
                        'vendor_normalized': best_vendor,
                        'vendor_original': list(vendors[best_vendor]['original_names'])[0],
                        'donor_name': donor_name,
                        'employer_raw': employer,
                        'contribution': c,
                    })
                    match_stats['employer_token_overlap'] += 1
        
        # Strategy 2: Match direct donor to vendor (for committee/business contributions)
        if record_type in ('202', '203', '211'):
            donor_norm = normalize_name(donor_name)
            if donor_norm and len(donor_norm) >= 3:
                if donor_norm in vendor_norm_index:
                    matches.append({
                        'match_type': 'donor_exact',
                        'confidence': 'high',
                        'vendor_normalized': donor_norm,
                        'vendor_original': list(vendors[donor_norm]['original_names'])[0],
                        'donor_name': donor_name,
                        'employer_raw': '',
                        'contribution': c,
                    })
                    match_stats['donor_exact'] += 1
                    continue
                
                # Aggressive match
                donor_agg = normalize_name_aggressive(donor_name)
                if donor_agg in vendor_aggressive_index:
                    vnorm = vendor_aggressive_index[donor_agg]
                    matches.append({
                        'match_type': 'donor_fuzzy',
                        'confidence': 'medium',
                        'vendor_normalized': vnorm,
                        'vendor_original': list(vendors[vnorm]['original_names'])[0],
                        'donor_name': donor_name,
                        'employer_raw': '',
                        'contribution': c,
                    })
                    match_stats['donor_fuzzy'] += 1
    
    return matches, match_stats


# ============================================================
# STEP 5: Red Flag Analysis
# ============================================================

def analyze_red_flags(matches, vendors):
    """Identify red flag patterns."""
    red_flags = []
    
    # Group matches by vendor
    vendor_matches = defaultdict(list)
    for m in matches:
        vendor_matches[m['vendor_normalized']].append(m)
    
    for vnorm, vm_list in vendor_matches.items():
        vendor_info = vendors.get(vnorm, {})
        sole_source_value = vendor_info.get('sole_source_value', 0)
        sole_source_count = vendor_info.get('sole_source_count', 0)
        total_value = vendor_info.get('total_value', 0)
        original_name = list(vendor_info.get('original_names', {vnorm}))[0]
        
        # Count unique donors and total amount
        donors = set()
        total_donated = 0
        candidates_receiving = set()
        dates = []
        
        for m in vm_list:
            c = m['contribution']
            donor_key = f"{c.get('donor_last_name', '')}_{c.get('donor_first_name', '')}"
            donors.add(donor_key)
            total_donated += c.get('amount', 0)
            candidates_receiving.add(c.get('candidate_name', ''))
            if c.get('date'):
                dates.append(c['date'])
        
        # Flag 1: Sole-source vendor whose employees donate
        if sole_source_count > 0:
            red_flags.append({
                'flag_type': 'sole_source_vendor_donor',
                'severity': 'HIGH' if sole_source_value > 1000000 else 'MEDIUM',
                'vendor_name': original_name,
                'vendor_normalized': vnorm,
                'sole_source_value': sole_source_value,
                'sole_source_count': sole_source_count,
                'total_contract_value': total_value,
                'unique_donors': len(donors),
                'total_donated': total_donated,
                'candidates_receiving': list(candidates_receiving),
                'departments': list(vendor_info.get('departments', set())),
                'description': f"Sole-source vendor {original_name} (${sole_source_value:,.0f} in {sole_source_count} contracts) has {len(donors)} donor(s) contributing ${total_donated:,.0f} to {len(candidates_receiving)} Boston candidate(s)",
            })
        
        # Flag 2: Bundled donations (3+ donors from same employer, same candidate)
        candidate_donor_groups = defaultdict(set)
        for m in vm_list:
            c = m['contribution']
            donor_key = f"{c.get('donor_last_name', '')}_{c.get('donor_first_name', '')}"
            candidate_donor_groups[c.get('candidate_name', '')].add(donor_key)
        
        for cand, donor_set in candidate_donor_groups.items():
            if len(donor_set) >= 3:
                red_flags.append({
                    'flag_type': 'bundled_donations',
                    'severity': 'HIGH',
                    'vendor_name': original_name,
                    'vendor_normalized': vnorm,
                    'candidate': cand,
                    'unique_donors': len(donor_set),
                    'donor_names': list(donor_set)[:10],
                    'total_contract_value': total_value,
                    'sole_source_value': sole_source_value,
                    'description': f"{len(donor_set)} employees of {original_name} donated to {cand}",
                })
        
        # Flag 3: Large total donations relative to contract value
        if total_donated > 1000 and total_value > 0:
            red_flags.append({
                'flag_type': 'significant_donor_amount',
                'severity': 'MEDIUM' if total_donated > 5000 else 'LOW',
                'vendor_name': original_name,
                'vendor_normalized': vnorm,
                'total_donated': total_donated,
                'total_contract_value': total_value,
                'sole_source_value': sole_source_value,
                'unique_donors': len(donors),
                'description': f"Vendor {original_name} connections donated ${total_donated:,.0f} total; vendor has ${total_value:,.0f} in contracts (${sole_source_value:,.0f} sole-source)",
            })
    
    # Sort by severity then by donated amount
    severity_order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}
    red_flags.sort(key=lambda x: (severity_order.get(x.get('severity', 'LOW'), 3), -x.get('total_donated', 0) if 'total_donated' in x else 0))
    
    return red_flags


# ============================================================
# MAIN
# ============================================================

def main():
    base_dir = 'data/ocpf_contributions'
    contracts_file = 'data/contracts.csv'
    years = [2019, 2020, 2021, 2022, 2023, 2024, 2025]
    
    print("=" * 60)
    print("ENTITY RESOLUTION & CROSS-LINKING PIPELINE")
    print("=" * 60)
    
    # Step 1: Load Boston candidates
    print("\n[1] Loading Boston candidates...")
    candidates = load_boston_candidates(os.path.join(base_dir, 'candidates.txt'))
    cpf_ids = set(candidates.keys())
    print(f"  Found {len(candidates)} Boston candidates")
    
    # Show some key candidates
    for cpf, info in sorted(candidates.items(), key=lambda x: x[1]['last_name'])[:10]:
        print(f"    CPF {cpf}: {info['full_name']} ({info['office']})")
    
    # Step 2: Link to reports
    print("\n[2] Linking candidates to OCPF reports...")
    report_to_cpf, report_info = load_reports_for_candidates(years, base_dir, cpf_ids)
    print(f"  Total reports linked: {len(report_to_cpf)}")
    
    # Step 3: Extract contributions
    print("\n[3] Extracting contributions to Boston candidates...")
    contributions = extract_contributions(years, base_dir, report_to_cpf, candidates)
    print(f"  Total contributions extracted: {len(contributions)}")
    
    # Stats
    type_counts = defaultdict(int)
    total_amount = 0
    for c in contributions:
        type_counts[c['record_type_desc']] += 1
        total_amount += c['amount']
    print(f"  Total amount: ${total_amount:,.2f}")
    for t, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"    {t}: {count}")
    
    # Step 4: Build vendor index
    print("\n[4] Building vendor index from contracts...")
    vendors = build_vendor_index(contracts_file)
    print(f"  Unique vendor entities (normalized): {len(vendors)}")
    
    # Show top sole-source vendors
    sole_source_vendors = {k: v for k, v in vendors.items() if v['sole_source_count'] > 0}
    print(f"  Sole-source vendors: {len(sole_source_vendors)}")
    
    # Step 5: Entity resolution
    print("\n[5] Running entity resolution (matching employers/donors to vendors)...")
    matches, match_stats = match_entities(vendors, contributions)
    print(f"  Total matches found: {len(matches)}")
    for mtype, count in sorted(match_stats.items(), key=lambda x: -x[1]):
        print(f"    {mtype}: {count}")
    
    # Step 6: Red flag analysis
    print("\n[6] Analyzing red flags...")
    red_flags = analyze_red_flags(matches, vendors)
    print(f"  Total red flags: {len(red_flags)}")
    flag_counts = defaultdict(int)
    for rf in red_flags:
        flag_counts[rf['flag_type']] += 1
    for ft, count in sorted(flag_counts.items()):
        print(f"    {ft}: {count}")
    
    # ============================================================
    # OUTPUT FILES
    # ============================================================
    
    print("\n[7] Writing output files...")
    os.makedirs('output', exist_ok=True)
    
    # 7a: Entity map
    entity_map = {}
    for vnorm, vinfo in sole_source_vendors.items():
        original_names = list(vinfo['original_names'])
        entity_map[vnorm] = {
            'canonical_name': original_names[0],
            'name_variants': original_names,
            'normalized': vnorm,
            'total_contract_value': vinfo['total_value'],
            'sole_source_value': vinfo['sole_source_value'],
            'sole_source_count': vinfo['sole_source_count'],
            'departments': list(vinfo['departments']),
        }
    
    with open('output/entity_map.json', 'w') as f:
        json.dump(entity_map, f, indent=2, default=str)
    print(f"  entity_map.json: {len(entity_map)} sole-source vendor entities")
    
    # 7b: Cross-links CSV
    with open('output/cross_links.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'match_type', 'confidence', 'vendor_name', 'vendor_normalized',
            'donor_name', 'employer', 'amount', 'date', 'candidate_name',
            'candidate_office', 'record_type', 'sole_source_value',
            'total_contract_value', 'item_id'
        ])
        for m in matches:
            c = m['contribution']
            vinfo = vendors.get(m['vendor_normalized'], {})
            writer.writerow([
                m['match_type'],
                m['confidence'],
                m['vendor_original'],
                m['vendor_normalized'],
                m['donor_name'],
                m.get('employer_raw', ''),
                c.get('amount', 0),
                c.get('date', ''),
                c.get('candidate_name', ''),
                c.get('candidate_office', ''),
                c.get('record_type_desc', ''),
                vinfo.get('sole_source_value', 0),
                vinfo.get('total_value', 0),
                c.get('item_id', ''),
            ])
    print(f"  cross_links.csv: {len(matches)} matches")
    
    # 7c: Red flags CSV
    with open('output/red_flags.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'flag_type', 'severity', 'vendor_name', 'description',
            'sole_source_value', 'total_contract_value', 'total_donated',
            'unique_donors', 'departments'
        ])
        for rf in red_flags:
            writer.writerow([
                rf.get('flag_type', ''),
                rf.get('severity', ''),
                rf.get('vendor_name', ''),
                rf.get('description', ''),
                rf.get('sole_source_value', ''),
                rf.get('total_contract_value', ''),
                rf.get('total_donated', ''),
                rf.get('unique_donors', ''),
                '; '.join(rf.get('departments', [])),
            ])
    print(f"  red_flags.csv: {len(red_flags)} flags")
    
    # 7d: Contributions to Boston candidates (full extract)
    with open('output/boston_contributions.csv', 'w', newline='') as f:
        if contributions:
            writer = csv.DictWriter(f, fieldnames=contributions[0].keys())
            writer.writeheader()
            writer.writerows(contributions)
    print(f"  boston_contributions.csv: {len(contributions)} contributions")
    
    # 7e: Summary JSON
    summary = {
        'pipeline_run': datetime.now().isoformat(),
        'boston_candidates': len(candidates),
        'reports_linked': len(report_to_cpf),
        'total_contributions': len(contributions),
        'total_contributed_amount': total_amount,
        'contribution_types': dict(type_counts),
        'vendor_entities': len(vendors),
        'sole_source_vendors': len(sole_source_vendors),
        'entity_matches': len(matches),
        'match_breakdown': dict(match_stats),
        'red_flags_total': len(red_flags),
        'red_flag_breakdown': dict(flag_counts),
        'top_matched_vendors': [],
    }
    
    # Top matched vendors by donation amount
    vendor_donation_totals = defaultdict(lambda: {'total': 0, 'count': 0, 'donors': set(), 'sole_source': 0})
    for m in matches:
        vn = m['vendor_original']
        c = m['contribution']
        vendor_donation_totals[vn]['total'] += c.get('amount', 0)
        vendor_donation_totals[vn]['count'] += 1
        vendor_donation_totals[vn]['donors'].add(m.get('donor_name', ''))
        vinfo = vendors.get(m['vendor_normalized'], {})
        vendor_donation_totals[vn]['sole_source'] = vinfo.get('sole_source_value', 0)
    
    top_vendors = sorted(vendor_donation_totals.items(), key=lambda x: -x[1]['total'])[:20]
    for vname, vdata in top_vendors:
        summary['top_matched_vendors'].append({
            'vendor': vname,
            'total_donated': vdata['total'],
            'contribution_count': vdata['count'],
            'unique_donors': len(vdata['donors']),
            'sole_source_contract_value': vdata['sole_source'],
        })
    
    with open('output/cross_link_summary.json', 'w') as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"  cross_link_summary.json written")
    
    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)
    
    return summary


if __name__ == '__main__':
    main()

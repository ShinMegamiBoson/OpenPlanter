#!/usr/bin/env python3
"""
Statistical Timing Analysis of Campaign Donations vs Contract Award Dates

This script performs a permutation test to determine if donations cluster
suspiciously near contract award dates, focusing on snow removal vendors
and CRITICAL-risk politicians.

Methodology:
1. Load contracts.csv to get contract award dates by vendor
2. Load cross_links.csv to get donation dates by vendor-politician pairs
3. For each vendor-politician pair:
   - Calculate days between each donation and nearest contract award
   - Compute mean_days_to_award
   - Run permutation test: shuffle contract dates 10,000 times
   - Calculate p-value: fraction of permutations with mean <= observed
4. Output results with censored entity names
"""

import pandas as pd
import numpy as np
import json
from datetime import datetime
from scipy import stats
import warnings
warnings.filterwarnings('ignore')

def censor_name(name):
    """Replace name with █ characters of same length"""
    if pd.isna(name) or name == '':
        return name
    return '█' * len(str(name))

def normalize_vendor_name(name):
    """Normalize vendor name for matching"""
    if pd.isna(name):
        return ''
    name = str(name).upper()
    # Remove legal suffixes
    for suffix in [' LLC', ' INC', ' CORP', ' LTD', ' CO', ' CO.', ' INC.', ' CORPORATION', 
                   ',LLC', ',INC', ',CORP', ',LTD', ',CO', ',INC.']:
        name = name.replace(suffix, '')
    # Remove punctuation and normalize whitespace
    name = ''.join(c if c.isalnum() else ' ' for c in name)
    name = ' '.join(name.split())
    return name

def vendor_name_match(name1, name2):
    """Check if two vendor names match (fuzzy)"""
    norm1 = normalize_vendor_name(name1)
    norm2 = normalize_vendor_name(name2)
    
    # Exact match after normalization
    if norm1 == norm2:
        return True
    
    # Check if one is substring of other
    if norm1 in norm2 or norm2 in norm1:
        return True
    
    # Token overlap > 60%
    tokens1 = set(norm1.split())
    tokens2 = set(norm2.split())
    if not tokens1 or not tokens2:
        return False
    overlap = len(tokens1 & tokens2) / max(len(tokens1), len(tokens2))
    return overlap > 0.6

def parse_date(date_str):
    """Parse date from various formats"""
    if pd.isna(date_str):
        return None
    
    # Try different formats
    for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%Y/%m/%d', '%m-%d-%Y']:
        try:
            return datetime.strptime(str(date_str), fmt)
        except:
            continue
    return None

def days_to_nearest_award(donation_date, award_dates):
    """Calculate days from donation to nearest contract award"""
    if not award_dates:
        return None
    
    min_days = None
    for award_date in award_dates:
        days = (donation_date - award_date).days
        if min_days is None or abs(days) < abs(min_days):
            min_days = days
    
    return min_days

def permutation_test(donation_dates, award_dates, n_permutations=1000):
    """
    Perform permutation test to assess if donations cluster near awards.
    
    Null hypothesis: donation timing is independent of contract dates.
    Test: Are observed days-to-nearest-award smaller than expected by chance?
    
    Returns: (mean_observed, p_value, effect_size)
    """
    if not donation_dates or not award_dates:
        return None, None, None
    
    # Calculate observed mean absolute days to nearest award
    observed_days = []
    for don_date in donation_dates:
        days = days_to_nearest_award(don_date, award_dates)
        if days is not None:
            observed_days.append(abs(days))
    
    if not observed_days:
        return None, None, None
    
    observed_mean = np.mean(observed_days)
    
    # Permutation test: shuffle award dates within observed date range
    all_dates = sorted(donation_dates + award_dates)
    date_min, date_max = min(all_dates), max(all_dates)
    
    # Generate random award dates for permutations
    permuted_means = []
    for _ in range(n_permutations):
        # Random dates uniformly distributed in the observation period
        n_awards = len(award_dates)
        random_timestamps = np.random.uniform(
            date_min.timestamp(), 
            date_max.timestamp(), 
            n_awards
        )
        random_award_dates = [datetime.fromtimestamp(ts) for ts in random_timestamps]
        
        # Calculate mean days to nearest random award
        perm_days = []
        for don_date in donation_dates:
            days = days_to_nearest_award(don_date, random_award_dates)
            if days is not None:
                perm_days.append(abs(days))
        
        if perm_days:
            permuted_means.append(np.mean(perm_days))
    
    # P-value: fraction of permutations with mean <= observed
    # (one-tailed test: clustering means SMALLER distances)
    p_value = np.mean([pm <= observed_mean for pm in permuted_means])
    
    # Effect size: how many standard deviations from null mean?
    if permuted_means:
        null_mean = np.mean(permuted_means)
        null_std = np.std(permuted_means)
        effect_size = (null_mean - observed_mean) / null_std if null_std > 0 else 0
    else:
        effect_size = 0
    
    return observed_mean, p_value, effect_size

def main():
    print("Loading data...")
    
    # Load contracts
    contracts = pd.read_csv('data/contracts.csv')
    print(f"Loaded {len(contracts)} contracts")
    
    # Parse contract dates
    contracts['award_date'] = contracts['cntrct_hdr_cntrct_begin_dt'].apply(parse_date)
    contracts = contracts[contracts['award_date'].notna()]
    print(f"  {len(contracts)} with valid dates")
    
    # Load cross-links
    cross_links = pd.read_csv('output/cross_links.csv')
    print(f"Loaded {len(cross_links)} cross-links")
    
    # Parse donation dates
    cross_links['donation_date'] = cross_links['date'].apply(parse_date)
    cross_links = cross_links[cross_links['donation_date'].notna()]
    print(f"  {len(cross_links)} with valid dates")
    
    # Load CRITICAL politicians
    with open('output/politician_risk_scores.json') as f:
        risk_data = json.load(f)
    critical_politicians = [p['candidate_name'] for p in risk_data if p.get('risk_tier') == 'CRITICAL']
    print(f"\nFound {len(critical_politicians)} CRITICAL-risk politicians")
    
    # Load snow vendors
    with open('output/snow_vendor_profiles.json') as f:
        snow_vendors_data = json.load(f)
    snow_vendors = list(snow_vendors_data.keys())
    print(f"Found {len(snow_vendors)} snow removal vendors")
    
    # Create a mapping of cross_link vendor names to snow vendor names using fuzzy matching
    snow_vendor_map = {}
    for cl_vendor in cross_links['vendor_name'].unique():
        for snow_vendor in snow_vendors:
            if vendor_name_match(cl_vendor, snow_vendor):
                snow_vendor_map[cl_vendor] = snow_vendor
                break
    
    print(f"Matched {len(snow_vendor_map)} cross_link vendors to snow vendors")
    
    # Mark vendors as snow vendors
    cross_links['is_snow_vendor'] = cross_links['vendor_name'].map(
        lambda x: x in snow_vendor_map
    )
    cross_links['is_critical_politician'] = cross_links['candidate_name'].isin(critical_politicians)
    
    # Prioritize snow vendors + critical politicians, but analyze all with sufficient data
    # We'll analyze ALL vendor-politician pairs, but tag the high-priority ones
    print(f"\nAnalyzing ALL vendor-politician pairs with sufficient data")
    print(f"  Priority: snow vendors → CRITICAL politicians")
    
    analysis_links = cross_links.copy()
    
    # Group by vendor-politician pairs
    results = []
    pairs_processed = 0
    pairs_skipped = 0
    
    grouped = analysis_links.groupby(['vendor_name', 'candidate_name'])
    print(f"Total vendor-politician pairs: {len(grouped)}")
    
    for (vendor, politician), group in grouped:
        # Only analyze pairs with at least 3 donations for statistical validity
        if len(group) < 3:
            pairs_skipped += 1
            continue
        
        is_snow = group['is_snow_vendor'].iloc[0]
        is_critical = group['is_critical_politician'].iloc[0]
        priority = "🔴 PRIORITY" if (is_snow and is_critical) else ""
        
        print(f"\n{priority} Processing: {vendor} -> {politician}")
        print(f"  {len(group)} donations")
        
        # Get donation dates for this pair
        donation_dates = group['donation_date'].tolist()
        
        # Get contract award dates for this vendor
        vendor_contracts = contracts[contracts['vendor_name1'] == vendor]
        award_dates = vendor_contracts['award_date'].tolist()
        
        print(f"  {len(award_dates)} contract awards")
        
        if not award_dates or len(donation_dates) < 3:
            pairs_skipped += 1
            continue
        
        pairs_processed += 1
        
        # Calculate days to nearest award for each donation
        days_list = []
        for don_date in donation_dates:
            days = days_to_nearest_award(don_date, award_dates)
            if days is not None:
                days_list.append(days)
        
        if not days_list:
            continue
        
        mean_days = np.mean([abs(d) for d in days_list])
        
        # Perform permutation test
        print(f"  Running permutation test (1000 iterations)...")
        _, p_value, effect_size = permutation_test(donation_dates, award_dates, n_permutations=1000)
        
        if p_value is not None:
            significant = p_value < 0.05
            print(f"  Mean days to award: {mean_days:.1f}")
            print(f"  P-value: {p_value:.4f}")
            print(f"  Significant: {significant}")
            
            results.append({
                'vendor': censor_name(vendor),
                'politician': censor_name(politician),
                'is_snow_vendor': bool(is_snow),
                'is_critical_politician': bool(is_critical),
                'n_donations': len(donation_dates),
                'n_contracts': len(award_dates),
                'mean_days_to_award': round(mean_days, 2),
                'median_days_to_award': round(float(np.median([abs(d) for d in days_list])), 2),
                'p_value': round(p_value, 4),
                'effect_size': round(effect_size, 3),
                'significant': significant
            })
    
    # Sort by p-value
    results.sort(key=lambda x: x['p_value'])
    
    print(f"\n\n{'='*80}")
    print(f"ANALYSIS COMPLETE")
    print(f"{'='*80}")
    print(f"Total pairs analyzed: {pairs_processed}")
    print(f"Pairs skipped (insufficient data): {pairs_skipped}")
    print(f"Significant pairs (p < 0.05): {sum(1 for r in results if r['significant'])}")
    print(f"  Snow vendor → CRITICAL politician: {sum(1 for r in results if r['is_snow_vendor'] and r['is_critical_politician'] and r['significant'])}")
    print(f"  Snow vendor → any politician: {sum(1 for r in results if r['is_snow_vendor'] and r['significant'])}")
    print(f"  Any vendor → CRITICAL politician: {sum(1 for r in results if r['is_critical_politician'] and r['significant'])}")
    
    # Save results
    output_file = 'output/timing_statistical_analysis.json'
    with open(output_file, 'w') as f:
        json.dump({
            'metadata': {
                'analysis_date': datetime.now().isoformat(),
                'total_pairs_analyzed': len(results),
                'significant_pairs': sum(1 for r in results if r['significant']),
                'method': 'permutation_test',
                'n_permutations': 1000,
                'significance_threshold': 0.05,
                'focus': 'snow_vendors_and_critical_politicians'
            },
            'results': results
        }, f, indent=2)
    
    print(f"\nResults written to {output_file}")
    
    # Print summary of most significant findings
    print("\n" + "="*80)
    print("TOP 20 MOST SIGNIFICANT TIMING PATTERNS")
    print("="*80)
    for i, r in enumerate(results[:20], 1):
        status = "🚨 SUSPICIOUS" if r['significant'] else "✓ Normal"
        priority_tags = []
        if r['is_snow_vendor']:
            priority_tags.append("SNOW")
        if r['is_critical_politician']:
            priority_tags.append("CRITICAL")
        priority_str = f"[{' + '.join(priority_tags)}]" if priority_tags else ""
        
        print(f"\n#{i} {status} {priority_str}")
        print(f"Vendor:     {r['vendor']}")
        print(f"Politician: {r['politician']}")
        print(f"Donations:  {r['n_donations']} (mean {r['mean_days_to_award']:.1f} days to nearest award)")
        print(f"P-value:    {r['p_value']:.4f} (effect size: {r['effect_size']:.2f} σ)")

if __name__ == '__main__':
    main()

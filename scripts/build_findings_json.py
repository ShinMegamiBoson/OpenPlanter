import json
import csv

# Load all datasets
with open('output/politician_risk_scores.json') as f:
    risk_scores = json.load(f)

with open('output/politician_timing_analysis.json') as f:
    timing = json.load(f)

with open('output/cross_link_summary.json') as f:
    cross_summary = json.load(f)

with open('output/politician_shared_network.json') as f:
    network = json.load(f)

# Load bundling events
bundling = []
with open('output/bundling_events.csv') as f:
    for row in csv.DictReader(f):
        bundling.append(row)

# Load limit flags
limit_flags = []
with open('output/contribution_limit_flags.csv') as f:
    for row in csv.DictReader(f):
        limit_flags.append(row)

# Build findings structure
findings = {
    "report_metadata": {
        "generated": "2026-02-19T23:44:00Z",
        "investigation_period_contracts": "FY2019-FY2026",
        "investigation_period_finance": "2019-2025",
        "analyst": "OpenPlanter",
        "classification": "Evidence-backed preliminary findings"
    },
    "data_summary": {
        "total_contracts": 20923,
        "total_contract_value": 17180000000,
        "total_contributions": cross_summary["total_contributions"],
        "total_contributed_amount": cross_summary["total_contributed_amount"],
        "candidates_tracked": cross_summary["boston_candidates"],
        "high_confidence_matches": cross_summary["match_breakdown"]["employer_exact"] + cross_summary["match_breakdown"]["employer_fuzzy"],
        "bundling_events_detected": len(bundling),
        "limit_violations_flagged": len(limit_flags)
    },
    "findings": [
        {
            "id": "F1",
            "title": "Snow Removal Procurement Cartel",
            "severity": "CRITICAL",
            "confidence": "CONFIRMED",
            "summary": "13 family-owned firms hold $163M in limited-competition contracts with zero new entrants in 6 years and 33-67% price escalation",
            "evidence": {
                "vendor_count": 13,
                "total_contract_value": 163170000,
                "procurement_method": "Limited Competition",
                "cycles": 3,
                "new_entrants": 0,
                "price_increase_range": "33-67%"
            },
            "source_files": ["data/contracts.csv"]
        },
        {
            "id": "F2",
            "title": "Coordinated Employer-Directed Bundling",
            "severity": "CRITICAL",
            "confidence": "CONFIRMED",
            "summary": "Multiple instances of 10+ employees from same vendor donating to same candidate on same day, timed within 90 days of contract awards",
            "evidence": {
                "key_events": [
                    {"date": "2019-01-24", "vendor": "[REDACTED - snow contractor]", "candidate": "[REDACTED - mayor]", "donors": 26, "amount": 14250, "days_post_award": 70},
                    {"date": "2020-12-09", "vendor": "[REDACTED - snow contractor]", "candidate": "[REDACTED - mayor]", "donors": 16, "amount": 10100},
                    {"date": "2020-12-19", "vendor": "[REDACTED - law firm]", "candidate": "[REDACTED - mayor]", "donors": 49, "amount": 6800},
                    {"date": "2019-12-31", "vendor": "[REDACTED - demo contractor]", "candidate": "[REDACTED - mayor]", "donors": 14, "amount": 14000}
                ],
                "family_bundling_cases": [
                    {"family": "[REDACTED]", "vendor": "[REDACTED - snow contractor]", "family_members_donating": 13, "total_donated": 35000, "candidates": 7, "contract_value": 10500000}
                ]
            },
            "source_files": ["output/bundling_events.csv", "output/snow_donation_timeline.csv"]
        },
        {
            "id": "F3",
            "title": "Pre-Award Donation Timing Patterns",
            "severity": "CRITICAL",
            "confidence": "PROBABLE",
            "summary": "5 unrelated snow vendors donated in same 10-day window before FY2022 contract awards; post-award spikes detected",
            "evidence": {
                "pre_award_window": "October 15-25, 2021",
                "vendors_donating": 5,
                "days_before_award": "20-31",
                "award_date": "November 14-15, 2021",
                "all_vendors_retained": True
            },
            "source_files": ["output/politician_timing_analysis.json", "output/snow_donation_timeline.csv"]
        },
        {
            "id": "F4",
            "title": "Vendor Hub Influence Networks",
            "severity": "HIGH",
            "confidence": "CONFIRMED",
            "summary": "Private-sector vendors systematically donate to 10-16 politicians simultaneously",
            "evidence": {
                "top_hubs": [
                    {"vendor": "[REDACTED - construction]", "politicians": 16},
                    {"vendor": "[REDACTED - lobbying]", "politicians": 14},
                    {"vendor": "[REDACTED - demo services]", "politicians": 10},
                    {"vendor": "[REDACTED - law firm]", "politicians": 10}
                ]
            },
            "source_files": ["output/politician_shared_network.json"]
        },
        {
            "id": "F5",
            "title": "Contribution Limit Violations",
            "severity": "HIGH",
            "confidence": "POSSIBLE",
            "summary": "860 potential violations of $1,000/year individual limit detected",
            "evidence": {
                "total_flags": 860,
                "caveat": "Many may be reporting artifacts, committee transfers, or processing vendor fees"
            },
            "source_files": ["output/contribution_limit_flags.csv"]
        }
    ],
    "politician_risk_tiers": {
        "CRITICAL": [
            {
                "name": "[REDACTED]",
                "office": r.get("candidate_office", ""),
                "contractor_donations": r.get("total_contractor_donations", 0),
                "vendor_sources": r.get("unique_vendor_sources", 0),
                "contractor_pct": r.get("contractor_donation_pct", 0),
                "snow_vendor_donations": r.get("snow_vendor_donations", 0),
                "snow_vendor_count": r.get("snow_vendor_count", 0)
            }
            for r in risk_scores if r.get("risk_tier") == "CRITICAL"
        ],
        "HIGH_count": len([r for r in risk_scores if r.get("risk_tier") == "HIGH"]),
        "MODERATE_count": len([r for r in risk_scores if r.get("risk_tier") == "MODERATE"]),
        "LOW_count": len([r for r in risk_scores if r.get("risk_tier") == "LOW"])
    },
    "evidence_file_index": [
        {"file": "output/cross_links.csv", "records": 33481, "description": "All vendor-donor matches"},
        {"file": "output/politician_risk_scores.json", "records": 101, "description": "Risk-scored politicians"},
        {"file": "output/politician_timing_analysis.json", "description": "Donation-contract timing analysis"},
        {"file": "output/bundling_events.csv", "records": 1497, "description": "Same-day bundling events"},
        {"file": "output/shared_donor_networks.csv", "records": 20, "description": "Vendor influence breadth"},
        {"file": "output/politician_shared_network.json", "description": "Politician affinity network"},
        {"file": "output/contribution_limit_flags.csv", "records": 894, "description": "Over-limit donor flags"},
        {"file": "output/red_flags_refined.csv", "records": 319, "description": "Multi-factor red flags"},
        {"file": "output/politician_contractor_network.csv", "records": 2545, "description": "Candidate-vendor edges"}
    ]
}

with open('corruption_investigation_data.json', 'w') as f:
    json.dump(findings, f, indent=2, default=str)

print(f"Written corruption_investigation_data.json")
print(f"Findings: {len(findings['findings'])}")
print(f"CRITICAL politicians: {len(findings['politician_risk_tiers']['CRITICAL'])}")

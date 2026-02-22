# OSHA Inspection Data

## Summary

The U.S. Department of Labor's Occupational Safety and Health Administration (OSHA) publishes comprehensive enforcement data covering approximately 90,000 workplace inspections conducted annually. The dataset includes inspection case details, violation citations, penalty assessments, accident investigations, and strategic enforcement program codes. This data is essential for investigating workplace safety compliance, identifying repeat violators, and cross-referencing corporate safety records with contracts, permits, and political contributions.

## Access Methods

**DOL Open Data Portal API (preferred)**: The Department of Labor provides a modernized REST API through its Open Data Portal at `data.dol.gov`.

```
Base URL: https://data.dol.gov/get/
API Registration: https://dataportal.dol.gov/api-keys
```

Authentication requires a free API key sent via the `X-API-KEY` HTTP header.

**Key Endpoints**:

| Endpoint | Contents |
|----------|----------|
| `https://data.dol.gov/get/inspection` | OSHA inspection metadata and case details |
| `https://data.dol.gov/get/violation` | Citation and violation details linked to inspections |
| `https://data.dol.gov/get/accident` | OSHA accident investigation records |
| `https://data.dol.gov/get/strategic_codes` | Strategic program codes (NEP, LEP) tied to inspections |

**Query Parameters**:
- `top=N` — Limit results (default 100, max 200 per request)
- `skip=N` — Offset for pagination
- `filter=JSON` — Filter by field conditions (eq, neq, gt, lt, in, not_in)
- `fields=comma,separated,list` — Select specific fields
- `sort_by=field_name` — Sort by field
- `sort=asc|desc` — Sort direction

Response format: JSON (default), XML available via `/format/xml` suffix.

**Rate Limits**: Not explicitly documented; API key required for all requests.

**Bulk Download**: The DOL Enforcement Data Catalog at `enforcedata.dol.gov` provides data dictionary and bulk download options, updated daily.

**Legacy Interface**: The OSHA Inspection Lab (`enforcedata.dol.gov/views/oshaLab.php`) offers a web-based search interface but is being phased out in favor of the Open Data Portal.

## Data Schema

### Inspection Table (osha_inspection)

Core inspection metadata for each OSHA compliance investigation.

| Field | Description |
|-------|-------------|
| `activity_nr` | Unique inspection identifier (primary key) |
| `reporting_id` | OSHA area office identifier |
| `state_flag` | State or federal OSHA jurisdiction |
| `estab_name` | Establishment name (employer) |
| `site_address`, `site_city`, `site_state`, `site_zip` | Inspection site location |
| `naics_code` | 6-digit North American Industry Classification System code |
| `sic_code` | 4-digit Standard Industrial Classification code (legacy) |
| `owner_type` | A = Private, B = Local govt, C = State govt, D = Federal govt |
| `owner_code` | Specific owner/operator code |
| `adv_notice` | Y/N — Whether employer received advance notice |
| `safety_hlth` | S = Safety, H = Health, X = Both |
| `sic_code` | Standard Industrial Classification code |
| `naics_code` | North American Industry Classification System code |
| `insp_type` | Inspection type (A = Accident, B = Complaint, C = Referral, etc.) |
| `insp_scope` | A = Complete, B = Partial, C = Records only, D = No inspection |
| `why_no_insp` | Reason code if inspection not conducted |
| `union_status` | A = Union, B = Non-union, C = Unknown |
| `safety_manuf` | Y/N — Manufacturing establishment flag |
| `safety_const` | Y/N — Construction site flag |
| `safety_marit` | Y/N — Maritime industry flag |
| `safety_trans` | Y/N — Transportation flag |
| `safety_longshore` | Y/N — Longshore/harbor work flag |
| `nr_in_estab` | Number of employees at establishment |
| `open_date` | Inspection opening date |
| `case_mod_date` | Last case modification date |
| `close_conf_date` | Closing conference date |
| `close_case_date` | Case closure date |

### Violation Table (osha_violation)

Citation and penalty details linked to inspections via `activity_nr`.

| Field | Description |
|-------|-------------|
| `activity_nr` | Links to inspection table (foreign key) |
| `citation_id` | Citation identifier within inspection |
| `delete_flag` | D = Deleted, null = Active |
| `standard` | OSHA standard violated (e.g., 1926.501(b)(13)) |
| `viol_type` | S = Serious, W = Willful, R = Repeat, O = Other |
| `issuance_date` | Citation issuance date |
| `abate_date` | Required abatement date |
| `abate_complete` | Actual abatement completion date |
| `current_penalty` | Current penalty amount (may differ from initial) |
| `initial_penalty` | Initial penalty assessed |
| `final_order_date` | Date of final order |
| `nr_instances` | Number of violation instances |
| `nr_exposed` | Number of employees exposed to hazard |
| `rec` | A = Accident-related, B = Health, C = Safety |
| `gravity` | Gravity rating (01-10, higher = more severe) |
| `emphasis` | Y/N — Emphasis program flag |
| `hazcat` | Hazard category code |
| `fta_insp_nr` | Failure-to-abate parent inspection number |
| `fta_issuance_date` | Failure-to-abate original citation date |
| `fta_penalty` | Failure-to-abate penalty |
| `hazsub` | Hazardous substance code |

### Accident Table (osha_accident)

Accident investigation reports linked to inspections.

| Field | Description |
|-------|-------------|
| `summary_nr` | Unique accident summary identifier (primary key) |
| `activity_nr` | Links to inspection table |
| `reporting_id` | OSHA area office |
| `event_date` | Date of accident/incident |
| `event_desc` | Narrative description |
| `event_keyword` | Keyword tags (amputation, fall, struck-by, etc.) |
| `insp_type` | Inspection type triggered by accident |
| `total_injuries` | Total workers injured |
| `total_fatalities` | Total worker fatalities |
| `hosp` | Number hospitalized |
| `amputation` | Number of amputations |
| `degree_of_injury` | Severity classification |

### Strategic Codes Table (osha_strategic_codes)

Links inspections to national/local emphasis programs.

| Field | Description |
|-------|-------------|
| `activity_nr` | Links to inspection table |
| `prog_type` | NEP = National Emphasis Program, LEP = Local Emphasis Program, SP = Strategic Plan |
| `prog_value` | Program identifier code |

## Coverage

- **Jurisdiction**: United States (all 50 states + territories). Covers federal OSHA and state plan jurisdictions.
- **Time range**: 1970-present (database inception with OSH Act passage). Complete digital records from ~1980 forward.
- **Update frequency**: Daily updates to enforcement data catalog; API reflects near-real-time data (typically 24-48 hour lag from field inspections).
- **Volume**: ~90,000 inspections per year; cumulative database contains millions of inspection records and violation citations since 1970.

## Cross-Reference Potential

### High-Value Joins

- **Corporate Registries**: Match `estab_name` to business entity records (Secretary of State filings) to identify corporate officers, parent companies, and DBAs.
- **Government Contracts**: Cross-reference `estab_name` against municipal/state/federal contractor databases to identify safety violators receiving public contracts.
- **Business Permits & Licenses**: Join on `site_address` and `estab_name` to correlate safety violations with building permits, zoning variances, liquor licenses, etc.
- **Campaign Finance**: Match corporate donors and contributor employers to OSHA inspection histories and penalty assessments.
- **Workers' Compensation Claims**: Link `activity_nr` and accident dates to state workers' comp databases to verify injury reporting.
- **EPA Enforcement**: Cross-reference `naics_code` and `site_address` with EPA violation data for environmental and occupational health overlaps.

**Join Keys**:
- Employer name: `estab_name` (requires fuzzy matching / entity resolution)
- Location: `site_address`, `site_city`, `site_state`, `site_zip` (geocoding recommended)
- Industry: `naics_code` (6-digit), `sic_code` (4-digit legacy)
- Corporate identifiers: FEIN/EIN not included in OSHA data; must resolve via external corporate registries

## Data Quality

**Known Issues**:

1. **Inconsistent Employer Names**: `estab_name` is free-text with no standardization. Same company may appear as "ABC Corp", "ABC Corporation", "ABC Co.", "ABC Corp Inc", etc. Entity resolution required for accurate joins.

2. **Missing Geographic Data**: `site_address` sometimes incomplete or missing for mobile worksites (construction, transportation). Geocoding success rate ~85-90%.

3. **Penalty Adjustments**: `current_penalty` often differs from `initial_penalty` due to settlements, contests, and reductions. Use `current_penalty` for financial analysis.

4. **State Plan Variations**: State-run OSHA programs (e.g., California Cal/OSHA, Washington L&I) may have different citation types, penalty structures, and data completeness. `state_flag` differentiates federal vs. state jurisdictions.

5. **Deleted Records**: Citations may be vacated or deleted (`delete_flag = 'D'`). Always filter for active citations in violation queries.

6. **Case Closure Lag**: Open inspections (`close_case_date = NULL`) may remain in the database for months/years pending litigation or abatement verification.

7. **NAICS/SIC Accuracy**: Industry codes are self-reported by employers during inspection and may be misclassified. Verify critical industry filters manually.

8. **Date Formats**: All dates in YYYY-MM-DD format (ISO 8601). Null dates appear as empty fields in JSON responses.

## Acquisition Script

See `scripts/fetch_osha.py` for a Python stdlib implementation using `urllib.request`. The script queries the DOL inspection endpoint with optional filters (state, date range, establishment name) and outputs JSON or CSV.

**Usage**:
```bash
python scripts/fetch_osha.py --state MA --limit 50 --output inspections.json
python scripts/fetch_osha.py --help
```

## Legal & Licensing

**Public Domain**: OSHA enforcement data is published under 29 CFR § 1904 (OSHA Recordkeeping Rule) and is considered public information under the Freedom of Information Act (FOIA) 5 U.S.C. § 552. No restrictions on redistribution or derived works.

**Privacy**: Personally identifiable information (PII) such as worker names, Social Security numbers, and medical details are redacted from public datasets per FOIA Exemption 6 (personal privacy). Only establishment-level data is published.

**Citation Contests**: Employers may contest citations through OSHRC (Occupational Safety and Health Review Commission). Contested citations appear in the database with `final_order_date = NULL` until adjudication.

**Terms of Use**: The DOL Open Data Portal does not impose licensing restrictions. Standard attribution to "U.S. Department of Labor, OSHA Enforcement Database" is recommended.

## References

- **DOL Open Data Portal**: https://dataportal.dol.gov
- **API Documentation**: https://dataportal.dol.gov/pdf/dol-api-user-guide.pdf (updated 08/05/2024)
- **OSHA Enforcement Data Catalog**: https://enforcedata.dol.gov/views/data_catalogs.php
- **OSHA Inspection Lab**: https://enforcedata.dol.gov/views/oshaLab.php
- **Data Dictionary**: https://enforcedata.dol.gov/views/lab/oshaInspection/datadict_text.php
- **GitHub Issues (API)**: https://github.com/USDepartmentofLabor/DOLAPI/issues
- **OSHA Data Portal**: https://www.osha.gov/data
- **OSHA Inspection Detail Definitions**: https://www.osha.gov/data/inspection-detail-definitions
- **Developer Portal**: https://developer.dol.gov/health-and-safety/dol-osha-enforcement/
- **Contact**: data@dol.gov (API/data portal questions), osha.data@dol.gov (inspection data questions)

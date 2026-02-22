# SAM.gov (System for Award Management)

## Summary

The System for Award Management (SAM.gov) is the U.S. government's central registry for federal contractors and grantees. Maintained by the General Services Administration (GSA), SAM.gov provides two critical datasets for investigations: entity registration data (containing business details, points of contact, and certifications for all entities registered to do business with the federal government) and exclusions data (a list of individuals and entities barred from receiving federal contracts or assistance). These datasets enable tracking of government contractor relationships, identifying debarred entities, and cross-referencing federal vendors with campaign contributions and local contracts.

## Access Methods

**Entity Management API**: Returns detailed entity registration data including UEI, CAGE codes, legal business names, addresses, business types, and registration status.

```
Production: https://api.sam.gov/entity-information/v1-v4/entities
Alpha:      https://api-alpha.sam.gov/entity-information/v1-v4/entities
```

**Exclusions API**: Returns records of individuals and entities currently excluded from federal contracting.

```
Production: https://api.sam.gov/entity-information/v4/exclusions
Alpha:      https://api-alpha.sam.gov/entity-information/v4/exclusions
```

**Exclusions Extract API**: Provides bulk downloads of exclusion data as ZIP or CSV files.

```
Production: https://api.sam.gov/data-services/v1/extracts
Alpha:      https://api-alpha.sam.gov/data-services/v1/extracts
```

**Authentication**: All APIs require an API key. Users obtain keys from their SAM.gov profile under "Public API Key" (https://sam.gov/profile/details for production, alpha.sam.gov for testing).

**Rate Limits**:
- Non-federal users (no role): 10 requests/day
- Non-federal/Federal users (with role): 1,000 requests/day
- Non-federal system accounts: 1,000 requests/day
- Federal system accounts: 10,000 requests/day

**Data Sensitivity Levels**:
- Public: Entity names, addresses, UEI, CAGE codes, business types, exclusion records
- FOUO (CUI): Hierarchy data, security clearances, contact details (requires federal role)
- Sensitive (CUI): Banking info, SSN/TIN/EIN (POST requests only, restricted access)

## Data Schema

### Entity Management API

Key request parameters:
- `ueiSAM`: Unique Entity Identifier (up to 100 per request)
- `cageCode`: Commercial and Government Entity Code (up to 100 per request)
- `legalBusinessName`: Partial or complete name search
- `registrationDate`: Single date or ranges (MM/DD/YYYY format)
- `includeSections`: Filter by entityRegistration, coreData, assertions, pointsOfContact, repsAndCerts
- `format`: JSON (default) or CSV
- `proceedingsData`: Retrieve proceedings information (v3/v4 only)

Response characteristics:
- Synchronous responses: 10 records per page
- Maximum 10,000 records via pagination
- Asynchronous extract API: up to 1,000,000 records

### Exclusions API

Key fields in exclusion records:

| Field | Description |
|-------|-------------|
| `classification` | Entity type (Individual, Firm, Vessel, Special Entity Designation) |
| `exclusionName` | Full name of excluded individual or entity |
| `ueiSAM` | Unique Entity Identifier |
| `cageCode` | CAGE Code if applicable |
| `npi` | National Provider Identifier (healthcare) |
| `exclusionType` | Prohibition/Restriction, Voluntary Exclusion, Ineligible |
| `exclusionProgram` | Reciprocal, Nonprocurement, or Procurement |
| `excludingAgencyCode` | Agency that issued the exclusion |
| `excludingAgencyName` | Full name of excluding agency |
| `activationDate` | Date exclusion became active |
| `terminationDate` | Date exclusion expires/expired |
| `recordStatus` | Active or Inactive |
| `stateProvince` | State/province of excluded entity |
| `country` | Country of excluded entity |
| `addressLine1`, `addressLine2` | Physical address |
| `zipCode` | ZIP or postal code |
| `fascsaOrder` | Federal Acquisition Supply Chain Security Act order flag |

Search operators: AND (&), OR (~), NOT (!), wildcards (*), free-text search (q parameter).

### Exclusions Extract API

Request parameters:
- `fileName`: Specific file name (e.g., `SAM_Exclusions_Public_Extract_V2_22097.ZIP`)
- `fileType`: EXCLUSION, ENTITY, SCR, BIO
- `date`: Date for daily files (MM/DD/YYYY format)
- `api_key`: Required for authentication
- `format`: csv or json

File naming convention:
- Daily exclusions: `SAM_Exclusions_Public_Extract_V2_{YYDDD}.ZIP` (Julian date)
- FASCSA exclusions: `FASCSAOrders{YYDDD}.CSV`

Files generated daily after 7:00 AM Eastern Time.

## Coverage

- **Jurisdiction**: United States federal government (all agencies)
- **Time range**: Current active registrations and exclusions; historical data available via extracts
- **Update frequency**: Real-time for entity registrations; daily extracts for bulk downloads
- **Volume**: Millions of registered entities; tens of thousands of active exclusions

## Cross-Reference Potential

- **Campaign finance data (OCPF, FEC)**: Match federal contractors and excluded entities against campaign contributors and PAC donors to identify potential conflicts of interest
- **Local/state contract databases**: Cross-reference federal contractors with city and state vendors to track entities operating across multiple jurisdictions
- **Corporate registrations**: Link UEI and CAGE codes to state Secretary of Commonwealth records to identify officers and beneficial owners
- **Lobbying disclosures**: Connect excluded or registered entities to lobbying activity
- **Business ownership databases**: Trace entity hierarchies and subsidiaries

Join keys: entity names (fuzzy matching recommended), UEI, CAGE codes, addresses, officer names.

## Data Quality

- Machine-readable JSON and CSV formats
- Entity names may vary (DBA vs legal name, abbreviations)
- Address standardization generally good but some legacy records have inconsistent formatting
- Exclusion records are authoritative and legally binding
- Entity self-reporting relies on accuracy of registrants; data is subject to verification by contracting officers
- Historical address changes not preserved in standard API (only current registration data)
- Some fields restricted based on user access level (public vs FOUO vs Sensitive)

## Acquisition Script

See `scripts/fetch_sam_gov.py` for a Python script that queries the Exclusions Extract API using only standard library modules (urllib, json, argparse).

Usage example:
```bash
# Requires SAM.gov API key from https://sam.gov/profile/details
python scripts/fetch_sam_gov.py --api-key YOUR_API_KEY --file-type EXCLUSION --output exclusions.zip
```

## Legal & Licensing

SAM.gov data is public information collected under the authority of the Federal Acquisition Regulation (FAR) and various federal statutes. Exclusion records are published pursuant to Executive Order 12549, FAR Subpart 9.4, and other federal regulations. No restrictions on redistribution or derived works for public data. FOUO and Sensitive data subject to federal information security requirements.

## References

- SAM.gov homepage: https://sam.gov
- Entity Management API documentation: https://open.gsa.gov/api/entity-api/
- Exclusions API documentation: https://open.gsa.gov/api/exclusions-api/
- Exclusions Extract API documentation: https://open.gsa.gov/api/sam-entity-extracts-api/
- API key registration: https://sam.gov/profile/details
- Federal Acquisition Regulation (FAR): https://www.acquisition.gov/far/
- Data.gov SAM Exclusions catalog: https://catalog.data.gov/dataset/system-for-award-management-sam-public-extract-exclusions
- GSA contact: https://www.fsd.gov/gsafsd_sp (Federal Service Desk)

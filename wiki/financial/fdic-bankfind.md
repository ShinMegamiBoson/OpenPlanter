# FDIC BankFind Suite

## Summary

The Federal Deposit Insurance Corporation (FDIC) BankFind Suite API provides comprehensive public data on all FDIC-insured financial institutions, including institution profiles, branch locations, financial performance metrics, historical structure changes, and bank failures. The dataset covers over 27,000 current institutions and 78,000+ branch locations, with quarterly financial data dating back to 1934. This is the authoritative source for investigating bank ownership, financial health, failure patterns, and geographic footprints.

## Access Methods

**REST API (preferred)**: JSON and CSV responses via RESTful endpoints.

```
Base URL: https://api.fdic.gov/banks/
```

| Endpoint | Description | Record Count |
|----------|-------------|--------------|
| `/institutions` | Institution profiles, regulatory data, financial ratios | ~27,832 active |
| `/locations` | Branch and office locations with addresses | ~78,261 |
| `/failures` | Failed institution details since 1934 | ~4,113 |
| `/history` | Structure change events (mergers, acquisitions, relocations) | ~580,739 |
| `/summary` | Aggregate financial/structure data by year and state | ~7,989 |
| `/financials` | Detailed quarterly Call Report data (1,100+ variables) | ~1,669,800 |

**Authentication**: No API key required as of February 2026 (previously planned but not enforced).

**Rate limits**: Not documented; testing shows the API tolerates multiple concurrent requests.

**Query parameters**:
- `filters` - Elasticsearch query string (see below)
- `fields` - Comma-separated field list (omit for all fields)
- `limit` - Records per response (default: 10, max: 10,000)
- `offset` - Pagination offset
- `sort_by` - Field name for sorting
- `sort_order` - `ASC` or `DESC`
- `format` - `json` or `csv`

**Filter syntax**: Uses Elasticsearch query string with:
- Phrase matching: `NAME:"First Bank"`
- Boolean operators: `STALP:MA AND ACTIVE:1`
- Exclusion: `!(STNAME:"Virginia")`
- Date ranges: `FAILDATE:[2020-01-01 TO 2023-12-31]`
- Numeric ranges: `DEP:[50000 TO *]` (50M+ deposits, in thousands)

**Bulk download**: ZIP/CSV archives available at https://banks.data.fdic.gov/bankfind-suite/bulkData

## Data Schema

### Institutions Endpoint

Key fields for investigation:

| Field | Description |
|-------|-------------|
| `CERT` | Unique FDIC certificate number (primary key) |
| `NAME` | Institution legal name |
| `ADDRESS`, `CITY`, `STALP`, `ZIP` | Physical address |
| `ACTIVE` | 1 = active, 0 = inactive/closed |
| `INSDATE` | Date FDIC insurance granted |
| `ESTYMD` | Establishment date |
| `BKCLASS` | Bank class (N=commercial, SM=state savings, etc.) |
| `CHARTER` | Charter type (0=commercial, 1=stock savings) |
| `REGAGENT` | Primary regulator (OCC, FED, FDIC, STATE) |
| `FED_RSSD` | Federal Reserve RSSD ID (cross-reference key) |
| `RSSDHCR` | Holding company RSSD ID |
| `NAMEHCR` | Holding company name |
| `ASSET`, `DEP`, `NETINC` | Financial metrics (thousands of dollars) |
| `LATITUDE`, `LONGITUDE` | Geocoordinates |
| `CBSA`, `CBSA_NO` | Core Based Statistical Area |
| `OFFDOM`, `OFFFOR` | Count of domestic/foreign offices |
| `STCHRTR` | 1=state-chartered, 0=federal |

### Failures Endpoint

| Field | Description |
|-------|-------------|
| `CERT` | FDIC certificate number |
| `NAME` | Failed institution name |
| `CITY`, `PSTALP` | Location |
| `FAILDATE` | Failure date (M/D/YYYY) |
| `SAVR` | Resolution authority (FDIC, RTC, etc.) |
| `QBFASSET`, `QBFDEP` | Assets/deposits at failure (thousands) |
| `COST` | Estimated FDIC resolution cost |
| `RESTYPE` | Resolution type (FAILURE, ASSISTANCE) |
| `RESTYPE1` | Resolution method (PO=payout, PA=purchase & assumption) |

### Locations Endpoint

| Field | Description |
|-------|-------------|
| `UNINUM` | Unique location ID |
| `CERT` | Institution FDIC certificate (joins to institutions) |
| `NAME` | Institution name |
| `OFFNAME` | Branch/office name |
| `ADDRESS`, `CITY`, `STALP`, `ZIP` | Branch address |
| `LATITUDE`, `LONGITUDE` | Geocoordinates |
| `MAINOFF` | 1=main office, 0=branch |
| `SERVTYPE` | Service type (11=full service, 12=limited service, etc.) |
| `ESTYMD` | Branch establishment date (YYYY-MM-DD) |
| `ACQDATE` | Date acquired (if applicable) |

### History Endpoint

Structure change events (mergers, acquisitions, charter changes, branch relocations):

| Field | Description |
|-------|-------------|
| `CERT` | Institution FDIC certificate |
| `INSTNAME` | Institution name |
| `CHANGECODE`, `REPORT_TYPE` | Event type code |
| `EFFDATE` | Effective date of change |
| `CLASS_CHANGE_FLAG` | 1=class changed |
| `FAILED_*_FLAG` | Various failure-related flags |
| `FRM_*` | "From" values (predecessor institution data) |
| `ACQYEAR`, `PROCYEAR` | Acquisition/processing year |

### Financials Endpoint

Quarterly Call Report data with 1,100+ variables. Key fields:

| Field | Description |
|-------|-------------|
| `CERT` | Institution FDIC certificate |
| `REPDTE` | Report date (YYYYMMDD) |
| `ASSET` | Total assets (thousands) |
| `DEP`, `DEPDOM` | Total deposits, domestic deposits |
| `LNLSNET` | Net loans and leases |
| `NETINC` | Net income |
| `ROAA`, `ROAE` | Return on average assets/equity (%) |
| `EQTOT` | Total equity capital |
| Various ratio fields | Profitability, liquidity, capital adequacy |

## Coverage

- **Jurisdiction**: United States (all 50 states, DC, territories)
- **Time range**: 1934-present (failures); 1984-present (institutions); 2002-present (comprehensive Call Reports)
- **Update frequency**:
  - Institutions/Locations: Daily updates (reflected in index timestamp)
  - Financials: Quarterly (after Call Report filing deadlines)
  - Failures: Updated upon resolution
- **Volume**:
  - 27,832 active institutions (Feb 2026)
  - 78,261 branch locations
  - 4,113 failures since 1934
  - 580,739 structure change events
  - 1.67M quarterly financial records

## Cross-Reference Potential

- **Campaign finance data**: Match contributor employers against bank names; identify financial sector donations.
- **Corporate registries**: Link `RSSDHCR`/`NAMEHCR` (holding company) to state Secretary of State records for ownership structure.
- **Federal Reserve**: Use `FED_RSSD` to join with Federal Reserve National Information Center (NIC) data for detailed ownership trees.
- **Lobbying disclosures**: Cross-reference bank names and holding companies against federal/state lobbying registrants.
- **Contract/procurement data**: Match payee names against banks in government payment records (e.g., Boston Open Checkbook).
- **Real estate records**: Geocode branch locations (`LATITUDE`, `LONGITUDE`) to overlay with property ownership, zoning, or tax data.
- **FDIC enforcement actions**: Combine with FDIC enforcement orders (available at fdic.gov) using `CERT` number.
- **Branch deserts**: Analyze location data against census demographics to identify underbanked areas.

Join keys: `CERT` (FDIC certificate, primary), `FED_RSSD` (Federal Reserve ID), `RSSDHCR` (holding company ID), institution/branch names (fuzzy matching), addresses.

## Data Quality

- **Clean structured data**: JSON responses are well-formatted with consistent schemas.
- **Numeric encoding**: Financial figures in thousands of dollars; some boolean flags use 1/0, others Y/N.
- **Date formats**: Inconsistent across endpoints (YYYYMMDD, MM/DD/YYYY, YYYY-MM-DD).
- **Null handling**: `null` in JSON indicates missing/inapplicable data.
- **Geocoding**: Latitude/longitude included for most institutions and branches; high accuracy.
- **Name standardization**: Legal names generally consistent but may include punctuation variations.
- **Historical completeness**: Pre-1990s data sparser; some older failures lack financial details.
- **Amendment handling**: API returns current data snapshot; no historical versioning of amended reports.
- **Field documentation**: The API lacks comprehensive data dictionaries; field meanings often require consulting FDIC Call Report instructions.

## Acquisition Script

See `scripts/fetch_fdic.py` for a Python standard-library script that queries institutions, failures, locations, history, summary, and financials endpoints. Supports filters, field selection, pagination, and CSV/JSON output.

Example usage:
```bash
# Get all active banks in Massachusetts
python scripts/fetch_fdic.py institutions --filter "STALP:MA AND ACTIVE:1" --limit 100

# Get recent failures
python scripts/fetch_fdic.py failures --filter "FAILDATE:[2020-01-01 TO *]"

# Get branches for a specific bank (CERT=14)
python scripts/fetch_fdic.py locations --filter "CERT:14" --limit 500
```

## Legal & Licensing

All FDIC data is **public domain** under 12 U.S.C. §1819(a)(3) and the Freedom of Information Act (5 U.S.C. §552). No restrictions on redistribution, commercial use, or derived works. The FDIC Terms of Use (https://www.fdic.gov/about/financial-reports/website-privacy-policy) disclaim warranties but impose no licensing requirements.

## References

- **API Documentation**: https://banks.data.fdic.gov/docs/ (OpenAPI YAML definitions)
- **Interactive API explorer**: https://api.fdic.gov/banks/docs/
- **Bulk downloads**: https://banks.data.fdic.gov/bankfind-suite/bulkData
- **Institution search UI**: https://banks.data.fdic.gov/bankfind-suite/bankfind
- **Data dictionary**: Included in bulk download ZIPs and at https://www.fdic.gov/bank-data-guide/
- **Call Report instructions**: https://www.fdic.gov/resources/bankers/call-reports/ (explains financial field definitions)
- **API examples PDF**: https://s3-us-gov-west-1.amazonaws.com/cg-2e5c99a6-e282-42bf-9844-35f5430338a5/downloads/Use_the_API_with_Examples.pdf
- **FDIC press release** (API launch): https://www.fdic.gov/news/press-releases/2020/pr20142.html
- **Python wrapper** (third-party): https://github.com/dpguthrie/bankfind
- **R wrapper** (third-party): https://github.com/bertcarnell/fdic.api
- **Contact**: https://www.fdic.gov/resources/data-tools/bankfind-suite-help/

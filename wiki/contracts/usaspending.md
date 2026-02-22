# USASpending.gov

## Summary

USASpending.gov is the official U.S. government portal for federal spending transparency, publishing comprehensive data on contracts, grants, loans, and other federal awards. Managed by the Department of Treasury's Bureau of the Fiscal Service, the platform aggregates data from the Federal Procurement Data System (FPDS), Federal Award Submission System (FASS), and agency financial systems under the Digital Accountability and Transparency Act (DATA Act). This is the authoritative source for tracking federal contract awards, recipient organizations, and cross-jurisdictional spending patterns essential for corruption and procurement investigations.

## Access Methods

**RESTful API (preferred)**: Free, no authentication required, JSON responses.

```
Base URL: https://api.usaspending.gov/api/v2/
Documentation: https://api.usaspending.gov/docs/endpoints
```

**Key Endpoints**:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/search/spending_by_award/` | POST | Search and filter awards by multiple criteria |
| `/bulk_download/awards/` | POST | Generate bulk CSV downloads by agency/fiscal year |
| `/download/awards/` | POST | Custom award data downloads with filtering |
| `/awards/<AWARD_ID>/` | GET | Detailed information for a specific award |
| `/search/spending_by_transaction/` | POST | Individual transaction-level data |
| `/autocomplete/recipient/` | POST | Search recipients by name or UEI |
| `/autocomplete/awarding_agency/` | POST | Search federal agencies |

**Rate Limits**: None documented; standard HTTP etiquette recommended.

**Bulk Downloads**: Pre-generated ZIP archives by fiscal year and agency available at https://www.usaspending.gov/download_center/award_data_archive (FY2008-present). Archives contain CSV files segmented by award type (contracts, grants, loans, etc.).

**Web Interface**: https://www.usaspending.gov/ — Advanced Search tool with filters and export capabilities (FY2008+).

## Data Schema

### Award Search Response Fields

Core fields available via `/search/spending_by_award/`:

**Universal Award Fields**:

| Field | Description |
|-------|-------------|
| `Award ID` | Generated award identifier (PIID for contracts) |
| `Recipient Name` | Primary recipient organization |
| `Recipient UEI` | Unique Entity Identifier (replaced DUNS in 2022) |
| `Awarding Agency` | Federal agency issuing the award |
| `Awarding Sub Agency` | Sub-agency or bureau |
| `Funding Agency` | Source of funding (may differ from awarding) |
| `Award Amount` | Total obligated amount |
| `Total Outlays` | Actual payments disbursed |
| `Description` | Award description or purpose |
| `Place of Performance City Code` | FIPS city code |
| `Place of Performance State Code` | Two-letter state code |
| `Place of Performance Zip5` | 5-digit ZIP code |
| `Last Modified Date` | Most recent update timestamp |
| `COVID-19 Obligations` | Pandemic-related funding flag |
| `def_codes` | Defense spending codes |

**Contract-Specific Fields**:

| Field | Description |
|-------|-------------|
| `Start Date`, `End Date` | Contract period of performance |
| `Contract Award Type` | Type code (e.g., definitive contract, purchase order) |
| `NAICS` | North American Industry Classification System code |
| `PSC` | Product/Service Code |

**Grant/Loan Fields**:

| Field | Description |
|-------|-------------|
| `CFDA Number` | Catalog of Federal Domestic Assistance number |
| `Assistance Listings` | Program name |
| `SAI Number` | Sub-award identifier |

### Transaction-Level Data

More granular transaction records include modification history, action dates, and transaction-specific obligation changes.

## Coverage

- **Jurisdiction**: Federal government (all agencies, departments, and sub-agencies)
- **Time range**:
  - Award data: **FY2001-present** (via bulk downloads)
  - Advanced Search: **FY2008-present**
  - Financial system data (DATA Act): **Q2 FY2017-present** (January 2017+)
- **Update frequency**:
  - Contract data (FPDS): **Within 5 days** of award/modification
  - DOD/USACE contracts: **90-day delay** due to FPDS publication schedule
  - Bulk archives: Updated quarterly
- **Volume**:
  - ~400 million award records total (FY2001-2025)
  - ~100 million contract actions
  - ~2 million active awards per fiscal year

## Cross-Reference Potential

**High-value joins** for investigation workflows:

- **State/Local Campaign Finance**: Match federal contract recipients (corporate entities, executives, PACs) against state-level donor databases. Join keys: recipient name (fuzzy), UEI, business addresses, principal officers.

- **State Corporate Registries**: Resolve recipient UEI/DUNS to state business registrations, registered agents, and ownership structures.

- **Lobbying Disclosures (Senate LD-2)**: Cross-reference federal contractors with lobbying expenditures and clients. Join keys: recipient name, parent company name.

- **SEC EDGAR Filings**: Match publicly-traded contractors to financial disclosures, 10-K risk factors, and beneficial ownership (Form 4).

- **State/Local Procurement**: Identify contractors active in both federal and municipal markets. Join keys: vendor name, tax ID (when available), address.

- **OpenSecrets/FEC**: Federal PAC contributions from contractor executives and employees.

**Join strategies**: UEI (when available) is the most reliable key post-2022. Pre-2022, DUNS numbers are authoritative. For entity resolution across systems lacking UEI/DUNS, use fuzzy name matching combined with address/ZIP validation and NAICS/industry code alignment.

## Data Quality

**Known Issues** (documented by GAO reports 2022-2024):

- **Incompleteness**: 49 of 152 agencies did not report data to USASpending in FY2022, including some COVID-19 fund recipients.
- **Timeliness**: 18 of 101 agencies missed submission deadlines for Q1 FY2021.
- **Linkage gaps**: 19 agencies failed to submit File C (financial data linking awards to budgets), breaking the award-to-appropriation chain.
- **Inconsistent standards**: Hundreds of billions in obligations labeled "Unknown/Other" for program activity.
- **Name variations**: Recipient names lack standardization (e.g., "IBM Corp", "International Business Machines", "IBM Corporation").
- **Historical data quality**: Pre-FY2017 data predates DATA Act requirements; completeness and accuracy vary significantly by agency.
- **DOD delay**: Defense contracts appear 90+ days after execution.

**Recommendations**:
- Always query by UEI (post-2022) or DUNS (pre-2022) for entity tracking.
- Use recipient autocomplete API to resolve name variants before filtering.
- Cross-validate large awards against agency-specific procurement systems.
- For time-series analysis, account for DOD reporting lag.

## Acquisition Script

See `scripts/fetch_usaspending.py` — stdlib-only Python script for querying the spending API and downloading contract/award data. Supports filtering by agency, date range, award type, and recipient. Outputs JSON or CSV.

**Usage**:
```bash
python scripts/fetch_usaspending.py --award-type contracts \
  --start-date 2023-01-01 --end-date 2023-12-31 \
  --recipient "Acme Corporation" --output contracts_2023.json
```

## Legal & Licensing

Public domain data under the **Digital Accountability and Transparency Act of 2014 (DATA Act, P.L. 113-101)** and **Federal Funding Accountability and Transparency Act of 2006 (FFATA, P.L. 109-282)**. No copyright restrictions. Data may be freely redistributed, analyzed, and republished without attribution requirements. API and bulk downloads subject to standard federal website terms of use (no abusive automated access).

## References

- **Official site**: https://www.usaspending.gov
- **API documentation**: https://api.usaspending.gov/docs/endpoints
- **Bulk downloads**: https://www.usaspending.gov/download_center/award_data_archive
- **DATA Act schema (DAIMS)**: https://fiscal.treasury.gov/data-transparency/DAIMS-current.html
- **FPDS data dictionary**: https://www.fpds.gov/wiki/index.php/FPDS_Data_Dictionary
- **GAO oversight reports**:
  - [Data Quality Assessment 2022](https://www.gao.gov/products/gao-22-104702)
  - [Improvement Opportunities 2024](https://www.gao.gov/products/gao-24-106214)
- **CRS Report R44027**: Tracking Federal Awards (Congress.gov)
- **Analyst's Guide**: https://dt-datalab.usaspending.gov/analyst-guide/
- **API GitHub repository**: https://github.com/fedspendingtransparency/usaspending-api

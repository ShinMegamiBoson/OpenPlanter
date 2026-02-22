# FEC Federal Campaign Finance

## Summary

The Federal Election Commission (FEC) maintains comprehensive campaign finance data for all federal elections (Presidential, Senate, and House races). The data includes candidate registrations, committee filings, itemized contributions, expenditures, independent expenditures, and communication costs. Available through both bulk downloads and a RESTful API (OpenFEC), this is the primary source for federal campaign finance investigations covering all 50 states and U.S. territories.

## Access Methods

**OpenFEC API (preferred for programmatic access)**: RESTful JSON API with comprehensive search and filter capabilities.

```
Base URL: https://api.open.fec.gov/v1/
```

**Authentication**: API key required from api.data.gov. For testing, use `DEMO_KEY` (rate-limited).

**Rate limits**: DEMO_KEY has very low limits; obtain a free API key at https://api.open.fec.gov/developers/ for higher limits. All responses cached for 1 hour (`Cache-Control: public, max-age=3600`).

### Key API Endpoints

| Endpoint | Description |
|----------|-------------|
| `/candidates` | Search and list candidates with filters |
| `/candidate/{id}` | Detailed candidate profile |
| `/candidate/{id}/committees` | Committees associated with candidate |
| `/candidate/{id}/totals` | Aggregated financial totals |
| `/committees` | Search and list committees |
| `/committee/{id}/totals` | Committee financial totals by cycle |
| `/committee/{id}/reports` | Filed reports and disclosures |
| `/schedules/schedule_a/` | Itemized contributions (Schedule A) |
| `/schedules/schedule_b/` | Itemized disbursements (Schedule B) |
| `/schedules/schedule_e/` | Independent expenditures (Schedule E) |

**Common parameters**: `api_key`, `cycle` (election year), `office` (P/H/S), `page`, `per_page`, `sort`, `q` (search term)

**Bulk downloads**: ZIP archives available at https://www.fec.gov/data/browse-data/?tab=bulk-data

| File Category | Coverage | Format |
|---------------|----------|--------|
| Candidate Master | All registered candidates, 1979-2026 | Delimited text |
| Committee Master | All federal committees | Delimited text |
| Individual Contributions | Itemized donations, 1979-2026 | Delimited text |
| Committee-to-Committee | PAC/party contributions, 1979-2026 | Delimited text |
| Operating Expenditures | Disbursements, 2003-2026 | Delimited text |
| House/Senate Campaigns | Active campaign summaries, 1995-2026 | Delimited text |
| Independent Expenditures | IE reports, 2009-2026 | Delimited text |

**Update frequency**: Bulk files updated daily to weekly; API data refreshed within 48 hours of filing.

**Note**: FEC previously offered FTP downloads (ftp.fec.gov) but migrated to web-based downloads. Some bulk files now require Amazon CLI tools for transfer.

## Data Schema

### API Response Structure

All API endpoints return paginated JSON with this structure:

```json
{
  "api_version": "1.0",
  "pagination": {
    "page": 1,
    "per_page": 20,
    "count": 150,
    "pages": 8
  },
  "results": [...]
}
```

### Candidate Records

| Field | Description |
|-------|-------------|
| `candidate_id` | Unique FEC candidate ID (persistent across cycles) |
| `name` | Candidate full name |
| `office` | H (House), S (Senate), P (President) |
| `office_full` | Full office name |
| `state` | Two-letter state code |
| `district` | District number (House only) |
| `party` | Party affiliation |
| `candidate_status` | C (Statutory candidate), F (Future), N (Not yet), P (Prior) |
| `cycles` | Array of election cycles |
| `election_years` | Years candidate appeared on ballot |

### Committee Records

| Field | Description |
|-------|-------------|
| `committee_id` | Unique FEC committee ID |
| `name` | Committee name |
| `designation` | P (Principal), A (Authorized), J (Joint), U (Unauthorized) |
| `committee_type` | H (House), S (Senate), P (Presidential), X (Party), etc. |
| `treasurer_name` | Committee treasurer |
| `street_1`, `city`, `state`, `zip` | Committee address |
| `filing_frequency` | Q (Quarterly), M (Monthly), T (Terminated) |

### Schedule A (Contributions)

| Field | Description |
|-------|-------------|
| `committee_id` | Receiving committee |
| `contributor_name` | Individual/entity name |
| `contributor_city`, `contributor_state`, `contributor_zip` | Address |
| `contributor_employer` | Employer name |
| `contributor_occupation` | Occupation |
| `contribution_receipt_date` | Transaction date |
| `contribution_receipt_amount` | Dollar amount |
| `receipt_type` | Transaction type code |
| `memo_text` | Additional details |

### Schedule B (Expenditures)

| Field | Description |
|-------|-------------|
| `committee_id` | Disbursing committee |
| `recipient_name` | Payee name |
| `recipient_city`, `recipient_state`, `recipient_zip` | Address |
| `disbursement_date` | Transaction date |
| `disbursement_amount` | Dollar amount |
| `disbursement_description` | Purpose |
| `category_code` | Expenditure category |

## Coverage

- **Jurisdiction**: Federal elections (all 50 states + DC, territories)
- **Time range**:
  - Candidate/committee records: 1979-present
  - Individual contributions: 1979-present
  - Operating expenditures: 2003-present
  - Full itemized data: 1979-present
- **Update frequency**:
  - API: Real-time to 48 hours after filing
  - Bulk downloads: Daily to weekly
- **Volume**:
  - ~6,000+ active candidate committees per cycle
  - ~16,000+ total committees (including PACs, Super PACs, parties)
  - Millions of itemized transactions per cycle

## Cross-Reference Potential

- **State campaign finance systems** (e.g., MA OCPF): Link federal candidates' committees to state-level contributions and expenditures
- **Corporate registrations**: Match committee contributors/expenditure recipients to Secretary of State corporate databases
- **Government contracts**: Cross-reference PAC/individual donors with federal contract recipients (USAspending.gov)
- **Lobbying disclosures**: Connect lobbyist employers to campaign donors (senate.gov/lobby, house.gov/lobby)
- **IRS 990 filings**: Match nonprofit contributors to their Form 990 disclosures
- **Property records**: Link contributor addresses to property ownership for wealth analysis

**Join keys**: Candidate/committee IDs (FEC format: C00######, H########, S########, P########), entity names (fuzzy matching), addresses, employer names, dates.

## Data Quality

**Strengths**:
- Standardized FEC IDs for candidates and committees
- Well-structured API with consistent schemas
- Machine-readable JSON (API) and delimited text (bulk)
- Comprehensive coverage mandated by federal law

**Known Issues**:
- **Free-text fields**: Contributor/payee names have inconsistent capitalization and formatting
- **Amended reports**: Bulk files contain only latest versions; historical amendments not preserved
- **Multiple date formats**: Varies by report type and filing method
- **Missing geocoding**: No standardized geographic coordinates; addresses require external geocoding
- **Employer/occupation**: Self-reported, inconsistent abbreviations
- **Bulk file sizes**: Individual contributions files can exceed 1GB compressed
- **FTP deprecation**: Legacy FTP access removed; some users report difficulties with web-based bulk downloads
- **Name resolution**: No canonical entity IDs across filings; requires fuzzy matching for donor/vendor deduplication

## Acquisition Script

See `scripts/fetch_fec.py` for bulk download and API query functionality. Supports:
- API queries with pagination
- Bulk file downloads
- JSON and CSV output formats
- Filtering by cycle, office, state

Example usage:
```bash
# Query candidates via API
python scripts/fetch_fec.py --mode api --endpoint candidates --cycle 2024 --office H --state MA

# Download bulk individual contributions
python scripts/fetch_fec.py --mode bulk --file indiv --cycle 2024
```

## Legal & Licensing

Public domain data under the Freedom of Information Act (FOIA) and Federal Election Campaign Act (52 U.S.C. § 30101 et seq.).

**Restrictions**: Individual contributor names and addresses "may not be sold or used for commercial purposes" (52 U.S.C. § 30111(a)(4)). No restrictions on redistribution for noncommercial, journalistic, or investigative purposes.

## References

- **FEC website**: https://www.fec.gov
- **OpenFEC API documentation**: https://api.open.fec.gov/developers/
- **Bulk downloads**: https://www.fec.gov/data/browse-data/?tab=bulk-data
- **API signup**: https://api.data.gov/signup/
- **GitHub repository**: https://github.com/fecgov/openFEC
- **Legal resources**: https://www.fec.gov/legal-resources/
- **Data tutorials**: https://www.fec.gov/introduction-campaign-finance/data-tutorials/
- **Contact**: APIinfo@fec.gov, (202) 694-1120
- **Sunlight Foundation API guide**: https://sunlightfoundation.com/2015/07/08/openfec-makes-campaign-finance-data-more-accessible-with-new-api-heres-how-to-get-started/

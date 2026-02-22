# ProPublica Nonprofit Explorer / IRS 990

## Summary

ProPublica's Nonprofit Explorer provides searchable access to over 1.8 million nonprofit tax filings (IRS Form 990) submitted electronically since 2001. The dataset includes organization profiles, executive compensation, revenue/expenses, assets/liabilities, and full-text search across 990 filings. This is a critical source for investigating nonprofit finances, cross-referencing charitable foundation grants to political actors, and tracing money flows between tax-exempt organizations and campaign contributors.

## Access Methods

**ProPublica API (preferred)**: RESTful JSON API, no authentication required, no documented rate limits.

```
Base URL: https://projects.propublica.org/nonprofits/api/v2
```

### Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/search.json` | GET | Search organizations by keyword, state, NTEE code, or tax subsection |
| `/organizations/:ein.json` | GET | Retrieve complete profile and filing history for a single EIN |

**Search parameters**:
- `q` — keyword (supports quoted phrases, `+` for required terms, `-` for exclusion)
- `page` — zero-indexed page number (default: 0, 25 results per page)
- `state[id]` — two-letter postal code (e.g., `MA`, `CA`)
- `ntee[id]` — NTEE major group code (1-10: Arts, Education, Health, etc.)
- `c_code[id]` — 501(c) subsection code (3, 4, 5, 6, 7, etc.)

**Response format**: JSON or JSONP (via `callback` parameter). Results paginated at 25 per page (reduced from 100 in September 2023).

**Web interface**: https://projects.propublica.org/nonprofits/ — full-text search with filters.

**IRS Bulk Data (deprecated as of Dec 31, 2021)**: Historic XML files were available on AWS S3 (`irs-form-990` bucket). The IRS discontinued updates and AWS has removed public access. Alternative bulk sources include Charity Navigator's 990 Toolkit and the Nonprofit Open Data Collective.

## Data Schema

### Organization Profile Fields

| Field | Description |
|-------|-------------|
| `ein` | Employer Identification Number (9-digit integer) |
| `strein` | String-formatted EIN with hyphen (XX-XXXXXXX) |
| `name` | Organization legal name |
| `sub_name` | Subordinate name (if applicable) |
| `address`, `city`, `state`, `zipcode` | Mailing address |
| `subseccd` | IRS subsection code (3 = 501(c)(3) public charity, etc.) |
| `ntee_code` | National Taxonomy of Exempt Entities classification |
| `guidestar_url` | Link to GuideStar profile |
| `nccs_url` | Link to National Center for Charitable Statistics profile |
| `updated` | Last data update timestamp |
| `filings` | Array of filing objects (see below) |

### Filing Object Fields

Each organization returns an array of `filings`, one per year filed. Core fields:

| Field | Description |
|-------|-------------|
| `tax_prd` | Tax period end date (YYYYMM format, e.g., 202312) |
| `tax_prd_yr` | Tax year (YYYY) |
| `formtype` | Form type (990, 990EZ, 990PF, 990N) |
| `pdf_url` | Link to original PDF filing |
| `updated` | Filing record update timestamp |
| `totrevenue` | Total revenue |
| `totfuncexpns` | Total functional expenses |
| `totassetsend` | Total assets (end of year) |
| `totliabend` | Total liabilities (end of year) |
| `totnetassetend` | Net assets (end of year) |
| `pct_compnsatncurrofcr` | Percentage of expenses for current officer compensation |
| `pct_othrsalwages` | Percentage of expenses for other salaries/wages |
| `compnsatncurrofcr` | Current officer compensation (dollars) |
| `othrsalwages` | Other salaries and wages (dollars) |
| `totcntrbgfts` | Total contributions and grants |
| `totprgmrevnue` | Total program service revenue |
| `invstmntinc` | Investment income |
| `grsincmembers` | Gross income from members |
| `grsincother` | Gross income from other sources |

**Additional fields**: Form 990 includes 40-120 additional financial line items (grants paid, lobbying expenses, political expenditures, related organization transactions, schedule of contributors, etc.). Field availability depends on form type and year.

## Coverage

- **Jurisdiction**: United States (all 50 states + DC + territories)
- **Time range**: 2001-present (electronically filed returns); paper-filed pre-2013 not included
- **Update frequency**: Daily (as IRS releases new e-filings)
- **Volume**: 1.8+ million filings; approximately 200,000-300,000 new filings per year
- **Organization count**: Approximately 1.4 million active tax-exempt organizations

**Limitations**:
- Small nonprofits filing Form 990-N (e-Postcard) have no financial data, only confirmation of continued operation
- Churches and religious organizations are not required to file and may be absent
- Pre-2013 filings are incomplete (only orgs that e-filed before the 2013 IRS mandate)

## Cross-Reference Potential

ProPublica 990 data is exceptionally valuable for cross-referencing with campaign finance and contracts:

- **Campaign finance (OCPF, FEC)**: Match nonprofit employees and board members (Schedule J, Schedule O) against campaign contributors. Identify PAC contributions from nonprofit-affiliated individuals.
- **Lobbying disclosures**: Cross-reference Schedule C lobbying expenses with state/federal lobbying registrations to detect undisclosed influence campaigns.
- **Government contracts**: Match Schedule I grant recipients (if government entities) against contract award databases. Identify nonprofits receiving both grants and contracts from the same agency.
- **Corporate registrations**: Resolve related organization transactions (Schedule R) to corporate subsidiaries and affiliates.
- **Foundation grants**: Trace 990-PF (private foundation) grant payments to recipient nonprofits, then link recipients to political actors or contractors.

**Join keys**: EIN (primary), organization name (fuzzy), address, officer/director names (Schedule J, Part VII).

## Data Quality

- **Structured extraction**: ProPublica parses XML filings into normalized JSON. Original PDFs available for verification.
- **Name variations**: Organization names may vary across years (mergers, DBA names). `sub_name` field sometimes captures subordinates inconsistently.
- **Address quality**: Mailing addresses may be accountant/lawyer offices, not operational addresses.
- **Financial inconsistencies**: Amended filings overwrite prior versions. Some orgs file late or skip years.
- **Officer data**: Schedule J (officer compensation) and Part VII (governance) are free-text fields with inconsistent formatting. Name matching requires fuzzy logic.
- **NTEE codes**: Not all organizations have NTEE classifications; some are miscategorized.
- **Date formats**: `tax_prd` uses YYYYMM integer format; `updated` is ISO 8601 timestamp.

## Acquisition Script

See `scripts/fetch_propublica_990.py` for a standalone Python script using only stdlib (urllib.request, json). Supports:
- Organization search by keyword, state, or NTEE code
- Single-org lookup by EIN with full filing history
- JSON output to stdout or file

Run `python scripts/fetch_propublica_990.py --help` for usage.

## Legal & Licensing

IRS Form 990 filings are public records under 26 U.S.C. Section 6104. ProPublica's Nonprofit Explorer is released under the [ProPublica Data Terms of Use](https://www.propublica.org/datastore/terms):
- Free for non-commercial and commercial use
- Attribution required (link back to ProPublica)
- No redistribution of bulk data in competing database products
- No warranties; use at your own risk

Derived analyses and investigations using 990 data are not restricted.

## References

- ProPublica Nonprofit Explorer: https://projects.propublica.org/nonprofits/
- API documentation: https://projects.propublica.org/nonprofits/api
- ProPublica Data Terms of Use: https://www.propublica.org/datastore/terms
- IRS Form 990 overview: https://www.irs.gov/charities-non-profits/form-990-series-which-forms-do-exempt-organizations-file
- Nonprofit Open Data Collective: https://nonprofit-open-data-collective.github.io/overview/
- NTEE classification system: https://nccs.urban.org/project/national-taxonomy-exempt-entities-ntee-codes
- ProPublica API announcement (2013): https://www.propublica.org/nerds/announcing-the-nonprofit-explorer-api

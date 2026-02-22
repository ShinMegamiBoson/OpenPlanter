# SEC EDGAR

## Summary

The Securities and Exchange Commission's Electronic Data Gathering, Analysis, and Retrieval (EDGAR) system is the primary repository for all public company filings in the United States. It contains 10-K/10-Q annual and quarterly reports, 8-K current reports, proxy statements, insider trading disclosures (Forms 3/4/5), beneficial ownership reports (13D/13G), and registration statements dating back to 1994. EDGAR is essential for investigating corporate ownership structures, executive compensation, related-party transactions, and financial relationships between companies and political entities.

## Access Methods

### JSON APIs (Preferred)

The SEC provides free RESTful APIs at `data.sec.gov` that deliver JSON-formatted data with no authentication required.

**Base URL**: `https://data.sec.gov/`

| Endpoint | Description |
|----------|-------------|
| `submissions/CIK##########.json` | Filing history and metadata for a company (CIK must be 10 digits with leading zeros) |
| `api/xbrl/companyfacts/CIK##########.json` | All XBRL financial statement data for a company |
| `api/xbrl/companyconcept/CIK##########/{taxonomy}/{tag}.json` | Single accounting concept across all periods (e.g., us-gaap/AccountsPayableCurrent) |
| `api/xbrl/frames/{taxonomy}/{tag}/CY{year}Q{quarter}.json` | All companies' disclosures of a single concept in a period |

**Company Ticker Lookup**: `https://www.sec.gov/files/company_tickers.json` — maps stock tickers to CIK numbers and company names.

**Rate limit**: 10 requests per second. The SEC monitors by IP address and may temporarily block excessive requests.

**User-Agent requirement**: All requests must include a User-Agent header identifying the requester (format: "CompanyName admin@example.com"). Requests without proper User-Agent headers may be blocked.

### Bulk Data Downloads

**Nightly archives** (most efficient for large-scale analysis):

- `companyfacts.zip` — all XBRL data from the Company Facts API
- `submissions.zip` — complete filing history for all filers from the Submissions API

**Daily filings** (for incremental updates):

- `https://www.sec.gov/Archives/edgar/Feed/` — daily compressed tar.gz archives of all filings (e.g., `20061207.nc.tar.gz`)
- `https://www.sec.gov/Archives/edgar/Oldloads/` — historical concatenated archives with filing headers

### RSS Feeds

**Real-time filings**: `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&CIK=&type=&company=&dateb=&owner=exclude&start=0&count=100&output=atom`

Updated every 10 minutes (Mon-Fri, 6am-10pm ET). Each entry includes company name, CIK, accession number, form type, filing date, and links to HTML and structured data.

### Full-Text Search

**Web interface**: `https://www.sec.gov/edgar/search/` — search filings by keyword, ticker, CIK, or date range. No documented API for full-text search; third-party services (sec-api.io) provide commercial APIs.

## Data Schema

### Submissions API Response

Key fields from `submissions/CIK##########.json`:

| Field | Description |
|-------|-------------|
| `cik` | Central Index Key (unique company identifier) |
| `entityType` | Filer type (operating, investment, etc.) |
| `sic`, `sicDescription` | Standard Industrial Classification code and description |
| `name`, `formerNames` | Current and historical company names |
| `tickers`, `exchanges` | Stock ticker symbols and exchange listings |
| `filings.recent.accessionNumber` | Filing accession numbers (unique ID for each submission) |
| `filings.recent.filingDate` | Date filed with SEC |
| `filings.recent.reportDate` | Reporting period end date |
| `filings.recent.form` | Form type (10-K, 8-K, etc.) |
| `filings.recent.primaryDocument` | Primary document filename |

### XBRL Company Facts API Response

From `api/xbrl/companyfacts/CIK##########.json`:

| Field | Description |
|-------|-------------|
| `entityName` | Company name |
| `cik` | Central Index Key |
| `facts.us-gaap.*` | US GAAP accounting concepts (taxonomy) |
| `facts.dei.*` | Document and Entity Information taxonomy |
| Each concept contains arrays of facts with `end`, `val`, `accn` (accession number), `fy` (fiscal year), `fp` (fiscal period), `form`, `filed` (filing date), and `frame` (reporting period) |

### Form Types

Common filing types relevant to investigations:

- **10-K** — Annual report with audited financials
- **10-Q** — Quarterly report
- **8-K** — Current report (material events: acquisitions, executive changes, bankruptcy)
- **DEF 14A** — Proxy statement (executive compensation, board composition, shareholder proposals)
- **Forms 3/4/5** — Insider trading (initial ownership, transactions, annual summary)
- **13D/13G** — Beneficial ownership (5%+ stake disclosures)
- **S-1** — IPO registration statement
- **SC 13D** — Activist investor disclosure

## Coverage

- **Jurisdiction**: United States (public companies, foreign private issuers with US listings)
- **Time range**: 1994-present (electronic); some filings digitized back to 1993
- **Update frequency**: Real-time (submissions API typically < 1 second delay; XBRL APIs < 1 minute delay)
- **Volume**:
  - 30+ million filings from over 1 million entities
  - ~3,000-5,000 new filings per business day
  - 6,000+ publicly traded companies with active reporting obligations

## Cross-Reference Potential

- **Campaign Finance (OCPF, FEC)**: Match corporate PAC contributions and individual donor employers to parent companies. Link board members and executives to personal political donations.
- **Government Contracts (USAspending, city/state procurement)**: Identify companies winning contracts and cross-reference with ownership structures from 13D/13G filings, related-party transactions in 10-K notes, and board interlocks from proxy statements.
- **State Business Registries (MA SOC)**: Resolve subsidiary relationships and registered agents. EDGAR filings list subsidiaries in Exhibit 21 of 10-K forms.
- **Lobbying Disclosures**: Connect lobbying clients to parent company financials and political contributions from executives.
- **Real Estate Records**: Match property transactions to corporate insiders disclosed in Forms 4/5 or related-party lease agreements in 10-K footnotes.

**Join keys**: CIK (internal), ticker symbol, company name (fuzzy matching required), executive names, addresses (principal executive offices), EIN/tax ID (rarely disclosed).

## Data Quality

- **Structured data**: XBRL financial statements available for 10-K/10-Q/8-K filings since ~2009 (voluntary until 2012, mandatory after). Highly standardized US GAAP taxonomy.
- **Unstructured data**: Pre-XBRL filings and non-financial disclosures (proxy statements, exhibits) require text parsing. Quality varies by filer.
- **Name normalization**: Company names change due to mergers, rebranding, or corporate restructuring. Use `formerNames` array and CIK for disambiguation.
- **Amended filings**: Companies can file amendments (e.g., 10-K/A). The Submissions API includes both original and amended versions; use `accessionNumber` and `filingDate` to identify the latest.
- **Foreign filers**: Use Forms 20-F (annual) and 6-K (current report) instead of 10-K/8-K. May report under IFRS instead of US GAAP.
- **Small filers**: Smaller reporting companies have reduced disclosure requirements (e.g., 2 years of audited financials instead of 3).

## Acquisition Script

See `scripts/fetch_sec_edgar.py` for a Python standard library implementation that queries the company ticker lookup and submissions API.

Example usage:
```bash
# Look up a company by ticker
python scripts/fetch_sec_edgar.py --ticker AAPL

# Get submissions for a specific CIK
python scripts/fetch_sec_edgar.py --cik 0000320193

# Download to a file
python scripts/fetch_sec_edgar.py --ticker MSFT --output msft_submissions.json
```

## Legal & Licensing

All EDGAR filings are **public records** under the Securities Exchange Act of 1934 and the Freedom of Information Act (FOIA). No restrictions on redistribution, derived works, or commercial use. The SEC requests that automated users:

1. Include a descriptive User-Agent header
2. Limit requests to 10 per second to ensure fair access
3. Download bulk archives for large-scale analysis instead of scraping individual pages

**Terms of use**: https://www.sec.gov/about/privacy-information

## References

- Official API documentation: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- Accessing EDGAR data guide: https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data
- Structured data RSS feeds: https://www.sec.gov/structureddata/rss-feeds
- Rate limit announcement: https://www.sec.gov/filergroup/announcements-old/new-rate-control-limits
- EDGAR full-text search: https://www.sec.gov/edgar/search/
- Developer resources: https://www.sec.gov/developer
- CIK lookup tool: https://www.sec.gov/search-filings/cik-lookup
- Daily feed archive: https://www.sec.gov/Archives/edgar/Feed/
- API overview PDF: https://www.sec.gov/files/edgar/filer-information/api-overview.pdf

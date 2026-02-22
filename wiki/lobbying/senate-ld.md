# Senate Lobbying Disclosures (LD-1/LD-2)

## Summary

The U.S. Senate Office of Public Records maintains bulk lobbying disclosure filings under the Lobbying Disclosure Act (LDA) of 1995. Data includes registrations (LD-1), quarterly activity reports (LD-2), and contribution reports (LD-203). Each filing identifies lobbying firms, clients, individual lobbyists, policy issues, government agencies contacted, and income/expenses. This is the authoritative federal source for tracking who is lobbying Congress and executive agencies, making it essential for corruption investigations and influence mapping.

## Access Methods

**Bulk download (legacy)**: Quarterly ZIP archives containing compressed XML files.

```
Base URL: http://soprweb.senate.gov/downloads/
Pattern: {YEAR}_{QUARTER}.zip
Example: http://soprweb.senate.gov/downloads/2024_4.zip
```

Downloads include all documents received during that quarter (Q1-Q4). Files can be opened in Excel 2007+ or parsed with XML libraries.

**REST API (current)**: JSON-based API at `https://lda.senate.gov/api/v1/` provides programmatic access to filings, registrants, clients, lobbyists, and reference data. Requires API registration. Full OpenAPI specification available at `/api/openapi/v1/`.

**Migration notice**: The lda.senate.gov site is transitioning to lda.gov. After June 30, 2026, legacy endpoints may be deprecated. Users should update bookmarks and API integrations to the new domain.

**Web interface**: https://lda.senate.gov/system/public/ — searchable database with filters by registrant, client, lobbyist name, issue code, date range. No bulk export from UI.

## Data Schema

Each quarterly XML download contains three primary document types:

### LD-1 (Registration)

Filed when a lobbying relationship begins. Key fields:

| Field | Description |
|-------|-------------|
| `RegistrantID` | Senate-assigned unique ID for lobbying firm/org |
| `RegistrantName` | Name of registrant (lobbying firm or self-filer) |
| `ClientID` | Senate-assigned unique ID for client |
| `ClientName` | Entity being represented |
| `RegistrationEffectiveDate` | Date lobbying began (added Oct 2014) |
| `GeneralIssueCode` | Policy area (see House/Senate issue codes) |
| `SpecificIssue` | Free-text description of issues |
| `Lobbyist/Name` | Individual lobbyist names (repeating) |
| `Lobbyist/CoveredPosition` | Prior covered official position (if any) |
| `ForeignEntity` | Foreign entity with >20% ownership (if any) |

### LD-2 (Quarterly Activity Report)

Filed quarterly for each active client. Key fields:

| Field | Description |
|-------|-------------|
| `RegistrantID`, `ClientID` | Link to LD-1 registration |
| `ReportYear`, `ReportQuarter` | Q1/Q2/Q3/Q4 reporting period |
| `Income` | Lobbying income (rounded to $10,000 for firms) |
| `Expenses` | Lobbying expenses (rounded to $10,000 for orgs) |
| `GeneralIssueCode` | Policy area (repeating per issue) |
| `SpecificIssue` | Detailed description of lobbying activity |
| `GovernmentEntity` | Agencies/offices contacted (repeating) |
| `Lobbyist/Name` | Active lobbyists that quarter (repeating) |

Income/expenses use $5,000 increments (e.g., "<$5,000", "$10,000", "$20,000"). Reports with no activity in a quarter are marked "No Lobbying Activity".

### LD-203 (Contributions Report)

Semi-annual report (mid-year and year-end) of political contributions by registrants and individual lobbyists. Key fields:

| Field | Description |
|-------|-------------|
| `ReportType` | Mid-Year (July 30) or Year-End (Jan 30) |
| `Contributor` | Registrant or individual lobbyist name |
| `PayeeFirstName`, `PayeeLastName` | Contribution recipient |
| `PayeeOrganization` | PAC or committee name |
| `Amount` | Contribution amount |
| `Date` | Contribution date |
| `Type` | FECA, PAC, presidential library, event |

**General Issue Codes**: Standard list of ~80 policy areas (Agriculture, Defense, Healthcare, Taxes, etc.). Full list at https://lda.senate.gov/system/public/views/lists/general-issue-areas.

## Coverage

- **Jurisdiction**: Federal (U.S. Congress and Executive Branch agencies)
- **Time range**: 1999 Q1 to present (bulk XML); pre-1999 may exist in paper records
- **Update frequency**: Filings due quarterly (LD-1/LD-2: 20 days after quarter-end; LD-203: semi-annually)
- **Volume**: ~12,000 registrants, ~100,000 active quarterly reports per year, ~5,000 LD-203 filings per period

## Cross-Reference Potential

- **Campaign finance (FEC)**: Match lobbyist/registrant contributions to candidate committees using contributor names and amounts. LD-203 directly lists FECA contributions.
- **Federal contracts (USAspending.gov)**: Identify clients that lobby for contracts, then cross-reference with procurement awards. Links lobbying activity to contract outcomes.
- **Congressional voting records (Congress.gov)**: Correlate lobbying issues/bills with roll call votes to measure influence.
- **State campaign finance (e.g., MA OCPF)**: Some federal lobbyists also contribute to state candidates. Match on names and employers.
- **Corporate registrations (SEC)**: Resolve client/registrant names to corporate entities, subsidiaries, and officers.

Join keys: registrant/client names (fuzzy matching required), Senate IDs (RegistrantID, ClientID), individual lobbyist names, issue keywords, dates.

## Data Quality

- **XML structure**: Well-formed but verbose. Each filing is a separate XML document within the ZIP. No CSV export from legacy system.
- **Name inconsistencies**: Registrant/client names may vary across filings (e.g., abbreviations, "Inc." vs "Incorporated"). Senate IDs are the reliable join key.
- **Free-text fields**: `SpecificIssue` and `GovernmentEntity` fields are unstructured. Extracting bill numbers/agencies requires text parsing.
- **Rounding**: Income/expenses rounded to nearest $10,000 or $20,000, reducing precision for trend analysis.
- **Amendments**: Filers can amend prior reports. Amended filings replace originals; no version history in bulk downloads.
- **Late filings**: Some reports filed after deadline. `ReceivedDate` in XML shows actual filing date.

## Acquisition Script

`scripts/fetch_senate_lobbying.py` — Downloads quarterly XML files from soprweb.senate.gov. Specify year and quarter (1-4) as arguments. Uses only Python stdlib (`urllib.request`, `xml.etree`, `argparse`). Run `python scripts/fetch_senate_lobbying.py --help` for usage.

## Legal & Licensing

Public data under the Lobbying Disclosure Act of 1995 (2 U.S.C. §§ 1601-1614) and 1 U.S.C. § 104a. No copyright restrictions. The Senate Office of Public Records is the custodian. No authentication required for bulk downloads. No rate limits documented, but responsible use recommended.

## References

- **LDA.gov API documentation**: https://lda.senate.gov/api/redoc/v1/
- **Downloadable databases (legacy)**: https://www.senate.gov/legislative/Public_Disclosure/database_download.htm
- **Lobbying disclosure home**: https://lda.senate.gov/
- **House Clerk lobbying disclosure**: https://lobbyingdisclosure.house.gov/ (same filings, alternate interface)
- **LDA statute**: 2 U.S.C. §§ 1601-1614
- **Issue code list**: https://lda.senate.gov/system/public/views/lists/general-issue-areas
- **Senate Office of Public Records**: lobby@sec.senate.gov, (202) 224-0758

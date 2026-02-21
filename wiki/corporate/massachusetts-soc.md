# Massachusetts Secretary of Commonwealth — Corporate Registry

## Summary

The Massachusetts Secretary of the Commonwealth maintains the state's official corporate registry. It contains records for all business entities (corporations, LLCs, LLPs, nonprofits) registered in or authorized to do business in Massachusetts, including their officers, registered agents, and filing history. This is essential for resolving corporate entities to the individuals behind them.

## Access Methods

**Online search**: https://corp.sec.state.ma.us/corpweb/CorpSearch/CorpSearch.aspx

Supports search by entity name, ID number, officer/agent name, or registered agent. Returns entity details, officer lists, and filing history. No bulk download or public API.

**FOIA / Public Records Request**: Bulk data extracts may be obtainable via a public records request to the Corporations Division under M.G.L. c. 66, Section 10.

**Scraping**: The search interface uses ASP.NET postbacks (ViewState). Programmatic access requires maintaining session state and parsing HTML responses. Rate-limit considerations apply.

## Data Schema

Per-entity record (as displayed on the web interface):

| Field | Description |
|-------|-------------|
| Entity ID | Unique state-assigned identifier |
| Entity Name | Legal name of the business |
| Entity Type | Corporation, LLC, LLP, Nonprofit, etc. |
| Date of Organization | Formation or registration date |
| State of Organization | Jurisdiction of incorporation |
| Status | Active, Dissolved, Revoked, etc. |
| Resident Agent | Name and address of registered agent in MA |
| Officers | Names, titles, and addresses of directors/officers |
| Filing History | Annual reports, amendments, mergers, dissolutions |

## Coverage

- **Jurisdiction**: Massachusetts (domestic entities + foreign entities authorized in MA)
- **Time range**: Active and historical entities; records go back decades
- **Update frequency**: Real-time (filings processed as received)
- **Volume**: Hundreds of thousands of registered entities

## Cross-Reference Potential

- **OCPF campaign finance**: Match corporate contributor names and officer names to campaign donors.
- **Boston Open Checkbook**: Resolve city contract vendors to their corporate officers and ownership structure.
- **Lobbying disclosures**: Identify corporate entities that employ registered lobbyists.

Join keys: entity names (fuzzy), officer names, registered agent names, addresses.

## Data Quality

- Web-only access; no structured bulk export
- Entity names may include DBA suffixes and legal designators (Inc., LLC, etc.)
- Officer data is self-reported by entities in annual filings and may be outdated
- Historical officer data available through filing history but requires per-entity lookup
- ASP.NET interface can be fragile for automated scraping

## Acquisition Script

No dedicated acquisition script yet. A scraping approach would need to:

1. POST to the search form with ViewState tokens
2. Parse HTML result tables
3. Follow detail links per entity for officer/agent data
4. Respect rate limits and session expiration

## Legal & Licensing

Corporate registry data is public record under Massachusetts law. No explicit license or terms of use on the website. Standard public records law (M.G.L. c. 66, Section 10) applies.

## References

- Corporate search: https://corp.sec.state.ma.us/corpweb/CorpSearch/CorpSearch.aspx
- Secretary of Commonwealth: https://www.sec.state.ma.us/cor/
- Corporations Division: https://www.sec.state.ma.us/cor/coridx.htm

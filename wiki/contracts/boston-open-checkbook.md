# Boston Open Checkbook

## Summary

The City of Boston publishes contract and spending data through its Open Checkbook portal on Analyze Boston (data.boston.gov). This includes city contracts, purchase orders, and expenditure line items across all departments. It is the primary source for identifying vendors receiving city funds and flagging potential pay-to-play patterns.

## Access Methods

**Socrata Open Data API (SODA)**: Analyze Boston datasets are queryable via the SODA API.

```
Checkbook explorer:  https://data.boston.gov/dataset/checkbook-explorer
Contracts dataset:   https://data.boston.gov/dataset/open-checkbook
```

SODA endpoints support JSON/CSV export, filtering (`$where`), pagination (`$limit`, `$offset`), and full-text search.

**Bulk CSV**: Each dataset page offers a direct CSV download link.

**No authentication required** for public datasets. Rate limits apply to unauthenticated SODA requests (~1000 req/hour); register for an app token for higher throughput.

## Data Schema

Key fields vary by dataset. Common fields across checkbook datasets:

| Field | Description |
|-------|-------------|
| `vendor_name` | Payee / contractor name |
| `department_name` | City department |
| `account_description` | Spending category |
| `amount` | Dollar amount |
| `fiscal_year` | Budget year |
| `contract_number` | Contract identifier (where applicable) |
| `check_date` or `invoice_date` | Transaction date |

Exact field names depend on the specific dataset version. Inspect the dataset metadata page for the current schema.

## Coverage

- **Jurisdiction**: City of Boston
- **Time range**: FY2011-present (varies by dataset)
- **Update frequency**: Quarterly or annually depending on the dataset
- **Volume**: Tens of thousands of line items per fiscal year

## Cross-Reference Potential

- **OCPF campaign finance**: Match vendor names against campaign contributor employers and expenditure payees.
- **MA Secretary of Commonwealth**: Resolve vendor entities to corporate officers.
- **Lobbying disclosures**: Identify vendors who also employ registered lobbyists.

Join keys: vendor/entity names (fuzzy), addresses, contract numbers.

## Data Quality

- Clean, machine-readable CSV
- Vendor names may have minor variations across fiscal years (abbreviations, DBA names)
- Some datasets have been restructured between years — check schema version
- Dollar amounts are numeric; no currency symbols in data fields

## Acquisition Script

No dedicated acquisition script yet. Data can be fetched with:

```bash
curl -o checkbook.csv "https://data.boston.gov/api/3/action/datastore_search_sql?sql=SELECT * FROM \"<resource_id>\" LIMIT 50000"
```

Or via the SODA endpoint with appropriate filters.

## Legal & Licensing

Public data published under the City of Boston's open data policy. No restrictions on redistribution. Attribution to the City of Boston / Analyze Boston is encouraged.

## References

- Analyze Boston portal: https://data.boston.gov
- Open Checkbook: https://data.boston.gov/dataset/checkbook-explorer
- SODA API documentation: https://dev.socrata.com/consumers/getting-started.html

# Massachusetts OCPF Campaign Finance

## Summary

The Massachusetts Office of Campaign and Political Finance (OCPF) publishes bulk campaign finance filings for all state and local candidates, PACs, and committees. Data includes itemized contributions, expenditures, in-kind donations, and filer metadata. This is the primary source for Massachusetts campaign finance investigations.

## Access Methods

**Bulk download (preferred)**: ZIP archives on Azure blob storage, updated nightly at 3:30 AM ET.

```
Base URL: https://ocpf2.blob.core.windows.net/downloads/data2/
```

| File | Size | Contents |
|------|------|----------|
| `ocpf-{YEAR}-reports.zip` | 14-22 MB | Annual report metadata + itemized transactions |
| `ocpf-filers.zip` | ~1 MB | All registered filers (candidates, PACs, LPCs) |
| `independent-spending-report-data.zip` | varies | Independent expenditure reports |
| `district_code_list.zip` | small | District code lookup |

Discovery method: URLs reverse-engineered from the OCPF React SPA's JavaScript bundle (`main.*.js`).

**Web interface**: https://www.ocpf.us/Reports — requires JavaScript; no documented API.

**R package**: [maocpf](https://github.com/smach/maocpf) — per-candidate scraping (not bulk).

## Data Schema

Each annual ZIP contains two tab-delimited files:

### reports.txt (~15 MB/year)

| Field | Description |
|-------|-------------|
| `Report_ID` | Unique report identifier |
| `CPF_ID` | Filer committee ID (joins to filers) |
| `Report_Type_ID` | Report type code |
| `Filing_Date` | Date filed |
| `Start_Date`, `End_Date` | Reporting period |
| `Receipts_Total` | Total contributions |
| `Expenditures_Total` | Total expenditures |
| `End_Balance` | Cash on hand |
| `OCPF_Full_Name` | Filer/candidate name |
| `OCPF_Office`, `OCPF_District` | Office sought/held |

### report-items.txt (~88 MB/year)

| Field | Description |
|-------|-------------|
| `Item_ID` | Unique transaction ID |
| `Report_ID` | Joins to reports.txt |
| `Record_Type_ID` | Transaction type (see below) |
| `Date` | Transaction date |
| `Amount` | Dollar amount |
| `Name`, `First_Name` | Contributor/payee |
| `Street_Address`, `City`, `State`, `Zip` | Address |
| `Employer`, `Occupation` | Employment (contributions) |
| `Purpose` | Expenditure purpose |

**Key Record Type IDs**: 201 = Individual Contribution, 202 = Committee Contribution, 211 = Business/Corp Contribution, 301 = Expenditure, 303 = Contribution to Committee, 315 = Independent Expenditure.

### Filer files

- `all_filers.txt` (9,941 records) — all filers
- `candidates.txt` (6,621) — candidate committees
- `pacs.txt` (853) — PACs
- `lpcs.txt` (1,320) — local party committees

## Coverage

- **Jurisdiction**: Massachusetts (state and local)
- **Time range**: 2002-present (bulk); pre-2002 may be incomplete
- **Update frequency**: Nightly (3:30 AM ET)
- **Volume**: ~48,000 reports and ~614,000 itemized transactions per year-set (2019-2026)

## Cross-Reference Potential

- **Boston Open Checkbook**: Match contributor employers and expenditure payees against city contract vendors.
- **MA Secretary of Commonwealth**: Resolve corporate contributors to their officers and registered agents.
- **Lobbying disclosures**: Cross-reference lobbyist employers with campaign donors.

Join keys: entity names (fuzzy), addresses, employer names, CPF IDs (internal).

## Data Quality

- Tab-delimited, quoted strings, UTF-8
- Only latest version of amended reports (superseded reports excluded)
- Multiple date formats (M/D/YYYY most common)
- Free-text name fields with inconsistent formatting
- No geographic index — filtering by city requires joining to candidates table

## Acquisition Script

See `data/ocpf_contributions/` for previously downloaded archives and `data/ocpf_data_sources.md` for the original acquisition notes.

## Legal & Licensing

Public data under the Massachusetts Public Records Law (M.G.L. c. 66, Section 10). No restrictions on redistribution or derived works.

## References

- OCPF website: https://www.ocpf.us
- Bulk downloads: https://www.ocpf.us/Data/Downloads
- Data dictionary: included as `readme.txt` in `ocpf-filers.zip`
- Contact: ocpf@mass.gov, (617) 979-8300

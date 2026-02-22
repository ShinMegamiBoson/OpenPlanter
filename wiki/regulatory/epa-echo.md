# EPA ECHO (Enforcement and Compliance History Online)

## Summary

The EPA Enforcement and Compliance History Online (ECHO) system provides integrated compliance and enforcement information for over 1 million regulated facilities nationwide. Published by the EPA Office of Enforcement and Compliance Assurance, ECHO aggregates inspection, violation, enforcement action, and penalty data across major environmental statutes including the Clean Air Act (CAA), Clean Water Act (CWA), Resource Conservation and Recovery Act (RCRA), and Safe Drinking Water Act (SDWA). The system also includes Toxics Release Inventory (TRI) data. ECHO is essential for investigating corporate environmental compliance patterns, enforcement gaps, and regulatory capture.

## Access Methods

**REST API (preferred)**: JSON/XML/JSONP endpoints via HTTPS, no authentication required.

```
Base URL: https://echodata.epa.gov/echo/
```

| Endpoint | Purpose | Rate Limit |
|----------|---------|------------|
| `echo_rest_services.get_facilities` | Search facilities, validate parameters, obtain Query ID | Not documented |
| `echo_rest_services.get_facility_info` | Self-contained enhanced facility search | Not documented |
| `echo_rest_services.get_qid` | Paginate results using Query ID (valid ~30 min) | Not documented |
| `echo_rest_services.get_download` | Generate CSV/GeoJSON files | Not documented |
| `echo_rest_services.get_map` | Map coordinates and facility clustering | Not documented |

**Recommended workflow**:
1. Call `get_facilities` with search parameters to validate query and obtain a `QueryID`
2. Use `get_qid` with the QueryID to paginate through facility arrays (max 1,000 records/page)
3. Use `get_download` to generate CSV exports for large result sets

**Bulk downloads**: Compressed ZIP files containing comma-delimited text files available at https://echo.epa.gov/tools/data-downloads. Downloads include ICIS-Air, ICIS-NPDES, RCRAInfo, and other program-specific datasets with full historical data. Updated periodically (frequency varies by dataset).

**Web interface**: https://echo.epa.gov/facilities/facility-search — JavaScript-based search tool, no API key required.

**Enforcement case API**: Separate endpoints for civil and criminal case searches via `echo_rest_services.case_rest_services.*`.

## Data Schema

### get_facilities / get_facility_info Response

**Results object** contains:
- `QueryID` — Time-sensitive identifier (valid ~30 minutes) for pagination
- `FacilityInfo` — Array of facility records
- `Summary` — Aggregate statistics across matched facilities
- `ClusterInfo` — Geographic clustering data when results exceed threshold (~2,000 records)

**Facility record fields** (130+ total available):

| Field | Description |
|-------|-------------|
| `RegistryID` | Facility Registry Service (FRS) unique identifier |
| `FacilityName` | Facility name |
| `FacilityStreet`, `FacilityCity`, `FacilityState`, `FacilityZip` | Physical address |
| `FacilityLatitude`, `FacilityLongitude` | Geographic coordinates |
| `AIRIDs`, `NPDESIDs`, `RCRAIDs`, `SDWISIDs` | Program-specific permit/facility IDs |
| `FacMajorFlag` | Major facility designation (Y/N) |
| `CAAComplStatus`, `CWAComplStatus`, `RCRAComplStatus` | Current compliance status by statute |
| `CAA3yrComplQtrsHistory`, `CWA3yrComplQtrsHistory` | 3-year quarterly compliance history (12 quarters) |
| `FormalActionCount`, `InformalActionCount` | Enforcement action counts |
| `Inspections5yr` | Total inspections over 5 years |
| `CurrentSNCStatus`, `CurrentHPVStatus` | Significant Noncompliance (SNC) or High Priority Violator (HPV) status |
| `PenaltiesLast5Years` | Dollar amount of assessed penalties (5-year window) |
| `NAICSCodes` | North American Industry Classification System codes |
| `SICCodes` | Standard Industrial Classification codes |

### Enforcement Case Schema

Civil cases (ICIS) and criminal cases (Summary of Criminal Prosecutions) include:

| Field | Description |
|-------|-------------|
| `CaseNumber` | Unique case identifier |
| `CaseName` | Case name assigned by lead attorney |
| `CaseType` | CI (civil) or CR (criminal) |
| `LeadAgency` | EPA or state agency |
| `FiledDate`, `SettlementDate` | Key case dates |
| `TotalFederalPenalty` | Dollar penalty amount from all settlements |
| `ViolationDescription` | Description of violations |
| `ProgramCodes` | Statutes involved (CAA, CWA, RCRA, etc.) |

## Coverage

- **Jurisdiction**: United States (all 50 states, territories)
- **Time range**: Varies by program; CAA/CWA data generally available from early 2000s; enforcement case data from 1970s for major cases
- **Update frequency**:
  - API: Near real-time (updated as state/federal data syncs to ICIS)
  - Bulk downloads: Quarterly or monthly depending on dataset
- **Volume**:
  - ~1 million regulated facilities
  - ~800,000 facilities in primary search (actively regulated)
  - Tens of thousands of enforcement cases
  - Millions of inspection and violation records

## Cross-Reference Potential

- **Campaign finance data** (OCPF, FEC): Match company names and corporate officers from violating facilities to political contributions. Use `FacilityName`, `NAICSCodes`, and `SICCodes` as join keys alongside fuzzy name matching.
- **Corporate registries** (Secretary of State databases): Resolve facility owners and parent corporations to their officers, registered agents, and subsidiaries.
- **Government contracts** (USASpending, city procurement): Identify contractors with poor environmental compliance records. Join on company name and address fields.
- **Lobbying disclosures**: Cross-reference violators and penalized entities with lobbying expenditures to detect influence campaigns.
- **Toxic Release Inventory (TRI)**: ECHO includes TRI IDs; can cross-reference pollution quantities with enforcement patterns.
- **Superfund sites (SEMS)**: Link facilities to hazardous waste site cleanup responsibilities.

**Primary join keys**: Facility name (fuzzy matching required), address, NAICS/SIC codes, FRS Registry ID (for inter-EPA database joins), latitude/longitude (geocoding).

## Data Quality

- **Inconsistent facility names**: Free-text name fields with variations (e.g., "XYZ Corp", "XYZ Corporation", "XYZ Inc."). Fuzzy matching required.
- **Address standardization**: Some addresses lack ZIP+4, inconsistent street abbreviations.
- **Delayed enforcement data**: State-reported violations may lag by weeks or months before appearing in ECHO.
- **Missing penalty amounts**: Some cases show enforcement actions but no assessed penalty data.
- **Multiple IDs per facility**: Large facilities may have multiple permits (e.g., several NPDES IDs); requires aggregation logic.
- **Compliance status encoding**: Quarterly compliance history uses coded strings (e.g., "VVVNNNCCCNNN" for 12 quarters); requires decoding (V=Violation, N=No Violation, C=Not Applicable).
- **Geocoding accuracy**: Coordinates may reflect facility centroid, mailing address, or permit location; positional accuracy varies.
- **Duplicate records**: Some facilities appear under multiple FRS IDs due to ownership changes or data migration issues.

## Acquisition Script

See `scripts/fetch_epa_echo.py` for a Python script using stdlib to query the ECHO API for facility data. The script supports geographic search, state filtering, compliance status filtering, and CSV export.

```bash
python scripts/fetch_epa_echo.py --state MA --output facilities.csv
```

## Legal & Licensing

ECHO data is public information provided under the Freedom of Information Act (FOIA) and EPA's open data policy. No restrictions on redistribution, analysis, or derived works. Enforcement case data and facility records are considered public records. No terms of service or API key required for access.

**Disclaimer**: EPA notes that compliance data reflects self-reported information from regulated entities and state/federal inspection records. Data quality depends on reporting accuracy and timeliness of state agency submissions.

## References

- ECHO website: https://echo.epa.gov/
- Web Services documentation: https://echo.epa.gov/tools/web-services
- Data downloads: https://echo.epa.gov/tools/data-downloads
- OpenAPI specification: https://api.apis.guru/v2/specs/epa.gov/echo/2019.10.15/swagger.json
- Civil Enforcement Case Report Data Dictionary: https://echo.epa.gov/help/reports/enforcement-case-report-data-dictionary
- ICIS-FE&C Download Summary: https://echo.epa.gov/tools/data-downloads/icis-fec-download-summary
- Envirofacts Data Service API: https://www.epa.gov/enviro/envirofacts-data-service-api
- Contact: echo-support@epa.gov

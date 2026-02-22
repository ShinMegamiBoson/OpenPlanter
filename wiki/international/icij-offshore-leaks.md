# ICIJ Offshore Leaks Database

## Summary

The International Consortium of Investigative Journalists (ICIJ) Offshore Leaks Database is a comprehensive repository of more than 810,000 offshore entities spanning five major leak investigations: Pandora Papers (2021), Paradise Papers (2017), Panama Papers (2016), Bahamas Leaks (2016), and Offshore Leaks (2013). The database contains structured information about offshore companies, trusts, foundations, their beneficial owners, intermediaries who facilitate offshore arrangements, and registered addresses across more than 200 countries and territories. This is the world's largest public repository for offshore financial structure investigations.

## Access Methods

**Bulk download (preferred)**: ZIP archive containing CSV files, updated as new leak investigations are published.

```
Base URL: https://offshoreleaks-data.icij.org/offshoreleaks/csv/
Primary file: full-oldb.LATEST.zip
```

The archive contains several CSV files:
- Node files (one per entity type)
- `all_edges.csv` or `edges_1direction.csv` (relationship data)
- `node_countries.csv` (country associations)
- `countries.csv` (country code lookup)
- `README` documentation explaining field schemas

**Neo4j database dumps**: Available for Neo4j versions 4 and 5 as graph database exports for advanced relationship queries.

**Web interface**: https://offshoreleaks.icij.org — Interactive search and visualization interface with entity search, relationship graph explorer, and country filtering. No documented public API for programmatic access.

**Reconciliation API**: Beta OpenRefine-compatible reconciliation endpoint for entity matching and data enrichment.

## Data Schema

The database uses a graph model with nodes representing entities and edges representing relationships. CSV exports provide flat representations of this structure.

### Node Types

| Type | Description | Approximate Count |
|------|-------------|-------------------|
| **Entity** | Legal structures (companies, trusts, foundations) | 815,000+ |
| **Officer** | Individuals associated with entities (directors, shareholders, beneficiaries) | 2,500,000+ |
| **Intermediary** | Firms or individuals facilitating offshore entity creation (law firms, accountants) | 23,000+ |
| **Address** | Physical locations tied to entities or individuals | 500,000+ |
| **Other** | Additional roles: beneficiaries, trustees, nominees, agents | Varies |

### Common Node Fields

Based on ICIJ schema documentation and CSV exports, nodes typically include:

| Field | Description |
|-------|-------------|
| `node_id` | Unique identifier for the entity or person |
| `name` | Entity name or individual's full name |
| `original_name` | Name as it appears in source documents |
| `sourceID` | Data leak identifier (Panama Papers, Paradise Papers, etc.) |
| `address` | Registered address (may be incomplete) |
| `country_codes` | ISO country codes (semicolon-delimited) |
| `countries` | Country names (semicolon-delimited) |
| `jurisdiction` | Legal jurisdiction of incorporation |
| `jurisdiction_description` | Human-readable jurisdiction name |
| `incorporation_date` | Date of entity formation |
| `inactivation_date` | Date of dissolution or cessation |
| `struck_off_date` | Date removed from registry |
| `closed_date` | Date entity closed |
| `status` | Current status (active, inactive, defaulted) |
| `service_provider` | Offshore services firm managing the entity |
| `valid_until` | Data validity period |
| `node_type` | Entity/Officer/Intermediary/Address/Other |

Entity-specific fields may include company type, registered agent, and corporate structure details. Officer nodes may include role descriptions, nationalities, and passport information.

### Relationship Data

The `all_edges.csv` file connects nodes through typed relationships:

| Relationship Type | Description |
|-------------------|-------------|
| `officer_of` | Individual serves as officer/director |
| `shareholder_of` | Ownership stake in entity |
| `intermediary_of` | Facilitator relationship |
| `registered_address` | Entity-address linkage |
| `same_as` | Duplicate entity resolution |
| `connected_to` | General association |
| `beneficiary_of` | Beneficial ownership |
| `related_entity` | Corporate structure relationship |

Edge records typically include: `START_ID` (source node), `END_ID` (target node), `TYPE` (relationship type), `link` (relationship description), and `sourceID` (leak provenance).

## Coverage

- **Jurisdiction**: Global (200+ countries and territories)
- **Time range**: 1940s–2020 (80+ years); varies by leak
  - Offshore Leaks: 1970s–2010
  - Panama Papers: 1977–2015
  - Bahamas Leaks: 1940s–2016
  - Paradise Papers: 1950s–2016
  - Pandora Papers: 1970s–2020
- **Update frequency**: Irregular; expanded when new leak investigations are published (typically 1-2 year intervals)
- **Volume**:
  - 810,000+ offshore entities
  - 3.9 million+ total nodes (entities, officers, intermediaries, addresses)
  - 29+ million source documents (combined raw file count)
  - 7+ terabytes of source data

## Cross-Reference Potential

High-value joins for investigations:

- **Campaign finance databases**: Match political donors to offshore entity beneficial owners; cross-reference officer names and addresses with contributor records. Join on personal names (fuzzy matching required), addresses, and date ranges.

- **Government contracts**: Identify contract vendors with offshore ownership structures; detect potential corruption or conflicts of interest. Join on company names, registered agents, and business addresses.

- **Corporate registries**: Resolve ultimate beneficial ownership by linking registered agent addresses to known offshore intermediaries; trace shell company networks. Join on entity names, registration dates, and jurisdictions.

- **Sanctions lists**: Screen entities and officers against OFAC, UN, EU sanction lists; identify sanctions evasion networks. Join on personal names, entity names, and countries.

- **Land records & real estate**: Trace property ownership through offshore holding companies; investigate suspicious real estate purchases. Join on entity names and addresses.

- **Lobbying disclosures**: Connect lobbyist employers to offshore ownership structures; expose hidden foreign influence. Join on company names and principal addresses.

**Join key considerations**:
- Names require fuzzy matching (Levenshtein distance, phonetic algorithms) due to spelling variations, alternate romanizations, and data entry inconsistencies
- Addresses are often incomplete or use registered agent locations rather than true business addresses
- Date ranges help disambiguate common names
- `sourceID` indicates data vintage and reliability

## Data Quality

**Strengths**:
- CSV files use UTF-8 encoding with standard delimiters
- Comprehensive provenance tracking via `sourceID` field
- Structured relationship data enables network analysis
- Multiple date fields capture entity lifecycle

**Known issues**:
- **Name inconsistencies**: Same individual may appear with multiple name variants, transliterations, or misspellings across different leaks
- **Incomplete addresses**: Many entries use registered agent addresses (often in tax havens) rather than beneficial owner locations
- **Date format variations**: Dates may appear as YYYY-MM-DD, MM/DD/YYYY, or DD-MMM-YYYY depending on source documents
- **Missing fields**: Not all entities have incorporation dates, officers, or complete ownership chains
- **Duplicate entities**: Same offshore company may appear in multiple leaks with different node IDs; `same_as` relationships partially resolve this
- **Language encoding**: Names from non-Latin alphabets may have inconsistent romanization
- **Sparse officer data**: Many entities list only nominee directors rather than true beneficial owners

**Validation recommendations**:
- Cross-check entity existence in source leak (e.g., Panama Papers) with primary documents where available
- Use multiple name variants when searching for individuals
- Verify matches with additional identifiers (birthdates, nationalities, known associates)
- Check relationship symmetry (A→B implies B→A for bidirectional relationships)

## Acquisition Script

See `scripts/fetch_icij_leaks.py` for a Python script using standard library modules to download and extract the bulk CSV archive.

```bash
python scripts/fetch_icij_leaks.py --output data/icij_leaks/
```

The script downloads `full-oldb.LATEST.zip` and extracts all CSV files to the specified directory. Use `--help` for additional options.

## Legal & Licensing

**License**: Open Database License (ODbL) v1.0 with database contents under Creative Commons Attribution-ShareAlike (CC BY-SA).

**Attribution requirement**: All uses must cite "International Consortium of Investigative Journalists (ICIJ)" as the data source. For academic publications, cite specific leak investigations (e.g., "Panama Papers data via ICIJ Offshore Leaks Database").

**Permitted uses**:
- Journalistic investigations and public interest reporting
- Academic research and statistical analysis
- Anti-corruption and compliance screening
- Derived databases and visualizations (with attribution)

**Restrictions**:
- Share-alike provision applies: Derived databases must use compatible open licenses
- Commercial use permitted but must maintain attribution and share-alike terms
- No warranty; data provided "as-is" without accuracy guarantees

**Data source legality**: Documents in the leaks were obtained through confidential sources. ICIJ does not disclose source identities. The database itself contains factual information extracted from leaked documents, not the underlying documents (which remain confidential).

**Privacy considerations**: Database includes personal information (names, addresses, nationalities) of individuals associated with offshore structures. Not all offshore entities are illegal or used for illicit purposes. Responsible use requires corroboration and context before making allegations.

## References

- ICIJ Offshore Leaks Database home: https://offshoreleaks.icij.org
- Bulk download documentation: https://offshoreleaks.icij.org/pages/database
- Data sources and leak summaries: https://offshoreleaks.icij.org/pages/data
- Schema documentation: https://offshoreleaks.icij.org/schema/oldb/node
- GitHub data tools: https://github.com/ICIJ/offshoreleaks-data-packages
- OpenSanctions structured exports: https://www.opensanctions.org/datasets/icij_offshoreleaks/
- Panama Papers R package (dgrtwo): https://github.com/dgrtwo/rpanama
- Contact: projects@icij.org

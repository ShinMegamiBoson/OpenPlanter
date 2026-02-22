# OFAC SDN List

## Summary

The Office of Foreign Assets Control (OFAC) Specially Designated Nationals (SDN) List is the U.S. Treasury's primary sanctions database, identifying individuals, entities, and vessels designated under national security and economic sanctions programs. The list includes foreign narcotics traffickers, terrorists, proliferators of weapons of mass destruction, and other threat actors. For corruption investigations, the SDN list enables cross-referencing public procurement vendors, campaign donors, and corporate officers against sanctioned entities and their aliases, revealing potential money laundering networks and shell company structures.

## Access Methods

**Bulk download (preferred)**: Legacy flat files updated regularly on Treasury.gov.

```
Base URL: https://www.treasury.gov/ofac/downloads/
```

| File | Contents |
|------|----------|
| `sdn.csv` | Primary SDN records (names, types, programs) |
| `add.csv` | Addresses linked to SDN entries |
| `alt.csv` | Aliases (AKA, FKA, NKA) linked to SDN entries |
| `sdn_comments.csv` | Remarks overflow data (created August 2013) |

**Critical requirement**: All four CSV files must be downloaded and joined in a relational database to obtain complete sanctions list data. Downloading only `sdn.csv` results in missing addresses and aliases.

**Alternative formats**:
- **Fixed-field**: `sdn.ff`, `add.ff`, `alt.ff`, `sdn_comments.ff`
- **XML**: `sdn.xml`, `sdn_advanced.xml` (Advanced Sanctions List Standard format)
- **PDF**: `sdnlist.pdf` (human-readable, not machine-parseable)

**Web interface**: https://sanctionslist.ofac.treas.gov — includes SDN List, Consolidated Non-SDN List, and custom dataset builder.

**Sanctions List Service API**: OFAC's delta file archives track incremental changes between releases.

## Data Schema

The SDN list uses a relational schema with `ent_num` as the primary key joining all files.

**Important**: The legacy CSV files have **no header row**. Field positions are fixed and documented in the data specification. Applications must either add headers programmatically or use positional parsing.

### sdn.csv (Primary records)

| Field | Type | Size | Description |
|-------|------|------|-------------|
| `ent_num` | number | — | Unique record identifier (primary key) |
| `SDN_Name` | text | 350 | Name of SDN (individual, entity, or vessel) |
| `SDN_Type` | text | 12 | Type of SDN (individual, entity, vessel, aircraft) |
| `Program` | text | 200 | Sanctions program name (e.g., SDGT, IRAN, UKRAINE-EO13662) |
| `Title` | text | 200 | Title of an individual (e.g., Minister, General) |
| `Call_Sign` | text | 8 | Vessel call sign |
| `Vess_type` | text | 25 | Vessel type |
| `Tonnage` | text | 14 | Vessel tonnage |
| `GRT` | text | 8 | Gross registered tonnage |
| `Vess_flag` | text | 40 | Vessel flag (country of registry) |
| `Vess_owner` | text | 150 | Vessel owner |
| `Remarks` | text | 1000 | Remarks on SDN (dates of birth, passport numbers, additional identifiers) |

### add.csv (Addresses)

| Field | Type | Size | Description |
|-------|------|------|-------------|
| `Ent_num` | number | — | Foreign key linking to sdn.csv |
| `Add_num` | number | — | Unique address record identifier |
| `Address` | text | 750 | Street address of SDN |
| `City/State/Province/Postal Code` | text | 116 | City, state/province, postal code |
| `Country` | text | 250 | Country of address |
| `Add_remarks` | text | 200 | Remarks on address |

**Cardinality**: One SDN record may have multiple addresses (one-to-many relationship).

### alt.csv (Aliases)

| Field | Type | Size | Description |
|-------|------|------|-------------|
| `ent_num` | number | — | Foreign key linking to sdn.csv |
| `alt_num` | number | — | Unique alias record identifier |
| `alt_type` | text | 8 | Type of alternate identity (aka, fka, nka) |
| `alt_name` | text | 350 | Alternate identity name |
| `alt_remarks` | text | 200 | Remarks on alternate identity |

**Cardinality**: One SDN record may have multiple aliases (one-to-many relationship).

**Alias types**:
- **aka** (also known as): Current alternate names
- **fka** (formerly known as): Previous names
- **nka** (now known as): Current legal name if entity was renamed

### sdn_comments.csv (Remarks overflow)

Contains spillover data for truncated remarks fields. Follows the same data specification as the primary files with unlimited row length. Introduced August 2013 to handle remarks exceeding 1000 characters.

## Coverage

- **Jurisdiction**: Global (all countries subject to U.S. sanctions programs)
- **Time range**: 1995-present (earliest SDN designations); historical designations remain until explicitly removed
- **Update frequency**: Variable — OFAC updates sanctions lists at an "ever increasing pace" with no fixed schedule. Delta files track changes.
- **Volume**: Approximately 12,000+ SDN entries (as of 2026), with 20,000+ aliases and 15,000+ addresses

## Cross-Reference Potential

The SDN list is critical for corruption investigations involving international actors and money flows. Key cross-reference opportunities:

- **Corporate registries** (Secretary of State filings): Match SDN entity names and aliases against corporate officers, registered agents, and beneficial owners. Look for shell companies with SDN-linked principals.
- **Campaign finance data**: Cross-reference donor names, employers, and addresses against SDN records and aliases. Foreign nationals are prohibited from U.S. campaign contributions.
- **Public procurement contracts**: Match vendor names and addresses against SDN list. Government contracts with sanctioned entities violate federal law.
- **Real estate records**: Compare property owners and transaction parties against SDN addresses. Sanctioned individuals often use real estate for money laundering.
- **Business licenses**: Match license holders and corporate affiliations against SDN entities to identify front companies.

**Join keys**: Entity names (fuzzy matching required due to transliteration variations), addresses, dates of birth, passport numbers, vessel IMO numbers.

**Critical note**: OFAC designations often include multiple transliterations of non-Latin names (Arabic, Cyrillic, Chinese). Fuzzy matching algorithms (Levenshtein distance, phonetic matching) are essential.

## Data Quality

- **Format**: CSV with quoted strings, UTF-8 encoding, **no header row**
- **Name variations**: Extensive use of aliases captures transliteration variants, maiden names, and shell company renamings
- **Address granularity**: Ranges from full street addresses to country-only locations
- **Date formats**: Varies in Remarks field (DD MMM YYYY, circa dates, date ranges)
- **Entity disambiguation**: No unique global identifiers (no LEI, DUNS, or EIN fields). Matching requires combining name, DOB, nationality, and address.
- **Amendments**: Updated entries replace previous versions; delta files track changes but historical snapshots are not preserved in the primary download
- **False positives**: Common names (e.g., "Mohamed Ali") require additional identifiers to confirm matches
- **Vessel data**: Comprehensive for maritime sanctions (IMO numbers, tonnage, flags) but aircraft fields are sparse

## Acquisition Script

See `/Users/abrahamparangi/Documents/Experimental/OpenPlanter/scripts/fetch_ofac_sdn.py` for a Python script that downloads all four CSV files and validates their schema.

## Legal & Licensing

**Public domain**: U.S. government works are not subject to copyright (17 U.S.C. § 105). The SDN list may be freely redistributed and used in derived works.

**Legal obligations**: U.S. persons and entities are **legally required** to block transactions with SDN-listed parties (31 C.F.R. Part 501). Use of this data for sanctions compliance carries legal liability; false negatives can result in civil and criminal penalties.

**Export control**: While the data itself is public, sharing it with sanctioned parties or using it to facilitate sanctions evasion is prohibited.

## References

- **OFAC Sanctions List Service**: https://ofac.treasury.gov/sanctions-list-service
- **Legacy flat files tutorial**: https://ofac.treasury.gov/sdn-list-data-formats-data-schemas/tutorial-on-the-use-of-list-related-legacy-flat-files
- **SDN data specification**: https://ofac.treasury.gov/media/29976/download
- **Consolidated list specification**: https://ofac.treasury.gov/media/14056/download
- **FAQ on file formats**: https://ofac.treasury.gov/faqs/topic/1641
- **Advanced Sanctions List Standard (ASLS)**: https://ofac.treasury.gov/sdn-list-data-formats-data-schemas/frequently-asked-questions-on-advanced-sanctions-list-standard
- **Contact**: OFAC Sanctions Compliance & Evaluation Division, ofac_feedback@treasury.gov, 1-800-540-6322

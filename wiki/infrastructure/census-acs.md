# US Census Bureau American Community Survey (ACS)

## Summary

The American Community Survey (ACS) is an ongoing survey conducted by the US Census Bureau that provides detailed demographic, social, economic, and housing statistics for US communities. Published annually in 1-year and 5-year estimates, ACS data includes median income, education levels, employment, housing costs, population by age/race/ethnicity, and hundreds of other variables at multiple geographic levels. This is essential for investigations correlating campaign finance, contract awards, or policy decisions with neighborhood demographics and economic conditions.

## Access Methods

**Census Data API (preferred)**: RESTful JSON API at `api.census.gov/data`.

```
Base URL: https://api.census.gov/data/{year}/acs/{dataset}
Datasets: acs1 (1-year), acs5 (5-year), acs1/profile, acs5/profile, acs5/subject
```

**API Key**: Free registration at https://api.census.gov/data/key_signup.html. Required for >500 queries/day per IP address. No-key mode available for light usage.

**Rate limits**: 500 queries/day without key; higher limits with key (not publicly documented, but effectively unlimited for reasonable use).

**Example queries**:
```
# Median household income (B19013_001E) for all states, 2023 5-year
https://api.census.gov/data/2023/acs/acs5?get=NAME,B19013_001E&for=state:*

# Total population by sex/age (table B01001) for Suffolk County, MA tracts
https://api.census.gov/data/2023/acs/acs5?get=NAME,group(B01001)&for=tract:*&in=state:25+county:025

# Poverty rate for Boston (place FIPS 07000) in Massachusetts (state FIPS 25)
https://api.census.gov/data/2023/acs/acs5?get=NAME,B17001_002E,B17001_001E&for=place:07000&in=state:25
```

**Data discovery tools**:
- Interactive API query builder: https://api.census.gov/data.html
- Variable search: https://api.census.gov/data/2023/acs/acs5/variables.html

**Bulk download**: FTP site at https://www2.census.gov/programs-surveys/acs/summary_file/ (large, complex table structures; API preferred).

## Data Schema

ACS organizes data into tables, each identified by a code (e.g., B01001, B19013). Each table contains multiple variables.

### Variable Naming Convention

Variables follow the pattern `[TABLE]_[SEQUENCE][SUFFIX]`:
- `B19013_001E` = Median household income estimate
- `B19013_001M` = Median household income margin of error
- Suffix `E` = Estimate (point value)
- Suffix `M` = Margin of error (90% confidence)

### Key Tables for Investigations

| Table Code | Description |
|------------|-------------|
| B01001 | Sex by age (population breakdown) |
| B01003 | Total population |
| B02001 | Race |
| B03002 | Hispanic or Latino origin by race |
| B19013 | Median household income |
| B19301 | Per capita income |
| B17001 | Poverty status in the past 12 months |
| B23025 | Employment status |
| B25077 | Median home value |
| B25064 | Median gross rent |
| B15003 | Educational attainment |
| B08301 | Means of transportation to work |
| B11001 | Household type |

### Data Products

- **Detailed Tables**: 20,000+ variables; available to block group level
- **Subject Tables**: Thematic summaries (S-prefix); tract level
- **Data Profiles**: Key indicators (DP-prefix); tract level
- **Comparison Profiles**: Year-over-year changes (CP-prefix); tract level

### Geography Response Fields

| Field | Description |
|-------|-------------|
| `NAME` | Human-readable geographic name |
| `state` | State FIPS code (2-digit) |
| `county` | County FIPS code (3-digit, within state) |
| `tract` | Census tract code (6-digit, within county) |
| `block group` | Block group code (1-digit, within tract) |
| `place` | Place/city FIPS code (5-digit, within state) |
| `congressional district` | Congressional district code |
| `metropolitan statistical area/micropolitan statistical area` | Metro area code |
| `zip code tabulation area` | ZCTA (5-digit) |

## Coverage

- **Jurisdiction**: United States, Puerto Rico, District of Columbia; all states, counties, places, metro areas, congressional districts, census tracts, block groups, and ZCTAs
- **Time range**:
  - 1-year estimates: 2005-2024 (population 65,000+)
  - 5-year estimates: 2009-2024 (all geographies, including small areas)
- **Update frequency**: Annual releases in September (1-year) and December (5-year)
- **Volume**:
  - 5-year (2019-2023): ~35,000 variables × 220,000 census tracts
  - Most recent data: 2024 1-year (released Sept 2025), 2020-2024 5-year (Dec 2025)

## Cross-Reference Potential

ACS data is ideal for demographic overlays on other investigation datasets:

- **Campaign finance**: Correlate contribution patterns with donor neighborhood income, education, race/ethnicity. Match candidate district boundaries to demographic profiles.
- **Contracts**: Analyze whether city contracts flow to high/low-income areas; cross-reference vendor addresses with neighborhood wealth indicators.
- **Lobbying/PAC records**: Identify lobbyist home addresses and compare to neighborhood median income and political demographics.
- **Police data / crime records**: Normalize incident rates by population; overlay with poverty, employment, housing cost data.
- **Environmental / infrastructure**: Map pollution permits or development projects against neighborhood demographics for equity analysis.

**Join keys**: Geographic FIPS codes (state, county, tract, block group, place), addresses (geocoded to census geography), ZIP codes (via ZCTA).

**Geographic crosswalks**: Census provides relationship files to map ZCTAs to tracts, places to counties, etc. at https://www.census.gov/geographies/reference-files/time-series/geo/relationship-files.html.

## Data Quality

- **Sampling**: ACS is survey-based, not a full enumeration. All values are estimates with margins of error. Smaller geographies have wider error margins. Always use margin of error (M variables) for statistical tests.
- **Suppression**: Data suppressed if sample too small or violates disclosure rules. Suppressed values appear as `-666666666` or null.
- **Multi-year spans**: 5-year estimates aggregate 60 months of responses; use for stability, not to detect single-year trends.
- **Date alignment**: 5-year data labeled by end year (e.g., "2019-2023" released Dec 2024). Compare only non-overlapping 5-year periods.
- **Geography changes**: Tract/block group boundaries redrawn every 10 years (2010, 2020). Use crosswalk files for longitudinal analysis.
- **Consistency**: API returns JSON arrays; first row is column headers.

## Acquisition Script

`scripts/fetch_census_acs.py` — Python stdlib script to query ACS API for specified variables and geographies. Supports CSV output.

Usage:
```bash
# Get median income for all Massachusetts counties, 2023 5-year
python scripts/fetch_census_acs.py \
  --year 2023 \
  --dataset acs5 \
  --variables B19013_001E,B19013_001M \
  --geography county:* \
  --state 25 \
  --output ma_county_income.csv

# Get poverty data for all tracts in Suffolk County (Boston), no API key
python scripts/fetch_census_acs.py \
  --year 2023 \
  --dataset acs5 \
  --variables B17001_002E,B17001_001E \
  --geography tract:* \
  --state 25 \
  --county 025 \
  --output boston_poverty.csv
```

## Legal & Licensing

All US Census Bureau data is **public domain** under Title 13, United States Code. No copyright restrictions. Freely redistributable for any purpose, commercial or non-commercial. Attribution appreciated but not required.

Citation format:
```
U.S. Census Bureau, 2019-2023 American Community Survey 5-Year Estimates,
Table B19013, accessed via Census API on [date].
```

## References

- **ACS API home**: https://www.census.gov/programs-surveys/acs/data/data-via-api.html
- **Developer portal**: https://www.census.gov/data/developers.html
- **ACS 5-year datasets**: https://www.census.gov/data/developers/data-sets/acs-5year.html
- **ACS 1-year datasets**: https://www.census.gov/data/developers/data-sets/acs-1year.html
- **API user guide (PDF)**: https://www.census.gov/content/dam/Census/data/developers/api-user-guide/api-user-guide.pdf
- **Example queries**: https://www.census.gov/data/developers/guidance/api-user-guide.Example_API_Queries.html
- **Variable search**: https://data.census.gov/
- **Geographic relationship files**: https://www.census.gov/geographies/reference-files/time-series/geo/relationship-files.html
- **ACS handbook**: https://www.census.gov/content/dam/Census/library/publications/2020/acs/acs_api_handbook_2020.pdf
- **Support**: https://www.census.gov/data/developers/guidance/api-user-guide/help.html

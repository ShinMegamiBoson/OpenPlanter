# Public Records API Reference

Quick reference for US government APIs used by `scrape_records.py` and `dataset_fetcher.py`. All endpoints are accessed via `urllib.request` (stdlib only).

## SEC EDGAR

**Entity submissions** (filing history, metadata):
```
GET https://data.sec.gov/submissions/CIK{cik_padded_10}.json
Header: User-Agent: OpenPlanter/1.0 openplanter@investigation.local
```
- **Auth**: User-Agent with name + email (mandatory, no API key)
- **Rate**: ~10 requests/sec
- **Linking keys**: `cik` (Central Index Key), `tickers`, `exchanges`
- **CIK lookup**: `https://www.sec.gov/files/company_tickers.json` (JSON map of all tickers → CIK)

**Full-text search** (EDGAR EFTS):
```
GET https://efts.sec.gov/LATEST/search-index?q={query}&dateRange=custom&startdt=2020-01-01&forms=10-K,10-Q,8-K,DEF+14A&hits.hits.total=true
```

## FEC (Federal Election Commission)

**Committee name search**:
```
GET https://api.open.fec.gov/v1/names/committees/?q={name}&api_key={key}
```
- **Auth**: Free API key at [api.open.fec.gov](https://api.open.fec.gov/developers/). `DEMO_KEY` available (1000 req/hr)
- **Rate**: 1000 requests/hr per key
- **Linking keys**: `committee_id`, `committee_name`, `treasurer_name`

**Individual contributions (Schedule A)**:
```
GET https://api.open.fec.gov/v1/schedules/schedule_a/?contributor_name={name}&api_key={key}&per_page=100
```

**Bulk downloads** (used by `dataset_fetcher.py`):
```
https://www.fec.gov/files/bulk-downloads/2024/committee_master_2024.csv
```

## Senate LDA (Lobbying Disclosure Act)

**Registrant search**:
```
GET https://lda.senate.gov/api/v1/registrants/?name={name}&format=json&page_size=25
```
- **Auth**: None
- **Rate**: ~1 request/sec (polite)
- **Linking keys**: `id`, `name`, `house_registrant_id`
- **Pagination**: `{next, previous, count, results}` — follow `next` URL

**Filing search**:
```
GET https://lda.senate.gov/api/v1/filings/?filing_type=1&registrant_name={name}&format=json&page_size=25
```

## OFAC SDN (Treasury Sanctions)

**Bulk download** (used by `dataset_fetcher.py`):
```
https://www.treasury.gov/ofac/downloads/sdn.csv
```
- **Auth**: None
- **Format**: Pipe-delimited CSV
- **Linking keys**: `uid`, `name`, `sdnType`, `programs`

## OpenSanctions

**Bulk download** (used by `dataset_fetcher.py`):
```
https://data.opensanctions.org/datasets/latest/sanctions/targets.simple.csv
```
- **Auth**: None (non-commercial use)
- **Linking keys**: `id`, `name`, `countries`, `identifiers`

## USAspending.gov

**Award search** (POST JSON):
```
POST https://api.usaspending.gov/api/v2/search/spending_by_award/
Content-Type: application/json

{
  "filters": {
    "keyword": "entity name",
    "time_period": [{"start_date": "2020-01-01", "end_date": "2026-12-31"}]
  },
  "fields": ["Award ID", "Recipient Name", "Award Amount", "Awarding Agency"],
  "page": 1,
  "limit": 25,
  "sort": "Award Amount",
  "order": "desc"
}
```
- **Auth**: None
- **Rate**: Liberal (no published limit)
- **Linking keys**: `recipient_name`, `award_id`, `awarding_agency`

## US Census Bureau (ACS)

**American Community Survey 5-Year Estimates**:
```
GET https://api.census.gov/data/{year}/acs/acs5?get={variables}&for={geography}&key={key}
```
- **Auth**: Optional `CENSUS_API_KEY` (free at [api.census.gov](https://api.census.gov/data/key_signup.html)). Works without key at lower rate.
- **Rate**: ~500 req/day without key, higher with key
- **Linking keys**: `state`, `county`, `zip code tabulation area`
- **Script**: `fetch_census.py`
- **Key variables**: B01003_001E (population), B19013_001E (median income), B15003_022E (bachelor's degree)

**Geography codes**:
```
for=state:*                        # All states
for=county:*&in=state:36           # All counties in NY (FIPS 36)
for=zip+code+tabulation+area:12508 # Single ZIP
```

## EPA ECHO (Enforcement & Compliance History)

**Facility search**:
```
GET https://echodata.epa.gov/echo/echo_rest_services.get_facilities?output=JSON&p_fn={name}&p_st={state}
```
- **Auth**: None (free public API)
- **Rate**: ~2 req/sec recommended
- **Linking keys**: `RegistryId` (FRS ID), `FacilityName`, `SICCodes`, `NAICSCodes`, `Lat`, `Lon`
- **Script**: `fetch_epa.py`
- **Response format**: `{"Results": {"Facilities": [...]}}`

**Program flags**: `AirFlag` (CAA), `CWAFlag` (CWA), `RCRAFlag` (RCRA), `TRIFlag` (TRI)

## ICIJ Offshore Leaks Database

**Entity search**:
```
GET https://offshoreleaks.icij.org/api/v1/search?q={query}&type={entity|officer|intermediary|address}&limit=100
```
- **Auth**: None (free public database)
- **Rate**: ~1 req/sec recommended (429 on burst)
- **Linking keys**: `id` (ICIJ node ID), `name`, `jurisdiction`, `country_codes`, `sourceID`
- **Script**: `fetch_icij.py`
- **Datasets**: Panama Papers (2016), Paradise Papers (2017), Pandora Papers (2021), Offshore Leaks (2013), Bahamas Leaks (2016)

## OSHA Inspection Data (DOL Enforcement)

**Inspection search**:
```
GET https://enforcedata.dol.gov/api/enforcement?dataset=inspection&$filter={filter}&$top=25&$orderby=open_date desc
```
- **Auth**: None (free public API)
- **Rate**: ~2 req/sec recommended
- **Linking keys**: `activity_nr`, `estab_name`, `sic_code`, `naics_code`, `site_state`
- **Script**: `fetch_osha.py`
- **Filter syntax**: `estab_name eq 'Name' and site_state eq 'TX' and sic_code eq '2911'`

## ProPublica Nonprofit Explorer (IRS 990)

**Organization search**:
```
GET https://projects.propublica.org/nonprofits/api/v2/search.json?q={name}&state[id]={state}&ntee[id]={code}
```
- **Auth**: None (free public API)
- **Rate**: ~1 req/sec recommended
- **Linking keys**: `ein`, `name`, `ntee_code`, `state`
- **Script**: `fetch_propublica990.py`

**Direct EIN lookup** (includes filing data + officer compensation):
```
GET https://projects.propublica.org/nonprofits/api/v2/organizations/{ein}.json
```

## SAM.gov Entity Registration

**Entity search**:
```
GET https://api.sam.gov/entity-information/v3/entities?api_key={key}&legalBusinessName={name}&registrationStatus=A
```
- **Auth**: `SAM_GOV_API_KEY` required (free at [api.data.gov](https://api.data.gov/signup/))
- **Rate**: 1000 req/day
- **Linking keys**: `ueiSAM` (Unique Entity ID), `cageCode`, `legalBusinessName`, `naicsCode`
- **Script**: `fetch_sam.py`
- **Sections**: `includeSections=entityRegistration,coreData`

## Cross-Dataset Linking Strategy

No universal corporate ID exists in US public records. Standard approach:

1. **Normalize entity names** (strip legal suffixes, case fold, Unicode NFKD)
2. **Fuzzy match** across datasets (`difflib.SequenceMatcher`, threshold ≥ 0.85)
3. **Filter by jurisdiction** (state, address)
4. **Anchor on hard IDs** when available: CIK (SEC), committee_id (FEC), EIN (IRS/ProPublica), UEI (SAM.gov), FRS ID (EPA), CAGE code (DoD)
5. **Score confidence** using Admiralty tiers
6. **Cross-link via NAICS/SIC** when name matching is ambiguous

## Environment Variables

| Variable | Used By | Required |
|----------|---------|----------|
| `FEC_API_KEY` | `scrape_records.py` | No (`DEMO_KEY` fallback) |
| `EXA_API_KEY` | `web_enrich.py` | Yes (for Exa search) |
| `CENSUS_API_KEY` | `fetch_census.py` | No (works without, lower rate) |
| `SAM_GOV_API_KEY` | `fetch_sam.py` | Yes (free at api.data.gov) |
| `ANTHROPIC_API_KEY` | `delegate_to_rlm.py` | If using Anthropic models |
| `OPENAI_API_KEY` | `delegate_to_rlm.py` | If using OpenAI models |
| `OPENROUTER_API_KEY` | `delegate_to_rlm.py` | If using OpenRouter models |
| `CEREBRAS_API_KEY` | `delegate_to_rlm.py` | If using Cerebras models |
| `OPENPLANTER_REPO` | `delegate_to_rlm.py` | No (auto-discovers local clone) |

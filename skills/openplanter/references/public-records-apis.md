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

## Cross-Dataset Linking Strategy

No universal corporate ID exists in US public records. Standard approach:

1. **Normalize entity names** (strip legal suffixes, case fold, Unicode NFKD)
2. **Fuzzy match** across datasets (`difflib.SequenceMatcher`, threshold ≥ 0.85)
3. **Filter by jurisdiction** (state, address)
4. **Anchor on hard IDs** when available: CIK (SEC), committee_id (FEC), EIN (IRS)
5. **Score confidence** using Admiralty tiers

## Environment Variables

| Variable | Used By | Required |
|----------|---------|----------|
| `FEC_API_KEY` | `scrape_records.py` | No (`DEMO_KEY` fallback) |
| `EXA_API_KEY` | `web_enrich.py` | Yes (for Exa search) |
| `ANTHROPIC_API_KEY` | `delegate_to_rlm.py` | If using Anthropic models |
| `OPENAI_API_KEY` | `delegate_to_rlm.py` | If using OpenAI models |
| `OPENROUTER_API_KEY` | `delegate_to_rlm.py` | If using OpenRouter models |
| `CEREBRAS_API_KEY` | `delegate_to_rlm.py` | If using Cerebras models |

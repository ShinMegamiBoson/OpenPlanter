# Booz Allen Hamilton (NYSE: BAH) — Federal contracting, political contributions, SEC items (preliminary)

Generated: 2026-02-23

## Summary (what we found in this workspace)

### 1) Largest recent federal contracts (FY2024 window)
Using USAspending.gov API `spending_by_award` results for FY2024 (2023-10-01 to 2024-09-30) filtered to contract award type codes (A–D), Booz Allen Hamilton Inc appears as recipient on multiple awards above $1B.

Examples (award-level totals as returned by the endpoint; see `results.json` for full extracted fields and citations):
- **47QFCA21F0018** — **$1379603153.12** — Awarding agency: **General Services Administration**; Funding agency: **Department of Defense** (source: `data/raw/usaspending/spending_by_award_BAH_FY2024_top100.json`, result_index 0).
- **36C10B21N10070021** — **$1336349299.17** — Awarding/Funding agency: **Department of Veterans Affairs** (source: same file, result_index 1).
- **36C10B21N10150056** — **$1139008033.13** — Awarding/Funding agency: **Department of Veterans Affairs** (source: same file, result_index 2).
- **47QFCA20F0014** — **$1070585831.99** — Awarding agency: **General Services Administration**; Funding agency: **Department of Defense** (source: same file, result_index 3).
- **47QFCA22F0047** — **$1000052170.69** — Awarding agency: **General Services Administration**; Funding agency: **Department of Defense** (source: same file, result_index 4).

Agency concentration (USAspending `spending_by_category/awarding_agency` in the same FY2024 window):
- **General Services Administration**: **$2903055466.76**
- **Department of Defense**: **$2675967636.44**
- **Department of Veterans Affairs**: **$1392741371.82**
- **Department of Health and Human Services**: **$472685532.31**
- **Department of the Treasury**: **$189040047.43**
(see `data/raw/usaspending/spending_by_category_awarding_agency_BAH_FY2024.json` and `results.json`.)

### 2) Political contributions (PAC + executives/individuals)

#### Booz Allen Hamilton Inc. PAC
Booz Allen Hamilton Inc. PAC is identified in FEC data as committee_id **C00709816** (see `data/raw/fec/committee_C00709816.json`). Its Schedule B disbursements in the cached extract (`data/raw/fec/schedule_b_C00709816_2024_top100.json`) are all categorized as **CONTRIBUTIONS**.

Examples (from that extract):
- **$5000.0** to **SCHMITT FOR SENATE** (candidate: ERIC SCHMITT) (FEC sub_id **4081320242011922649**).
- **$5000.0** to **JONI FOR IOWA** (candidate: JONI ERNST) (FEC sub_id **4080320231762806112**).
- **$4000.0** to **WICKER FOR SENATE** (candidate: ROGER WICKER) (FEC sub_id **4080320231762806076**).
- **$3000.0** to **CONNOLLY FOR CONGRESS** (candidate: GERRY CONNOLLY) (FEC sub_id **4120520241074892759**).
- **$3000.0** to **COMER FOR CONGRESS** (candidate: JAMES COMER) (FEC sub_id **4082120242014613985**).

#### Individual contributions (employer filter)
Using OpenFEC Schedule A receipts filtered by **contributor_employer = "BOOZ ALLEN HAMILTON"**, 2024 two-year transaction period, large-dollar itemized receipts include contributions from individuals reporting senior roles.

Examples (from `data/raw/fec/schedule_a_employer_BOOZ_ALLEN_HAMILTON_2024_top100.json`):
- **$15000.0** — contributor **ROZANSKI, HORATIO** (occupation **CEO**, employer **BOOZ ALLEN HAMILTON**) (FEC sub_id **4121620241076631165**).
- **$15000.0** — contributor **ROZANSKI, HORACIO** (occupation **CEO**) (FEC sub_id **4010720251127187577**).
- **$15000.0** — contributor **ROZANSKI, HORACIO D.** (occupation **CEO**) (FEC sub_id **4010620251126694046**).

## 3) SEC / EDGAR items (filings + enforcement scan)

### EDGAR filings index
Booz Allen Hamilton Holding Corporation CIK resolved from SEC tickers JSON as **0001443646** (cached `data/raw/sec/company_tickers.json`), with submissions JSON cached at `data/raw/sec/submissions_CIK0001443646.json`. `results.json` includes direct URLs for recent 10-K/10-Q/8-K/DEF 14A primary documents.

### Enforcement actions
Within this session we did **not** identify a specific SEC litigation release / administrative proceeding charging Booz Allen Hamilton. We performed a keyword scan on a cached 10-Q HTML (see `data/raw/sec/bah-20251231_10q.html`) and did not find “Wells notice” or the phrase “SEC investigation”; occurrences of “investigation” appear in general risk factor language about government audits/investigations.

## Cross-referencing: political giving ↔ contract-awarding agencies (contextual)

Because campaign contributions do not directly name executive-branch agencies, links in `results.json` are labeled **possible** and based on documented committee oversight/jurisdiction relevance:
- PAC giving to **SCHMITT FOR SENATE** ↔ **DoD** context (Sen. Eric Schmitt listed with **Senate Armed Services Committee**) (committee evidence in `politician_committee_relevance.json`).
- PAC giving to **WICKER FOR SENATE** ↔ **DoD** context (Sen. Roger Wicker: **Senate Armed Services Committee**).
- PAC giving to **THOM TILLIS COMMITTEE** ↔ **VA** context (Sen. Thom Tillis: **Senate Committee on Veterans’ Affairs**).
- PAC giving to **CONNOLLY FOR CONGRESS** and **COMER FOR CONGRESS** ↔ **GSA** context (House oversight committee relevance to federal procurement/operations).

These cross-links are not evidence of influence, only a way to connect political recipients to agencies that are major sources of BAH contract dollars.

## Methodology / provenance
- USAspending.gov API results were cached as JSON under `data/raw/usaspending/`.
- OpenFEC API results were cached as JSON under `data/raw/fec/`.
- SEC EDGAR JSON cached under `data/raw/sec/`; a single 10-Q HTML was cached and keyword-scanned.
- Politician committee assignments were compiled with cited sources in `politician_committee_relevance.json`.

## Limitations
- USAspending award amounts in `spending_by_award` are award totals as returned by the API and may not equal obligations within FY2024.
- FEC individual contribution extraction uses an exact employer string filter and will omit employer variants.
- Cross-links are contextual and should not be interpreted causally.

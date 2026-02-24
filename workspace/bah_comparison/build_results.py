import json, datetime
from pathlib import Path


def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def normalize(s):
    return (s or "").upper()


def main():
    # Cached inputs
    us_aw_path = "data/raw/usaspending/spending_by_award_BAH_FY2024_top100.json"
    us_ag_awarding_path = "data/raw/usaspending/spending_by_category_awarding_agency_BAH_FY2024.json"
    fec_b_path = "data/raw/fec/schedule_b_C00709816_2024_top100.json"
    fec_a_path = "data/raw/fec/schedule_a_employer_BOOZ_ALLEN_HAMILTON_2024_top100.json"
    fec_committee_path = "data/raw/fec/committee_C00709816.json"
    sec_sub_path = "data/raw/sec/submissions_CIK0001443646.json"
    sec_10q_html_path = "data/raw/sec/bah-20251231_10q.html"
    pol_committees_path = "politician_committee_relevance.json"
    sec_pay_pdf_path = "data/raw/web/sec_contract_payment_justifications_202507.pdf"
    sec_pay_derived_path = "data/derived/sec_contract_payment_justifications_202507_booz_allen.json"

    us_aw = load_json(us_aw_path)
    us_ag_awarding = load_json(us_ag_awarding_path)
    fec_b = load_json(fec_b_path)
    fec_a = load_json(fec_a_path)
    fec_committee = load_json(fec_committee_path)
    sec_sub = load_json(sec_sub_path)
    pol = load_json(pol_committees_path)

    # SEC filings: last 15 for key forms
    recent = sec_sub.get("filings", {}).get("recent", {})
    filings = []
    for form, date, acc, doc in zip(
        recent.get("form", []),
        recent.get("filingDate", []),
        recent.get("accessionNumber", []),
        recent.get("primaryDocument", []),
    ):
        if form in ("10-K", "10-Q", "8-K", "DEF 14A"):
            url = "https://www.sec.gov/Archives/edgar/data/1443646/{}/{}".format(acc.replace("-", ""), doc)
            filings.append(
                {
                    "type": "edgar_filing",
                    "form": form,
                    "filing_date": date,
                    "accession_number": acc,
                    "primary_document": doc,
                    "url": url,
                    "source": {"dataset": "sec_submissions_json", "path": sec_sub_path},
                }
            )

    # Top contracts (by award amount, from spending_by_award)
    top_contracts = []
    for idx, r in enumerate(us_aw.get("results", [])[:15]):
        top_contracts.append(
            {
                "rank": idx + 1,
                "award_id": r.get("Award ID"),
                "award_amount": r.get("Award Amount"),
                "recipient_name": r.get("Recipient Name"),
                "recipient_uei": r.get("Recipient UEI"),
                "start_date": r.get("Start Date"),
                "end_date": r.get("End Date"),
                "awarding_agency": r.get("Awarding Agency"),
                "funding_agency": r.get("Funding Agency"),
                "description": r.get("Description"),
                "source": {
                    "dataset": "usaspending_api_spending_by_award",
                    "path": us_aw_path,
                    "result_index": idx,
                },
            }
        )

    # Awarding agency totals
    contract_agency_totals = []
    for idx, r in enumerate(us_ag_awarding.get("results", [])):
        contract_agency_totals.append(
            {
                "rank": idx + 1,
                "agency_name": r.get("name"),
                "amount": r.get("amount"),
                "source": {
                    "dataset": "usaspending_api_spending_by_category_awarding_agency",
                    "path": us_ag_awarding_path,
                    "result_index": idx,
                },
            }
        )

    # PAC disbursements (all are category CONTRIBUTIONS in this extract)
    pac_contrib = []
    pac_rows = sorted(fec_b.get("results", []), key=lambda r: float(r.get("disbursement_amount") or 0.0), reverse=True)
    for r in pac_rows[:40]:
        pac_contrib.append(
            {
                "type": "PAC_disbursement_contribution",
                "committee_id": r.get("committee_id"),
                "committee_name": r.get("committee"),
                "disbursement_date": r.get("disbursement_date"),
                "amount": r.get("disbursement_amount"),
                "recipient_name": r.get("recipient_name"),
                "recipient_committee_id": r.get("recipient_committee_id"),
                "candidate_name": r.get("candidate_name"),
                "candidate_id": r.get("candidate_id"),
                "sub_id": r.get("sub_id"),
                "pdf_url": r.get("pdf_url"),
                "source": {"dataset": "fec_schedule_b", "path": fec_b_path},
            }
        )

    # Individual contributions filtered by exact employer string
    indiv = []
    indiv_rows = sorted(
        fec_a.get("results", []), key=lambda r: float(r.get("contribution_receipt_amount") or 0.0), reverse=True
    )
    for r in indiv_rows[:40]:
        indiv.append(
            {
                "type": "individual_contribution_employer_match",
                "contribution_receipt_date": r.get("contribution_receipt_date"),
                "amount": r.get("contribution_receipt_amount"),
                "contributor_name": r.get("contributor_name"),
                "contributor_occupation": r.get("contributor_occupation"),
                "contributor_employer": r.get("contributor_employer"),
                "recipient_name": r.get("recipient_name"),
                "committee_id": r.get("committee_id"),
                "candidate_id": r.get("candidate_id"),
                "sub_id": r.get("sub_id"),
                "pdf_url": r.get("pdf_url"),
                "source": {"dataset": "fec_schedule_a", "path": fec_a_path},
            }
        )

    # SEC keyword scan note (using previously computed observation; store as narrative)
    sec_items = filings[:15]
    sec_items.append(
        {
            "type": "keyword_scan_10q_html",
            "file": sec_10q_html_path,
            "notes": "Keyword scan on cached 10-Q HTML did not find 'wells notice' or the phrase 'sec investigation'; occurrences of 'investigation' appear in general risk-factor context about government audits/investigations.",
            "source": {"path": sec_10q_html_path},
        }
    )

    # SEC contract payments PDF presence of Booz Allen lines is additional evidence of SEC as a customer.
    if Path(sec_pay_derived_path).exists():
        sec_pay = load_json(sec_pay_derived_path)
        sec_items.append(
            {
                "type": "sec_contract_payment_justifications_excerpt",
                "pdf_url": "https://www.sec.gov/files/07012025-07312025-contract-payment-justifications.pdf",
                "pdf_cached_path": sec_pay_pdf_path,
                "derived_path": sec_pay_derived_path,
                "booz_allen_rows_count": len(sec_pay),
                "example_row": sec_pay[0] if sec_pay else None,
                "source": {"dataset": "sec_pdf", "path": sec_pay_pdf_path},
            }
        )

    # Cross-links: contextual only, based on politician committee relevance.
    # Match PAC recipient_name to politician surname; if the politician has committees mapped to DoD/VA/GSA/DHS, link.
    cross_links = []
    for r in fec_b.get("results", []):
        rec = normalize(r.get("recipient_name"))
        for person, info in pol.items():
            last = normalize(person.split()[-1].strip(")"))
            if last and last in rec:
                rel = info.get("committees_relevant_to_agencies", {})
                agencies = [a for a, coms in rel.items() if coms]
                if not agencies:
                    continue
                cross_links.append(
                    {
                        "link_type": "political_giving_to_agency_contextual",
                        "confidence": "possible",
                        "rationale": "PAC recipient name contains politician surname; politician committee assignments indicate oversight/jurisdiction relevance to listed agencies. This is not evidence of influence.",
                        "political_giving": {
                            "fec_committee_id": r.get("committee_id"),
                            "fec_committee_name": r.get("committee"),
                            "recipient_name": r.get("recipient_name"),
                            "recipient_committee_id": r.get("recipient_committee_id"),
                            "candidate_name": r.get("candidate_name"),
                            "candidate_id": r.get("candidate_id"),
                            "disbursement_amount": r.get("disbursement_amount"),
                            "disbursement_date": r.get("disbursement_date"),
                            "fec_sub_id": r.get("sub_id"),
                            "source": {"dataset": "fec_schedule_b", "path": fec_b_path},
                        },
                        "politician_committee_evidence": {
                            "politician": person,
                            "office": info.get("office"),
                            "committees": info.get("committees"),
                            "committees_relevant_to_agencies": rel,
                            "sources": info.get("sources"),
                        },
                        "contracting_context": {
                            "top_awarding_agencies_source": us_ag_awarding_path,
                            "agencies_context": agencies,
                        },
                    }
                )

    # Basic entity map
    entity_map = [
        {
            "canonical": "BOOZ ALLEN HAMILTON",
            "variant": "BOOZ ALLEN HAMILTON INC",
            "context": "USAspending recipient name",
            "recipient_uei": (us_aw.get("results", [{}])[0] or {}).get("Recipient UEI"),
            "confidence": "confirmed",
        },
        {
            "canonical": "BOOZ ALLEN HAMILTON INC. PAC",
            "variant": (fec_committee.get("results", [{}])[0] or {}).get("name"),
            "context": "FEC committee",
            "committee_id": "C00709816",
            "confidence": "confirmed",
        },
    ]

    out = {
        "generated_at": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "subject": {"name": "Booz Allen Hamilton Holding Corporation", "ticker": "BAH", "cik": "0001443646"},
        "sources": [
            {
                "name": "USAspending API",
                "cache_paths": [us_aw_path, us_ag_awarding_path],
                "notes": "Queries limited to FY2024 time_period (2023-10-01 to 2024-09-30) and award_type_codes A-D.",
            },
            {
                "name": "FEC OpenFEC API",
                "cache_paths": [fec_committee_path, fec_b_path, fec_a_path],
                "notes": "Schedule A data filtered by exact employer string BOOZ ALLEN HAMILTON and is_individual=true for 2024 two-year transaction period.",
            },
            {"name": "SEC EDGAR submissions JSON", "cache_paths": [sec_sub_path]},
            {"name": "Politician committee assignments", "cache_paths": [pol_committees_path]},
            {
                "name": "SEC contract payment justifications PDF",
                "cache_paths": [sec_pay_pdf_path],
                "derived_paths": [sec_pay_derived_path],
            },
        ],
        "entity_map": entity_map,
        "top_contracts": top_contracts,
        "contract_agency_totals": contract_agency_totals,
        "contributions": pac_contrib + indiv,
        "sec_items": sec_items,
        "cross_links": cross_links,
        "limitations": [
            "USAspending amounts from spending_by_award are award totals as returned by the endpoint and may not equal obligations within FY2024.",
            "FEC individual contributions are filtered by exact employer string and will omit other Booz Allen variants (e.g., BOOZ-ALLEN, BOOZ ALLEN HAMILTON INC.).",
            "Cross-links between contributions and agencies are contextual and based on committee oversight relevance; they do not demonstrate causality or improper influence.",
        ],
    }

    with open("results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    print("WROTE results.json")
    print("top_contracts", len(top_contracts))
    print("contract_agency_totals", len(contract_agency_totals))
    print("contributions", len(pac_contrib) + len(indiv))
    print("sec_items", len(sec_items))
    print("cross_links", len(cross_links))


if __name__ == "__main__":
    main()

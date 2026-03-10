#!/usr/bin/env python3
"""Fetch entity-specific records from public records APIs.

Queries structured government APIs (SEC EDGAR, FEC, Senate LDA, USAspending)
for entity-specific records using urllib. For JavaScript-heavy portals (state
SOS sites), optionally delegates to Firecrawl as a subprocess.

Uses Python stdlib only — zero external dependencies.

Supported API sources:
    sec   — SEC EDGAR entity submissions (CIK lookup + filing history)
    fec   — FEC individual/committee contributions (requires FEC_API_KEY)
    lda   — Senate LDA lobbying filings by registrant/client name
    spend — USAspending.gov award search by recipient name

Usage:
    python3 scrape_records.py /path/to/workspace --entities "Acme Corp"
    python3 scrape_records.py /path/to/workspace --sources sec,fec,lda
    python3 scrape_records.py /path/to/workspace --all-entities --sources sec
    python3 scrape_records.py /path/to/workspace --entities "Acme" --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# API source definitions
# ---------------------------------------------------------------------------

_USER_AGENT = "OpenPlanter/1.0 openplanter@investigation.local"

# SEC EDGAR: rate limit ~10 req/sec, requires User-Agent with email
_SEC_FULLTEXT = "https://efts.sec.gov/LATEST/search-index?q={query}&dateRange=custom&startdt=2020-01-01&forms=10-K,10-Q,8-K,DEF+14A&hits.hits.total=true"
_SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
_SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"

# FEC: free API key at api.open.fec.gov, 1000 requests/hr
_FEC_COMMITTEES = "https://api.open.fec.gov/v1/names/committees/?q={query}&api_key={key}"
_FEC_CANDIDATES = "https://api.open.fec.gov/v1/names/candidates/?q={query}&api_key={key}"

# Senate LDA: no auth, ~1 req/sec polite
_LDA_FILINGS = "https://lda.senate.gov/api/v1/filings/?filing_type=1&registrant_name={query}&format=json&page_size=25"
_LDA_REGISTRANTS = "https://lda.senate.gov/api/v1/registrants/?name={query}&format=json&page_size=25"

# USAspending: no auth, liberal rate limits
_SPEND_SEARCH = "https://api.usaspending.gov/api/v2/search/spending_by_award/"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _http_get(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> bytes:
    """GET request via urllib, return raw bytes."""
    hdrs = {"User-Agent": _USER_AGENT}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _http_post_json(url: str, payload: dict, timeout: int = 30) -> bytes:
    """POST JSON via urllib, return raw bytes."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": _USER_AGENT,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


# ---------------------------------------------------------------------------
# Source-specific fetchers
# ---------------------------------------------------------------------------

def fetch_sec(entity_name: str, dest_dir: Path, timeout: int) -> dict:
    """Look up entity on SEC EDGAR and fetch submissions."""
    # Step 1: Find CIK via company tickers JSON
    print(f"    SEC: Looking up CIK for '{entity_name}'")
    try:
        raw = _http_get(_SEC_TICKERS, timeout=timeout)
        tickers = json.loads(raw)
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        return {"source": "sec", "status": "error", "error": f"Ticker lookup failed: {e}"}

    # Search for matching entity (case-insensitive substring)
    query_lower = entity_name.lower()
    matches = []
    for _key, entry in tickers.items():
        title = entry.get("title", "").lower()
        if query_lower in title or title in query_lower:
            matches.append(entry)

    if not matches:
        return {"source": "sec", "status": "no_match", "entity": entity_name}

    # Fetch submissions for best match
    best = matches[0]
    cik = str(best.get("cik_str", best.get("cik", ""))).zfill(10)
    print(f"    SEC: Found CIK {cik} ({best.get('title', '')})")

    try:
        sub_url = _SEC_SUBMISSIONS.format(cik=cik)
        sub_raw = _http_get(sub_url, timeout=timeout)
        submissions = json.loads(sub_raw)
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        return {"source": "sec", "status": "error", "error": f"Submissions fetch failed: {e}"}

    # Write to file
    out_file = dest_dir / "sec" / f"{cik}.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_bytes(sub_raw)

    recent_filings = submissions.get("filings", {}).get("recent", {})
    filing_count = len(recent_filings.get("accessionNumber", []))

    return {
        "source": "sec",
        "status": "ok",
        "entity": entity_name,
        "cik": cik,
        "company_name": submissions.get("name", ""),
        "filing_count": filing_count,
        "file": str(out_file.relative_to(dest_dir.parent.parent)),
    }


def fetch_fec(entity_name: str, dest_dir: Path, timeout: int) -> dict:
    """Search FEC for committees/candidates matching entity name."""
    api_key = os.environ.get("FEC_API_KEY", "DEMO_KEY")
    if api_key == "DEMO_KEY":
        print("    FEC: Using DEMO_KEY (limited to 1000 req/hr). Set FEC_API_KEY for production.")

    print(f"    FEC: Searching committees for '{entity_name}'")
    encoded = urllib.parse.quote(entity_name)

    try:
        url = _FEC_COMMITTEES.format(query=encoded, key=api_key)
        raw = _http_get(url, timeout=timeout)
        data = json.loads(raw)
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        # Strip API key from error message to prevent leaking credentials
        err_msg = str(e).replace(api_key, "***")
        return {"source": "fec", "status": "error", "error": f"Committee search failed: {err_msg}"}

    results = data.get("results", [])

    # Write results
    safe_name = re.sub(r"[^\w\-]", "_", entity_name.lower())[:60]
    out_file = dest_dir / "fec" / f"{safe_name}.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(results, indent=2), encoding="utf-8")

    return {
        "source": "fec",
        "status": "ok" if results else "no_match",
        "entity": entity_name,
        "match_count": len(results),
        "file": str(out_file.relative_to(dest_dir.parent.parent)),
    }


def fetch_lda(entity_name: str, dest_dir: Path, timeout: int) -> dict:
    """Search Senate LDA for lobbying filings by registrant name."""
    print(f"    LDA: Searching registrants for '{entity_name}'")
    encoded = urllib.parse.quote(entity_name)

    try:
        url = _LDA_REGISTRANTS.format(query=encoded)
        raw = _http_get(url, timeout=timeout)
        data = json.loads(raw)
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        return {"source": "lda", "status": "error", "error": f"LDA search failed: {e}"}

    results = data.get("results", [])

    safe_name = re.sub(r"[^\w\-]", "_", entity_name.lower())[:60]
    out_file = dest_dir / "lda" / f"{safe_name}.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(results, indent=2), encoding="utf-8")

    return {
        "source": "lda",
        "status": "ok" if results else "no_match",
        "entity": entity_name,
        "match_count": len(results),
        "file": str(out_file.relative_to(dest_dir.parent.parent)),
    }


def fetch_spend(entity_name: str, dest_dir: Path, timeout: int) -> dict:
    """Search USAspending.gov for awards to entity."""
    print(f"    USAspending: Searching awards for '{entity_name}'")

    payload = {
        "filters": {
            "keyword": entity_name,
            "time_period": [{"start_date": "2020-01-01", "end_date": "2026-12-31"}],
        },
        "fields": [
            "Award ID", "Recipient Name", "Award Amount",
            "Awarding Agency", "Award Type", "Start Date",
        ],
        "page": 1,
        "limit": 25,
        "sort": "Award Amount",
        "order": "desc",
    }

    try:
        raw = _http_post_json(_SPEND_SEARCH, payload, timeout=timeout)
        data = json.loads(raw)
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        return {"source": "spend", "status": "error", "error": f"USAspending search failed: {e}"}

    results = data.get("results", [])

    safe_name = re.sub(r"[^\w\-]", "_", entity_name.lower())[:60]
    out_file = dest_dir / "spend" / f"{safe_name}.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(results, indent=2), encoding="utf-8")

    return {
        "source": "spend",
        "status": "ok" if results else "no_match",
        "entity": entity_name,
        "match_count": len(results),
        "file": str(out_file.relative_to(dest_dir.parent.parent)),
    }


# ---------------------------------------------------------------------------
# Source registry
# ---------------------------------------------------------------------------

SOURCES = {
    "sec": {"name": "SEC EDGAR", "func": fetch_sec, "auth": "User-Agent header (built-in)"},
    "fec": {"name": "FEC API", "func": fetch_fec, "auth": "FEC_API_KEY (DEMO_KEY fallback)"},
    "lda": {"name": "Senate LDA", "func": fetch_lda, "auth": "None"},
    "spend": {"name": "USAspending", "func": fetch_spend, "auth": "None"},
}


def load_entity_names(workspace: Path) -> list[str]:
    """Load canonical entity names from entities/canonical.json."""
    canon_path = workspace / "entities" / "canonical.json"
    if not canon_path.exists():
        return []
    try:
        data = json.loads(canon_path.read_text(encoding="utf-8"))
        entities = data.get("entities", data) if isinstance(data, dict) else data
        return [e.get("canonical_name", "") for e in entities if e.get("canonical_name")]
    except (json.JSONDecodeError, OSError):
        return []


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch entity-specific records from public records APIs"
    )
    parser.add_argument(
        "workspace", type=Path,
        help="Path to investigation workspace",
    )
    parser.add_argument(
        "--entities", nargs="+",
        help="Entity names to search for",
    )
    parser.add_argument(
        "--all-entities", action="store_true",
        help="Search for all entities in entities/canonical.json",
    )
    parser.add_argument(
        "--sources", type=str, default="sec,fec,lda,spend",
        help=f"Comma-separated API sources (default: all). "
             f"Available: {', '.join(SOURCES.keys())}",
    )
    parser.add_argument(
        "--list", action="store_true", dest="list_sources",
        help="List available API sources and exit",
    )
    parser.add_argument(
        "--timeout", type=int, default=30,
        help="HTTP timeout per request in seconds (default: 30)",
    )
    parser.add_argument(
        "--delay", type=float, default=1.0,
        help="Delay between API calls in seconds (default: 1.0)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be fetched without making API calls",
    )
    args = parser.parse_args()

    if args.list_sources:
        print("Available API sources:\n")
        for sid, spec in SOURCES.items():
            print(f"  {sid:8s}  {spec['name']}")
            print(f"  {'':<8s}  Auth: {spec['auth']}")
            print()
        return

    workspace = args.workspace.resolve()
    if not workspace.exists():
        print(f"Error: workspace does not exist: {workspace}", file=sys.stderr)
        sys.exit(1)

    # Resolve entities
    entity_names: list[str] = []
    if args.entities:
        entity_names = args.entities
    elif args.all_entities:
        entity_names = load_entity_names(workspace)
        if not entity_names:
            print("No canonical entities found. Run entity_resolver.py first or use --entities.")
            sys.exit(1)
    else:
        print("Error: specify --entities or --all-entities", file=sys.stderr)
        sys.exit(1)

    # Resolve sources
    source_ids = [s.strip() for s in args.sources.split(",")]
    unknown = [s for s in source_ids if s not in SOURCES]
    if unknown:
        print(f"Error: unknown source(s): {', '.join(unknown)}\n"
              f"Available: {', '.join(SOURCES.keys())}", file=sys.stderr)
        sys.exit(1)

    dest_dir = workspace / "datasets" / "scraped"
    dest_dir.mkdir(parents=True, exist_ok=True)

    print(f"Fetching records for {len(entity_names)} entity/entities "
          f"from {len(source_ids)} source(s)\n")

    if args.dry_run:
        for name in entity_names:
            for sid in source_ids:
                print(f"  [dry-run] Would query {SOURCES[sid]['name']}: {name}")
        return

    all_results: list[dict] = []
    for name in entity_names:
        print(f"  Entity: {name}")
        for sid in source_ids:
            fetch_fn = SOURCES[sid]["func"]
            result = fetch_fn(name, dest_dir, args.timeout)
            result["query_entity"] = name
            all_results.append(result)

            if args.delay > 0:
                time.sleep(args.delay)
        print()

    # Write provenance log
    provenance = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "entities_queried": entity_names,
        "sources": source_ids,
        "results": all_results,
    }
    prov_file = dest_dir / "provenance.json"
    prov_file.write_text(json.dumps(provenance, indent=2), encoding="utf-8")

    ok = sum(1 for r in all_results if r["status"] == "ok")
    no_match = sum(1 for r in all_results if r["status"] == "no_match")
    errs = sum(1 for r in all_results if r["status"] == "error")
    print(f"Done: {ok} matched, {no_match} no match, {errs} errors "
          f"out of {len(all_results)} queries")
    print(f"Results in: {dest_dir}")

    if errs:
        sys.exit(1)


if __name__ == "__main__":
    main()

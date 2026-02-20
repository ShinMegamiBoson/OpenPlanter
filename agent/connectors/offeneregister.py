"""OffeneRegister bulk JSONL connector.

Searches pre-downloaded bulk JSONL data from OffeneRegister (~5.1M German
companies, CC0 license). The agent uses run_shell to download the bulk
file; this connector searches the local copy.

Data format: one JSON object per line with fields like:
  {"company_number":"...", "name":"...", "registered_address":"...",
   "officers":[...], "all_attributes":{...}, ...}
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from ..normalizers.german import (
    extract_legal_form,
    normalize_company_name,
    umlauts_to_ascii,
)


def _fuzzy_match(query_normalized: str, name: str) -> bool:
    """Check if query tokens all appear in the normalized company name."""
    target = normalize_company_name(name)
    tokens = query_normalized.split()
    return all(tok in target for tok in tokens)


def _normalize_officer(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize an officer record from OffeneRegister."""
    return {
        "name": raw.get("name", ""),
        "role": raw.get("position", "") or raw.get("role", ""),
        "start_date": raw.get("start_date", ""),
        "end_date": raw.get("end_date", ""),
    }


def _normalize_entry(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize an OffeneRegister company entry."""
    name = raw.get("name", "")
    officers_raw = raw.get("officers", [])
    officers = [_normalize_officer(o) for o in officers_raw if isinstance(o, dict)]

    # Extract register info from all_attributes or top level
    attrs = raw.get("all_attributes", {}) or {}
    registered_address = raw.get("registered_address", "") or attrs.get("registered_address", "")

    # Parse court and register number from company_number or all_attributes
    company_number = raw.get("company_number", "")
    court = attrs.get("court", "") or ""
    register_type = ""
    register_number = company_number

    # Try to split "HRB 12345" pattern
    hrb_match = re.match(r"^(HR[AB])\s*(\d+.*)$", company_number, re.IGNORECASE)
    if hrb_match:
        register_type = hrb_match.group(1).upper()
        register_number = hrb_match.group(2).strip()

    return {
        "name": name,
        "legal_form": extract_legal_form(name) or "",
        "registered_office": registered_address,
        "officers": [o["name"] for o in officers if o.get("name")],
        "officers_detail": officers,
        "hrb_number": company_number,
        "register_type": register_type,
        "register_number": register_number,
        "court": court,
        "status": raw.get("current_status", "") or attrs.get("current_status", ""),
        "raw_id": raw.get("company_number", ""),
    }


def search_offeneregister(
    query: str,
    data_path: str,
    max_results: int = 20,
) -> str:
    """Search OffeneRegister bulk JSONL file for matching companies.

    Args:
        query: Company name or search terms.
        data_path: Path to the bulk JSONL file.
        max_results: Maximum number of results to return.

    Returns:
        JSON string with search results.
    """
    if not query.strip():
        return json.dumps({"error": "Empty query"})

    path = Path(data_path)
    if not path.exists():
        return json.dumps({
            "error": f"Data file not found: {data_path}",
            "hint": (
                "Download the OffeneRegister bulk JSONL file first. "
                "See https://offeneregister.de/daten/ for download links."
            ),
        })

    query_normalized = normalize_company_name(query)
    # Also prepare ASCII-folded variant for broader matching
    query_ascii = umlauts_to_ascii(query.strip().lower())

    results: list[dict[str, Any]] = []
    scanned = 0
    errors = 0

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                scanned += 1
                line = line.strip()
                if not line:
                    continue

                # Quick pre-filter: check if any query token appears in raw line
                line_lower = line.lower()
                if query_ascii not in line_lower and not any(
                    tok in line_lower for tok in query_normalized.split()
                ):
                    continue

                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    errors += 1
                    continue

                if not isinstance(record, dict):
                    continue

                name = record.get("name", "")
                if not name:
                    continue

                if _fuzzy_match(query_normalized, name):
                    results.append(_normalize_entry(record))
                    if len(results) >= max_results:
                        break

    except OSError as exc:
        return json.dumps({"error": f"Failed to read data file: {exc}"})

    return json.dumps({
        "source": "offeneregister",
        "query": query,
        "data_path": str(path),
        "lines_scanned": scanned,
        "parse_errors": errors,
        "total_results": len(results),
        "results": results,
    }, ensure_ascii=False, indent=2)

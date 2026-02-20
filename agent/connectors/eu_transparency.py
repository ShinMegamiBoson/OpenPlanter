"""EU Transparency Register connector.

Searches pre-downloaded bulk CSV data from the EU Transparency Register
(data.europa.eu). Handles both CSV and XML formats.
"""
from __future__ import annotations

import csv
import json
import io
import re
from pathlib import Path
from typing import Any

from ..normalizers.german import normalize_company_name, umlauts_to_ascii


def _fuzzy_match(query_normalized: str, name: str) -> bool:
    """Check if query tokens all appear in the normalized name."""
    target = normalize_company_name(name)
    tokens = query_normalized.split()
    return all(tok in target for tok in tokens)


def _normalize_csv_entry(row: dict[str, str]) -> dict[str, Any]:
    """Normalize a CSV row from the EU Transparency Register."""
    # The CSV format varies; handle common column names
    name = (
        row.get("Name", "")
        or row.get("Organisation name", "")
        or row.get("name", "")
        or row.get("organisationName", "")
    )
    return {
        "name": name,
        "identification_code": row.get("Identification code", "") or row.get("identificationCode", ""),
        "category": (
            row.get("Category", "")
            or row.get("Section", "")
            or row.get("category", "")
        ),
        "country": (
            row.get("Country of head office", "")
            or row.get("Head office country", "")
            or row.get("country", "")
        ),
        "eu_lobbying_expenditure": (
            row.get("Estimated costs", "")
            or row.get("Costs of direct lobbying", "")
            or row.get("estimatedCosts", "")
        ),
        "num_lobbyists": (
            row.get("Number of persons", "")
            or row.get("numberOfPersons", "")
        ),
        "legislative_interests": _split_field(
            row.get("Fields of interest", "")
            or row.get("fieldsOfInterest", "")
        ),
        "registration_date": (
            row.get("Registration date", "")
            or row.get("registrationDate", "")
        ),
        "website": row.get("Website", "") or row.get("website", ""),
    }


def _split_field(value: str) -> list[str]:
    """Split a semicolon or comma-delimited field into a list."""
    if not value:
        return []
    # Try semicolon first, then comma
    if ";" in value:
        return [v.strip() for v in value.split(";") if v.strip()]
    return [v.strip() for v in value.split(",") if v.strip()]


def _parse_xml_entry(text: str) -> dict[str, Any]:
    """Minimal XML tag extraction without external dependencies."""
    def _extract_tag(tag: str) -> str:
        match = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", text, re.DOTALL)
        return match.group(1).strip() if match else ""

    return {
        "name": _extract_tag("name") or _extract_tag("organisationName"),
        "identification_code": _extract_tag("identificationCode"),
        "category": _extract_tag("category") or _extract_tag("section"),
        "country": _extract_tag("country") or _extract_tag("headOfficeCountry"),
        "eu_lobbying_expenditure": _extract_tag("estimatedCosts") or _extract_tag("lobbyCosts"),
        "num_lobbyists": _extract_tag("numberOfPersons"),
        "legislative_interests": _split_field(_extract_tag("fieldsOfInterest")),
        "registration_date": _extract_tag("registrationDate"),
        "website": _extract_tag("website"),
    }


def search_eu_transparency(
    query: str,
    data_path: str,
    max_results: int = 20,
) -> str:
    """Search EU Transparency Register bulk data for matching entries.

    Args:
        query: Organization name or search terms.
        data_path: Path to the bulk CSV or XML file.
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
                "Download EU Transparency Register data from "
                "https://data.europa.eu/data/datasets/transparency-register"
            ),
        })

    suffix = path.suffix.lower()
    if suffix == ".xml":
        return _search_xml(query, path, max_results)
    return _search_csv(query, path, max_results)


def _search_csv(query: str, path: Path, max_results: int) -> str:
    """Search a CSV format EU Transparency Register file."""
    query_normalized = normalize_company_name(query)
    query_ascii = umlauts_to_ascii(query.strip().lower())

    results: list[dict[str, Any]] = []
    scanned = 0

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            # Sniff delimiter
            sample = fh.read(4096)
            fh.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel

            reader = csv.DictReader(fh, dialect=dialect)
            for row in reader:
                scanned += 1
                name = (
                    row.get("Name", "")
                    or row.get("Organisation name", "")
                    or row.get("name", "")
                    or row.get("organisationName", "")
                )
                if not name:
                    continue

                name_lower = name.lower()
                if query_ascii not in name_lower and not _fuzzy_match(query_normalized, name):
                    continue

                results.append(_normalize_csv_entry(row))
                if len(results) >= max_results:
                    break

    except OSError as exc:
        return json.dumps({"error": f"Failed to read data file: {exc}"})

    return json.dumps({
        "source": "eu_transparency_register",
        "query": query,
        "data_path": str(path),
        "rows_scanned": scanned,
        "total_results": len(results),
        "results": results,
    }, ensure_ascii=False, indent=2)


def _search_xml(query: str, path: Path, max_results: int) -> str:
    """Search an XML format EU Transparency Register file."""
    query_normalized = normalize_company_name(query)
    query_ascii = umlauts_to_ascii(query.strip().lower())

    results: list[dict[str, Any]] = []
    scanned = 0

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return json.dumps({"error": f"Failed to read data file: {exc}"})

    # Split on record tags (common patterns)
    record_pattern = re.compile(
        r"<(?:interestRepresentative|entry|organisation)[^>]*>.*?</(?:interestRepresentative|entry|organisation)>",
        re.DOTALL,
    )

    for match in record_pattern.finditer(content):
        scanned += 1
        block = match.group()
        block_lower = block.lower()

        if query_ascii not in block_lower:
            continue

        entry = _parse_xml_entry(block)
        name = entry.get("name", "")
        if name and _fuzzy_match(query_normalized, name):
            results.append(entry)
            if len(results) >= max_results:
                break

    return json.dumps({
        "source": "eu_transparency_register",
        "query": query,
        "data_path": str(path),
        "records_scanned": scanned,
        "total_results": len(results),
        "results": results,
    }, ensure_ascii=False, indent=2)

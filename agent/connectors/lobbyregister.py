"""Lobbyregister Bundestag API connector.

Accesses the German federal lobby register via its public REST API.
Documentation: https://www.lobbyregister.bundestag.de/api/
"""
from __future__ import annotations

import json
import urllib.parse
from typing import Any

from . import ConnectorError, _api_request

_BASE_URL = "https://www.lobbyregister.bundestag.de/api/v1"

# Valid sort parameters for search.
VALID_SORTS = (
    "ALPHABETICAL_ASC",
    "ALPHABETICAL_DESC",
    "FINANCIALEXPENSES_ASC",
    "FINANCIALEXPENSES_DESC",
    "DONATIONS_ASC",
    "DONATIONS_DESC",
    "REGISTRATION_DATE_ASC",
    "REGISTRATION_DATE_DESC",
)

# Fields-of-interest filter codes (Interessenbereiche).
FOI_CODES: dict[str, str] = {
    "agriculture": "AGRICULTURE",
    "defence": "DEFENCE",
    "digital": "DIGITAL",
    "economy": "ECONOMY",
    "education": "EDUCATION",
    "energy": "ENERGY",
    "environment": "ENVIRONMENT",
    "europe": "EUROPE",
    "finance": "FINANCE",
    "foreign": "FOREIGN",
    "health": "HEALTH",
    "home": "HOME",
    "housing": "HOUSING",
    "justice": "JUSTICE",
    "labour": "LABOUR",
    "media": "MEDIA",
    "science": "SCIENCE",
    "social": "SOCIAL",
    "traffic": "TRAFFIC",
}


def _build_search_url(
    query: str,
    sort: str = "ALPHABETICAL_ASC",
    page: int = 0,
    size: int = 20,
    foi_filter: str | None = None,
    api_key: str = "",
) -> str:
    """Build the search URL with query parameters."""
    params: dict[str, str] = {
        "q": query,
        "sort": sort if sort in VALID_SORTS else "ALPHABETICAL_ASC",
        "page": str(max(0, page)),
        "size": str(max(1, min(size, 50))),
    }
    if foi_filter and foi_filter.upper() in FOI_CODES.values():
        params["fieldOfInterest"] = foi_filter.upper()
    elif foi_filter and foi_filter.lower() in FOI_CODES:
        params["fieldOfInterest"] = FOI_CODES[foi_filter.lower()]
    if api_key:
        params["apikey"] = api_key
    return f"{_BASE_URL}/sucheDetailJson?{urllib.parse.urlencode(params)}"


def _normalize_entry(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a Lobbyregister entry to a standard shape."""
    general = raw.get("general", {}) or {}
    financial = raw.get("financialInformation", {}) or {}
    activity = raw.get("activity", {}) or {}

    # Extract clients list
    clients: list[str] = []
    for client in (activity.get("clients") or []):
        if isinstance(client, dict):
            clients.append(client.get("name", ""))
        elif isinstance(client, str):
            clients.append(client)

    # Fields of interest
    fois: list[str] = []
    for foi in (activity.get("fieldsOfInterest") or []):
        if isinstance(foi, dict):
            fois.append(foi.get("name", "") or foi.get("code", ""))
        elif isinstance(foi, str):
            fois.append(foi)

    return {
        "name": general.get("name", "") or raw.get("name", ""),
        "register_number": raw.get("registerNumber", ""),
        "entry_id": raw.get("id", ""),
        "org_type": general.get("organizationType", ""),
        "legal_form": general.get("legalForm", ""),
        "address": _format_address(general.get("address")),
        "employees": general.get("numberOfEmployees", ""),
        "financial_expenditure": financial.get("financialExpenditure", ""),
        "financial_year": financial.get("financialYear", ""),
        "donations_flag": bool(financial.get("donations")),
        "fields_of_interest": fois,
        "clients": clients,
        "registration_date": raw.get("registrationDate", ""),
        "last_update": raw.get("lastUpdate", ""),
    }


def _format_address(addr: dict[str, Any] | None) -> str:
    """Format an address dict to a single string."""
    if not addr or not isinstance(addr, dict):
        return ""
    parts = [
        addr.get("street", ""),
        addr.get("zipCode", ""),
        addr.get("city", ""),
        addr.get("country", ""),
    ]
    return ", ".join(p for p in parts if p)


def search_lobbyregister(
    query: str,
    api_key: str = "",
    sort: str = "ALPHABETICAL_ASC",
    max_results: int = 20,
    foi_filter: str | None = None,
) -> str:
    """Search the Lobbyregister and return normalized JSON results."""
    if not query.strip():
        return json.dumps({"error": "Empty query"})

    url = _build_search_url(
        query=query.strip(),
        sort=sort,
        size=min(max_results, 50),
        foi_filter=foi_filter,
        api_key=api_key,
    )

    try:
        data = _api_request(url, timeout=30)
    except ConnectorError as exc:
        return json.dumps({"error": str(exc), "query": query})

    results: list[dict[str, Any]] = []
    entries = data.get("content", []) or data.get("results", []) or []
    if isinstance(entries, list):
        for entry in entries[:max_results]:
            if isinstance(entry, dict):
                results.append(_normalize_entry(entry))

    return json.dumps({
        "source": "lobbyregister_bundestag",
        "query": query,
        "total_results": data.get("totalElements", len(results)),
        "results": results,
    }, ensure_ascii=False, indent=2)


def get_lobbyregister_entry(
    register_number: str,
    entry_id: str,
    api_key: str = "",
) -> str:
    """Fetch a single Lobbyregister entry by register number and entry ID."""
    params: dict[str, str] = {}
    if api_key:
        params["apikey"] = api_key
    qs = f"?{urllib.parse.urlencode(params)}" if params else ""
    url = f"{_BASE_URL}/register/{urllib.parse.quote(register_number)}/{urllib.parse.quote(entry_id)}{qs}"

    try:
        data = _api_request(url, timeout=30)
    except ConnectorError as exc:
        return json.dumps({"error": str(exc), "register_number": register_number})

    return json.dumps({
        "source": "lobbyregister_bundestag",
        "entry": _normalize_entry(data),
    }, ensure_ascii=False, indent=2)

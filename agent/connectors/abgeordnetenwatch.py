"""abgeordnetenwatch.de API v2 connector.

Accesses German MP data, votes, questions, and side income via the
public CC0-licensed REST API.
Base URL: https://www.abgeordnetenwatch.de/api/v2/
No authentication required.
"""
from __future__ import annotations

import json
import urllib.parse
from typing import Any

from . import ConnectorError, _api_request

_BASE_URL = "https://www.abgeordnetenwatch.de/api/v2"


def _build_url(endpoint: str, params: dict[str, Any] | None = None) -> str:
    """Build API URL with optional query parameters."""
    url = f"{_BASE_URL}/{endpoint.lstrip('/')}"
    if params:
        # Filter out None values
        clean = {k: str(v) for k, v in params.items() if v is not None}
        if clean:
            url += f"?{urllib.parse.urlencode(clean)}"
    return url


def _normalize_politician(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a politician record."""
    return {
        "id": raw.get("id"),
        "label": raw.get("label", ""),
        "first_name": raw.get("first_name", ""),
        "last_name": raw.get("last_name", ""),
        "birth_name": raw.get("birth_name", ""),
        "year_of_birth": raw.get("year_of_birth"),
        "party": _extract_party(raw),
        "occupation": raw.get("occupation", ""),
        "education": raw.get("education", ""),
        "url": raw.get("abgeordnetenwatch_url", ""),
        "mandates": _extract_mandates(raw),
    }


def _extract_party(raw: dict[str, Any]) -> str:
    """Extract party name from nested party object."""
    party = raw.get("party")
    if isinstance(party, dict):
        return party.get("label", "") or party.get("full_name", "")
    return str(party) if party else ""


def _extract_mandates(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract mandates from related data."""
    mandates_raw = raw.get("mandates") or raw.get("related_data", {}).get("mandates", {})
    if isinstance(mandates_raw, dict):
        mandates_raw = mandates_raw.get("data", [])
    if not isinstance(mandates_raw, list):
        return []
    result: list[dict[str, Any]] = []
    for m in mandates_raw:
        if not isinstance(m, dict):
            continue
        result.append({
            "id": m.get("id"),
            "label": m.get("label", ""),
            "parliament_period": _nested_label(m.get("parliament_period")),
            "fraction": _nested_label(m.get("fraction")),
            "start_date": m.get("start_date", ""),
            "end_date": m.get("end_date", ""),
        })
    return result


def _nested_label(obj: Any) -> str:
    if isinstance(obj, dict):
        return obj.get("label", "") or obj.get("full_name", "")
    return str(obj) if obj else ""


def _normalize_sidejob(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a sidejob record."""
    return {
        "id": raw.get("id"),
        "label": raw.get("label", ""),
        "organization": raw.get("sidejob_organization", {}).get("label", "") if isinstance(raw.get("sidejob_organization"), dict) else "",
        "category": raw.get("category", ""),
        "income_level": raw.get("income_level", ""),
        "interval": raw.get("interval", ""),
        "created": raw.get("created", ""),
        "politician_id": _extract_nested_id(raw.get("mandate", {})),
    }


def _extract_nested_id(obj: Any) -> int | None:
    if isinstance(obj, dict):
        pol = obj.get("politician")
        if isinstance(pol, dict):
            return pol.get("id")
        return obj.get("id")
    return None


def _normalize_vote(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a vote record."""
    return {
        "id": raw.get("id"),
        "vote": raw.get("vote", ""),
        "reason_no_show": raw.get("reason_no_show", ""),
        "mandate": _nested_label(raw.get("mandate")),
        "fraction": _nested_label(raw.get("fraction")),
        "poll_id": raw.get("poll", {}).get("id") if isinstance(raw.get("poll"), dict) else None,
    }


def search_politicians(
    query: str | None = None,
    parliament_period: int | None = None,
    party_id: int | None = None,
    max_results: int = 20,
) -> str:
    """Search politicians on abgeordnetenwatch."""
    params: dict[str, Any] = {
        "range_end": min(max_results, 100),
    }
    if parliament_period is not None:
        params["parliament_period"] = parliament_period
    if party_id is not None:
        params["party"] = party_id
    if query:
        params["label[cn]"] = query

    url = _build_url("politicians", params)

    try:
        data = _api_request(url, timeout=30)
    except ConnectorError as exc:
        return json.dumps({"error": str(exc), "query": query})

    results: list[dict[str, Any]] = []
    entries = data.get("data", [])
    if isinstance(entries, list):
        for entry in entries[:max_results]:
            if isinstance(entry, dict):
                results.append(_normalize_politician(entry))

    meta = data.get("meta", {})
    return json.dumps({
        "source": "abgeordnetenwatch",
        "query": query,
        "total_results": meta.get("result", {}).get("total", len(results)) if isinstance(meta, dict) else len(results),
        "results": results,
    }, ensure_ascii=False, indent=2)


def get_politician(politician_id: int) -> str:
    """Fetch a single politician with mandates."""
    url = _build_url(f"politicians/{politician_id}", {"related_data": "mandates"})

    try:
        data = _api_request(url, timeout=30)
    except ConnectorError as exc:
        return json.dumps({"error": str(exc), "politician_id": politician_id})

    entry = data.get("data", data)
    if isinstance(entry, dict):
        entry = _normalize_politician(entry)

    return json.dumps({
        "source": "abgeordnetenwatch",
        "politician": entry,
    }, ensure_ascii=False, indent=2)


def get_poll_votes(poll_id: int, max_results: int = 100) -> str:
    """Fetch votes for a specific poll."""
    url = _build_url(f"polls/{poll_id}/votes", {"range_end": min(max_results, 500)})

    try:
        data = _api_request(url, timeout=30)
    except ConnectorError as exc:
        return json.dumps({"error": str(exc), "poll_id": poll_id})

    results: list[dict[str, Any]] = []
    entries = data.get("data", [])
    if isinstance(entries, list):
        for entry in entries[:max_results]:
            if isinstance(entry, dict):
                results.append(_normalize_vote(entry))

    return json.dumps({
        "source": "abgeordnetenwatch",
        "poll_id": poll_id,
        "total_votes": len(results),
        "votes": results,
    }, ensure_ascii=False, indent=2)


def search_sidejobs(
    politician_id: int | None = None,
    max_results: int = 50,
) -> str:
    """Search sidejobs (Nebeneinkünfte)."""
    params: dict[str, Any] = {
        "range_end": min(max_results, 200),
    }
    if politician_id is not None:
        params["politician"] = politician_id

    url = _build_url("sidejobs", params)

    try:
        data = _api_request(url, timeout=30)
    except ConnectorError as exc:
        return json.dumps({"error": str(exc), "politician_id": politician_id})

    results: list[dict[str, Any]] = []
    entries = data.get("data", [])
    if isinstance(entries, list):
        for entry in entries[:max_results]:
            if isinstance(entry, dict):
                results.append(_normalize_sidejob(entry))

    return json.dumps({
        "source": "abgeordnetenwatch",
        "politician_id": politician_id,
        "total_results": len(results),
        "sidejobs": results,
    }, ensure_ascii=False, indent=2)

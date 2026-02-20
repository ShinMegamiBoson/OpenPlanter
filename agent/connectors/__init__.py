"""German/EU data source connectors for OpenPlanter.

Shared HTTP helper following the urllib.request pattern from tools.py.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
import urllib.parse
from typing import Any


class ConnectorError(RuntimeError):
    """Raised when a connector request fails."""


def _api_request(
    url: str,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    timeout: int = 30,
) -> dict[str, Any]:
    """Stdlib HTTP helper (urllib.request). Returns parsed JSON."""
    hdrs = {
        "User-Agent": "OpenPlanter/1.0",
        "Accept": "application/json",
    }
    if headers:
        hdrs.update(headers)

    data: bytes | None = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        hdrs["Content-Type"] = "application/json"

    req = urllib.request.Request(url=url, data=data, headers=hdrs, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ConnectorError(f"HTTP {exc.code}: {body[:500]}") from exc
    except urllib.error.URLError as exc:
        raise ConnectorError(f"Connection error: {exc}") from exc
    except OSError as exc:
        raise ConnectorError(f"Network error: {exc}") from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConnectorError(f"Non-JSON response: {raw[:500]}") from exc
    if not isinstance(parsed, dict):
        raise ConnectorError(f"Expected JSON object, got {type(parsed).__name__}")
    return parsed


def _api_request_list(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
) -> list[dict[str, Any]]:
    """Like _api_request but expects a JSON array at top level."""
    hdrs = {
        "User-Agent": "OpenPlanter/1.0",
        "Accept": "application/json",
    }
    if headers:
        hdrs.update(headers)

    req = urllib.request.Request(url=url, headers=hdrs, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ConnectorError(f"HTTP {exc.code}: {body[:500]}") from exc
    except urllib.error.URLError as exc:
        raise ConnectorError(f"Connection error: {exc}") from exc
    except OSError as exc:
        raise ConnectorError(f"Network error: {exc}") from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConnectorError(f"Non-JSON response: {raw[:500]}") from exc
    if isinstance(parsed, dict):
        return [parsed]
    if not isinstance(parsed, list):
        raise ConnectorError(f"Expected JSON array, got {type(parsed).__name__}")
    return parsed

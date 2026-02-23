"""Exa API client for web search and URL content fetching.

Ported from agent/tools.py (web_search, fetch_url) and modernized
to use httpx.AsyncClient instead of urllib.request.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass(frozen=True)
class SearchResultItem:
    """A single search result from the Exa API."""

    url: str
    title: str
    snippet: str
    text: str | None = None


@dataclass(frozen=True)
class SearchResult:
    """Response from an Exa search query."""

    query: str
    results: list[SearchResultItem]
    total: int


@dataclass(frozen=True)
class PageContent:
    """Fetched content from a single URL."""

    url: str
    title: str
    text: str


class ExaError(Exception):
    """Raised when an Exa API call fails."""


class ExaClient:
    """Async client for the Exa search API.

    Parameters
    ----------
    api_key : str
        Exa API key for authentication.
    base_url : str
        Base URL for the Exa API (default: https://api.exa.ai).
    timeout : float
        Request timeout in seconds (default: 30.0).
    max_text_chars : int
        Maximum characters to return for text content (default: 8000).
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.exa.ai",
        timeout: float = 30.0,
        max_text_chars: int = 8000,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ExaError("EXA_API_KEY must be a non-empty string")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_text_chars = max_text_chars
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazily create and return the underlying httpx client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "x-api-key": self.api_key,
                    "Content-Type": "application/json",
                    "User-Agent": "redthread/0.1.0",
                },
                timeout=self.timeout,
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying httpx client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _clip(text: str, max_chars: int) -> str:
        """Truncate text to max_chars with an indicator if clipped."""
        if len(text) <= max_chars:
            return text
        omitted = len(text) - max_chars
        return f"{text[:max_chars]}\n\n...[truncated {omitted} chars]..."

    async def _request(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Send a POST request to the Exa API and return the parsed JSON response.

        Raises
        ------
        ExaError
            On HTTP errors, connection failures, or invalid JSON responses.
        """
        client = await self._get_client()
        try:
            response = await client.post(endpoint, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text
            raise ExaError(f"Exa API HTTP {exc.response.status_code}: {body}") from exc
        except httpx.TimeoutException as exc:
            raise ExaError(f"Exa API request timed out: {exc}") from exc
        except httpx.ConnectError as exc:
            raise ExaError(f"Exa API connection error: {exc}") from exc
        except httpx.RequestError as exc:
            raise ExaError(f"Exa API request error: {exc}") from exc

        try:
            parsed = response.json()
        except json.JSONDecodeError as exc:
            raise ExaError(
                f"Exa API returned non-JSON payload: {response.text[:500]}"
            ) from exc

        if not isinstance(parsed, dict):
            raise ExaError(f"Exa API returned non-object response: {type(parsed).__name__}")

        return parsed

    async def search(
        self,
        query: str,
        num_results: int = 10,
        include_text: bool = False,
    ) -> SearchResult:
        """Search the web via Exa.

        Parameters
        ----------
        query : str
            Search query string. Must be non-empty.
        num_results : int
            Number of results to request (clamped to 1-20).
        include_text : bool
            If True, include extracted page text in each result.

        Returns
        -------
        SearchResult
            Parsed search results.

        Raises
        ------
        ExaError
            On empty query or API failure.
        """
        query = query.strip()
        if not query:
            raise ExaError("Search query must be non-empty")

        clamped = max(1, min(num_results, 20))
        payload: dict[str, Any] = {
            "query": query,
            "numResults": clamped,
        }
        if include_text:
            payload["contents"] = {"text": {"maxCharacters": min(self.max_text_chars, 4000)}}

        parsed = await self._request("/search", payload)

        items: list[SearchResultItem] = []
        raw_results = parsed.get("results", [])
        if not isinstance(raw_results, list):
            raw_results = []

        for row in raw_results:
            if not isinstance(row, dict):
                continue
            text = None
            if include_text and isinstance(row.get("text"), str):
                text = self._clip(row["text"], 4000)
            items.append(
                SearchResultItem(
                    url=str(row.get("url", "")),
                    title=str(row.get("title", "")),
                    snippet=str(row.get("highlight", "") or row.get("snippet", "")),
                    text=text,
                )
            )

        return SearchResult(query=query, results=items, total=len(items))

    async def fetch_urls(self, urls: list[str]) -> list[PageContent]:
        """Fetch and extract text content from one or more URLs via Exa.

        Parameters
        ----------
        urls : list[str]
            URLs to fetch. Empty/invalid entries are filtered out.
            Maximum 10 URLs per request.

        Returns
        -------
        list[PageContent]
            Extracted page content for each URL.

        Raises
        ------
        ExaError
            If no valid URLs provided or API failure.
        """
        normalized: list[str] = []
        for raw in urls:
            if not isinstance(raw, str):
                continue
            text = raw.strip()
            if text:
                normalized.append(text)
        if not normalized:
            raise ExaError("At least one valid URL is required")

        normalized = normalized[:10]
        payload: dict[str, Any] = {
            "ids": normalized,
            "text": {"maxCharacters": self.max_text_chars},
        }

        parsed = await self._request("/contents", payload)

        pages: list[PageContent] = []
        raw_results = parsed.get("results", [])
        if not isinstance(raw_results, list):
            raw_results = []

        for row in raw_results:
            if not isinstance(row, dict):
                continue
            pages.append(
                PageContent(
                    url=str(row.get("url", "")),
                    title=str(row.get("title", "")),
                    text=self._clip(str(row.get("text", "")), self.max_text_chars),
                )
            )

        return pages

"""Tests for Exa web search client and agent tool wrappers.

All tests use mocked httpx responses — no real Exa API calls are made.
"""

from __future__ import annotations

import json

import httpx
import pytest

from redthread.search.exa import ExaClient, ExaError, PageContent, SearchResult, SearchResultItem
from redthread.agent.tools.search import fetch_url, web_search


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def api_key() -> str:
    return "test-exa-api-key-1234"


@pytest.fixture
def exa_client(api_key: str) -> ExaClient:
    return ExaClient(api_key=api_key)


# ---------------------------------------------------------------------------
# Helpers: mock transport for httpx
# ---------------------------------------------------------------------------

class MockTransport(httpx.AsyncBaseTransport):
    """A reusable httpx transport that returns a pre-configured response."""

    def __init__(
        self,
        status_code: int = 200,
        json_body: dict | None = None,
        text_body: str | None = None,
    ) -> None:
        self.status_code = status_code
        if json_body is not None:
            self._content = json.dumps(json_body).encode("utf-8")
            self._content_type = "application/json"
        elif text_body is not None:
            self._content = text_body.encode("utf-8")
            self._content_type = "text/plain"
        else:
            self._content = b"{}"
            self._content_type = "application/json"

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=self.status_code,
            content=self._content,
            headers={"content-type": self._content_type},
            request=request,
        )


class TimeoutTransport(httpx.AsyncBaseTransport):
    """Transport that simulates a timeout."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Simulated timeout")


def _make_client_with_transport(
    api_key: str,
    transport: httpx.AsyncBaseTransport,
    base_url: str = "https://api.exa.ai",
) -> ExaClient:
    """Create an ExaClient with a mocked httpx.AsyncClient using a custom transport."""
    client = ExaClient(api_key=api_key, base_url=base_url)
    client._client = httpx.AsyncClient(
        base_url=base_url,
        headers={
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "User-Agent": "redthread/0.1.0",
        },
        transport=transport,
    )
    return client


# ---------------------------------------------------------------------------
# ExaClient.__init__ tests
# ---------------------------------------------------------------------------

class TestExaClientInit:
    def test_valid_api_key(self, api_key: str) -> None:
        client = ExaClient(api_key=api_key)
        assert client.api_key == api_key
        assert client.base_url == "https://api.exa.ai"

    def test_custom_base_url(self, api_key: str) -> None:
        client = ExaClient(api_key=api_key, base_url="https://custom.api/")
        assert client.base_url == "https://custom.api"

    def test_empty_api_key_raises(self) -> None:
        with pytest.raises(ExaError, match="EXA_API_KEY must be a non-empty string"):
            ExaClient(api_key="")

    def test_whitespace_api_key_raises(self) -> None:
        with pytest.raises(ExaError, match="EXA_API_KEY must be a non-empty string"):
            ExaClient(api_key="   ")


# ---------------------------------------------------------------------------
# ExaClient.search tests
# ---------------------------------------------------------------------------

class TestExaClientSearch:
    async def test_search_returns_parsed_results(self, api_key: str) -> None:
        mock_response = {
            "results": [
                {
                    "url": "https://example.com/article",
                    "title": "Test Article",
                    "highlight": "This is a snippet about the query.",
                },
                {
                    "url": "https://example.com/news",
                    "title": "News Story",
                    "snippet": "Another result snippet.",
                },
            ]
        }
        client = _make_client_with_transport(api_key, MockTransport(json_body=mock_response))

        result = await client.search("test query")

        assert isinstance(result, SearchResult)
        assert result.query == "test query"
        assert result.total == 2
        assert len(result.results) == 2
        assert result.results[0].url == "https://example.com/article"
        assert result.results[0].title == "Test Article"
        assert result.results[0].snippet == "This is a snippet about the query."
        # Second result uses 'snippet' field (not 'highlight')
        assert result.results[1].snippet == "Another result snippet."

        await client.close()

    async def test_search_with_include_text(self, api_key: str) -> None:
        mock_response = {
            "results": [
                {
                    "url": "https://example.com",
                    "title": "Title",
                    "highlight": "Snippet",
                    "text": "Full page text content here.",
                },
            ]
        }
        client = _make_client_with_transport(api_key, MockTransport(json_body=mock_response))

        result = await client.search("query", include_text=True)

        assert result.results[0].text == "Full page text content here."

        await client.close()

    async def test_search_empty_query_raises(self, api_key: str) -> None:
        client = ExaClient(api_key=api_key)
        with pytest.raises(ExaError, match="Search query must be non-empty"):
            await client.search("")
        await client.close()

    async def test_search_whitespace_query_raises(self, api_key: str) -> None:
        client = ExaClient(api_key=api_key)
        with pytest.raises(ExaError, match="Search query must be non-empty"):
            await client.search("   ")
        await client.close()

    async def test_search_clamps_num_results(self, api_key: str) -> None:
        """num_results is clamped to 1-20 range."""
        mock_response = {"results": []}
        client = _make_client_with_transport(api_key, MockTransport(json_body=mock_response))

        # Should not raise even with extreme values
        result = await client.search("test", num_results=0)
        assert result.total == 0

        result = await client.search("test", num_results=100)
        assert result.total == 0

        await client.close()

    async def test_search_http_error(self, api_key: str) -> None:
        error_body = {"error": "Rate limit exceeded"}
        client = _make_client_with_transport(
            api_key, MockTransport(status_code=429, json_body=error_body)
        )

        with pytest.raises(ExaError, match="Exa API HTTP 429"):
            await client.search("test query")

        await client.close()

    async def test_search_timeout(self, api_key: str) -> None:
        client = _make_client_with_transport(api_key, TimeoutTransport())

        with pytest.raises(ExaError, match="timed out"):
            await client.search("test query")

        await client.close()

    async def test_search_non_json_response(self, api_key: str) -> None:
        client = _make_client_with_transport(
            api_key, MockTransport(text_body="<html>Not JSON</html>")
        )

        with pytest.raises(ExaError, match="non-JSON"):
            await client.search("test query")

        await client.close()

    async def test_search_handles_missing_results_key(self, api_key: str) -> None:
        """If the API response has no 'results' key, return empty results."""
        client = _make_client_with_transport(api_key, MockTransport(json_body={"status": "ok"}))

        result = await client.search("test")
        assert result.total == 0
        assert result.results == []

        await client.close()

    async def test_search_handles_non_dict_rows(self, api_key: str) -> None:
        """Non-dict entries in results list are silently skipped."""
        mock_response = {
            "results": [
                "not a dict",
                42,
                {"url": "https://good.com", "title": "Good", "highlight": "ok"},
            ]
        }
        client = _make_client_with_transport(api_key, MockTransport(json_body=mock_response))

        result = await client.search("test")
        assert result.total == 1
        assert result.results[0].url == "https://good.com"

        await client.close()


# ---------------------------------------------------------------------------
# ExaClient.fetch_urls tests
# ---------------------------------------------------------------------------

class TestExaClientFetchUrls:
    async def test_fetch_returns_page_content(self, api_key: str) -> None:
        mock_response = {
            "results": [
                {
                    "url": "https://example.com/page",
                    "title": "Page Title",
                    "text": "Full extracted text content of the page.",
                },
            ]
        }
        client = _make_client_with_transport(api_key, MockTransport(json_body=mock_response))

        pages = await client.fetch_urls(["https://example.com/page"])

        assert len(pages) == 1
        assert isinstance(pages[0], PageContent)
        assert pages[0].url == "https://example.com/page"
        assert pages[0].title == "Page Title"
        assert pages[0].text == "Full extracted text content of the page."

        await client.close()

    async def test_fetch_multiple_urls(self, api_key: str) -> None:
        mock_response = {
            "results": [
                {"url": "https://a.com", "title": "A", "text": "Text A"},
                {"url": "https://b.com", "title": "B", "text": "Text B"},
            ]
        }
        client = _make_client_with_transport(api_key, MockTransport(json_body=mock_response))

        pages = await client.fetch_urls(["https://a.com", "https://b.com"])

        assert len(pages) == 2
        assert pages[0].url == "https://a.com"
        assert pages[1].url == "https://b.com"

        await client.close()

    async def test_fetch_empty_urls_raises(self, api_key: str) -> None:
        client = ExaClient(api_key=api_key)
        with pytest.raises(ExaError, match="At least one valid URL is required"):
            await client.fetch_urls([])
        await client.close()

    async def test_fetch_filters_invalid_urls(self, api_key: str) -> None:
        client = ExaClient(api_key=api_key)
        with pytest.raises(ExaError, match="At least one valid URL is required"):
            await client.fetch_urls(["", "   ", ""])
        await client.close()

    async def test_fetch_http_error(self, api_key: str) -> None:
        client = _make_client_with_transport(
            api_key, MockTransport(status_code=500, json_body={"error": "Internal server error"})
        )

        with pytest.raises(ExaError, match="Exa API HTTP 500"):
            await client.fetch_urls(["https://example.com"])

        await client.close()

    async def test_fetch_limits_to_10_urls(self, api_key: str) -> None:
        """Only first 10 URLs are sent to the API."""
        mock_response = {"results": []}
        client = _make_client_with_transport(api_key, MockTransport(json_body=mock_response))

        urls = [f"https://example.com/{i}" for i in range(15)]
        pages = await client.fetch_urls(urls)

        assert pages == []
        await client.close()

    async def test_fetch_truncates_long_text(self, api_key: str) -> None:
        long_text = "x" * 20000
        mock_response = {
            "results": [
                {"url": "https://example.com", "title": "T", "text": long_text},
            ]
        }
        client = _make_client_with_transport(api_key, MockTransport(json_body=mock_response))

        pages = await client.fetch_urls(["https://example.com"])

        assert len(pages[0].text) < len(long_text)
        assert "truncated" in pages[0].text

        await client.close()


# ---------------------------------------------------------------------------
# ExaClient._clip tests
# ---------------------------------------------------------------------------

class TestExaClientClip:
    def test_clip_short_text_unchanged(self) -> None:
        assert ExaClient._clip("hello", 100) == "hello"

    def test_clip_long_text_truncated(self) -> None:
        result = ExaClient._clip("a" * 200, 50)
        assert len(result) < 200
        assert result.startswith("a" * 50)
        assert "truncated 150 chars" in result

    def test_clip_exact_length_unchanged(self) -> None:
        text = "x" * 100
        assert ExaClient._clip(text, 100) == text


# ---------------------------------------------------------------------------
# ExaClient.close tests
# ---------------------------------------------------------------------------

class TestExaClientClose:
    async def test_close_without_opening(self, api_key: str) -> None:
        """Closing a client that was never used should not raise."""
        client = ExaClient(api_key=api_key)
        await client.close()

    async def test_close_after_use(self, api_key: str) -> None:
        mock_response = {"results": []}
        client = _make_client_with_transport(api_key, MockTransport(json_body=mock_response))

        await client.search("test")
        await client.close()

        # Client should be None after close
        assert client._client is None


# ---------------------------------------------------------------------------
# Tool wrapper: web_search
# ---------------------------------------------------------------------------

class TestWebSearchTool:
    async def test_search_returns_json(self, api_key: str) -> None:
        mock_response = {
            "results": [
                {
                    "url": "https://example.com",
                    "title": "Example",
                    "highlight": "A snippet",
                },
            ]
        }
        client = _make_client_with_transport(api_key, MockTransport(json_body=mock_response))

        result = await web_search(client, "test query")

        parsed = json.loads(result)
        assert parsed["query"] == "test query"
        assert parsed["total"] == 1
        assert parsed["results"][0]["url"] == "https://example.com"
        assert parsed["results"][0]["title"] == "Example"
        assert parsed["results"][0]["snippet"] == "A snippet"

        await client.close()

    async def test_search_empty_query_returns_error(self, api_key: str) -> None:
        client = ExaClient(api_key=api_key)

        result = await web_search(client, "")

        assert "non-empty query" in result
        await client.close()

    async def test_search_whitespace_query_returns_error(self, api_key: str) -> None:
        client = ExaClient(api_key=api_key)

        result = await web_search(client, "   ")

        assert "non-empty query" in result
        await client.close()

    async def test_search_api_error_returns_message(self, api_key: str) -> None:
        client = _make_client_with_transport(
            api_key, MockTransport(status_code=503, json_body={"error": "service down"})
        )

        result = await web_search(client, "test query")

        assert "Web search failed" in result
        assert "503" in result

        await client.close()

    async def test_search_timeout_returns_message(self, api_key: str) -> None:
        client = _make_client_with_transport(api_key, TimeoutTransport())

        result = await web_search(client, "test query")

        assert "Web search failed" in result
        assert "timed out" in result

        await client.close()

    async def test_search_custom_num_results(self, api_key: str) -> None:
        mock_response = {
            "results": [
                {"url": f"https://example.com/{i}", "title": f"Result {i}", "highlight": f"Snippet {i}"}
                for i in range(5)
            ]
        }
        client = _make_client_with_transport(api_key, MockTransport(json_body=mock_response))

        result = await web_search(client, "test", num_results=5)

        parsed = json.loads(result)
        assert parsed["total"] == 5

        await client.close()


# ---------------------------------------------------------------------------
# Tool wrapper: fetch_url
# ---------------------------------------------------------------------------

class TestFetchUrlTool:
    async def test_fetch_returns_json(self, api_key: str) -> None:
        mock_response = {
            "results": [
                {
                    "url": "https://example.com/page",
                    "title": "Page",
                    "text": "Content of the page.",
                },
            ]
        }
        client = _make_client_with_transport(api_key, MockTransport(json_body=mock_response))

        result = await fetch_url(client, "https://example.com/page")

        parsed = json.loads(result)
        assert parsed["url"] == "https://example.com/page"
        assert parsed["title"] == "Page"
        assert parsed["text"] == "Content of the page."

        await client.close()

    async def test_fetch_empty_url_returns_error(self, api_key: str) -> None:
        client = ExaClient(api_key=api_key)

        result = await fetch_url(client, "")

        assert "non-empty URL" in result
        await client.close()

    async def test_fetch_none_url_returns_error(self, api_key: str) -> None:
        client = ExaClient(api_key=api_key)

        result = await fetch_url(client, None)  # type: ignore[arg-type]

        assert "non-empty URL" in result
        await client.close()

    async def test_fetch_api_error_returns_message(self, api_key: str) -> None:
        client = _make_client_with_transport(
            api_key, MockTransport(status_code=404, json_body={"error": "not found"})
        )

        result = await fetch_url(client, "https://example.com/missing")

        assert "Fetch URL failed" in result
        assert "404" in result

        await client.close()

    async def test_fetch_empty_result_returns_empty_content(self, api_key: str) -> None:
        """If the API returns no results for the URL, return empty content."""
        mock_response = {"results": []}
        client = _make_client_with_transport(api_key, MockTransport(json_body=mock_response))

        result = await fetch_url(client, "https://example.com")

        parsed = json.loads(result)
        assert parsed["url"] == "https://example.com"
        assert parsed["text"] == ""

        await client.close()

    async def test_fetch_strips_whitespace_from_url(self, api_key: str) -> None:
        mock_response = {
            "results": [
                {
                    "url": "https://example.com",
                    "title": "T",
                    "text": "Text",
                },
            ]
        }
        client = _make_client_with_transport(api_key, MockTransport(json_body=mock_response))

        result = await fetch_url(client, "  https://example.com  ")

        parsed = json.loads(result)
        assert parsed["url"] == "https://example.com"

        await client.close()

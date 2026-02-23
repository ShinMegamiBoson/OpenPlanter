"""Web search agent tools wrapping the Exa API client.

These are plain async functions (NOT decorated with @tool yet).
The SDK adapter will wrap them with the decorator in section 8.
Tools take exa_client as a parameter for dependency injection.
"""

from __future__ import annotations

import json

from redthread.search.exa import ExaClient, ExaError


async def web_search(
    exa_client: ExaClient,
    query: str,
    num_results: int = 10,
) -> str:
    """Search the web for information about entities, public records, news, or
    supplementary data. Returns titles, URLs, and snippets.

    Parameters
    ----------
    exa_client : ExaClient
        Injected Exa API client instance.
    query : str
        Search query string.
    num_results : int
        Number of results to return (1-20, default 10).

    Returns
    -------
    str
        JSON string with search results, or an error message.
    """
    query = query.strip()
    if not query:
        return "web_search requires a non-empty query"

    try:
        result = await exa_client.search(query=query, num_results=num_results)
    except ExaError as exc:
        return f"Web search failed: {exc}"

    output = {
        "query": result.query,
        "results": [
            {
                "url": item.url,
                "title": item.title,
                "snippet": item.snippet,
            }
            for item in result.results
        ],
        "total": result.total,
    }
    return json.dumps(output, indent=2, ensure_ascii=True)


async def fetch_url(
    exa_client: ExaClient,
    url: str,
) -> str:
    """Fetch and extract text content from a specific URL. Useful for reading
    public records, news articles, or corporate filings found via web_search.

    Parameters
    ----------
    exa_client : ExaClient
        Injected Exa API client instance.
    url : str
        URL to fetch content from.

    Returns
    -------
    str
        JSON string with page content, or an error message.
    """
    if not isinstance(url, str) or not url.strip():
        return "fetch_url requires a non-empty URL string"

    try:
        pages = await exa_client.fetch_urls([url.strip()])
    except ExaError as exc:
        return f"Fetch URL failed: {exc}"

    if not pages:
        return json.dumps({"url": url.strip(), "title": "", "text": ""}, indent=2)

    page = pages[0]
    output = {
        "url": page.url,
        "title": page.title,
        "text": page.text,
    }
    return json.dumps(output, indent=2, ensure_ascii=True)

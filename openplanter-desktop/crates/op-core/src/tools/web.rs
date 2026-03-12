use std::sync::LazyLock;
/// Web tools: Exa / Firecrawl / Brave / Tavily search and fetch_url.
use std::time::Duration;

use regex::Regex;
use serde_json::json;

use crate::config::normalize_web_search_provider;

use super::ToolResult;

static SCRIPT_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?is)<script[^>]*>.*?</script>").unwrap());
static STYLE_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?is)<style[^>]*>.*?</style>").unwrap());
static TITLE_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?is)<title[^>]*>(.*?)</title>").unwrap());
static BLOCK_TAG_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?is)</?(article|br|div|footer|h[1-6]|header|li|main|p|section|td|th|tr)[^>]*>")
        .unwrap()
});
static TAG_RE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?is)<[^>]+>").unwrap());

fn clip(text: &str, max_chars: usize) -> String {
    if text.len() <= max_chars {
        return text.to_string();
    }
    let end = text.floor_char_boundary(max_chars);
    let omitted = text.len() - end;
    format!("{}\n\n...[truncated {omitted} chars]...", &text[..end])
}

fn collapse_ws(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn decode_html_entities(text: &str) -> String {
    text.replace("&nbsp;", " ")
        .replace("&quot;", "\"")
        .replace("&#39;", "'")
        .replace("&#x27;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
}

fn extract_html_text(html: &str) -> (String, String) {
    let title = TITLE_RE
        .captures(html)
        .and_then(|caps| caps.get(1))
        .map(|m| collapse_ws(&decode_html_entities(m.as_str())))
        .unwrap_or_default();
    let without_scripts = SCRIPT_RE.replace_all(html, " ");
    let without_styles = STYLE_RE.replace_all(&without_scripts, " ");
    let with_breaks = BLOCK_TAG_RE.replace_all(&without_styles, "\n");
    let plain = TAG_RE.replace_all(&with_breaks, " ");
    let text = collapse_ws(&decode_html_entities(&plain));
    (title, text)
}

async fn exa_request(
    api_key: Option<&str>,
    exa_base_url: &str,
    endpoint: &str,
    payload: &serde_json::Value,
    timeout_sec: u64,
) -> Result<serde_json::Value, String> {
    let api_key = match api_key {
        Some(value) if !value.trim().is_empty() => value,
        _ => return Err("EXA_API_KEY not configured".into()),
    };

    let url = format!("{}{}", exa_base_url.trim_end_matches('/'), endpoint);
    let client = reqwest::Client::new();
    let response = client
        .post(&url)
        .header("x-api-key", api_key)
        .header("Content-Type", "application/json")
        .header("User-Agent", "exa-py 1.0.18")
        .timeout(Duration::from_secs(timeout_sec))
        .json(payload)
        .send()
        .await
        .map_err(|e| format!("Exa API request failed: {e}"))?;

    let response = response
        .error_for_status()
        .map_err(|e| format!("Exa API request failed: {e}"))?;

    response
        .json::<serde_json::Value>()
        .await
        .map_err(|e| format!("Exa API returned non-JSON payload: {e}"))
}

async fn firecrawl_request(
    api_key: Option<&str>,
    firecrawl_base_url: &str,
    endpoint: &str,
    payload: &serde_json::Value,
    timeout_sec: u64,
) -> Result<serde_json::Value, String> {
    let api_key = match api_key {
        Some(value) if !value.trim().is_empty() => value,
        _ => return Err("FIRECRAWL_API_KEY not configured".into()),
    };

    let url = format!("{}{}", firecrawl_base_url.trim_end_matches('/'), endpoint);
    let client = reqwest::Client::new();
    let response = client
        .post(&url)
        .header("Authorization", format!("Bearer {api_key}"))
        .header("Content-Type", "application/json")
        .timeout(Duration::from_secs(timeout_sec))
        .json(payload)
        .send()
        .await
        .map_err(|e| format!("Firecrawl API request failed: {e}"))?;

    let response = response
        .error_for_status()
        .map_err(|e| format!("Firecrawl API request failed: {e}"))?;

    response
        .json::<serde_json::Value>()
        .await
        .map_err(|e| format!("Firecrawl API returned non-JSON payload: {e}"))
}

async fn brave_request(
    api_key: Option<&str>,
    brave_base_url: &str,
    endpoint: &str,
    params: &[(&str, String)],
    timeout_sec: u64,
) -> Result<serde_json::Value, String> {
    let api_key = match api_key {
        Some(value) if !value.trim().is_empty() => value,
        _ => return Err("BRAVE_API_KEY not configured".into()),
    };

    let url = format!("{}{}", brave_base_url.trim_end_matches('/'), endpoint);
    let client = reqwest::Client::new();
    let response = client
        .get(&url)
        .header("Accept", "application/json")
        .header("X-Subscription-Token", api_key)
        .query(params)
        .timeout(Duration::from_secs(timeout_sec))
        .send()
        .await
        .map_err(|e| format!("Brave API request failed: {e}"))?;

    let response = response
        .error_for_status()
        .map_err(|e| format!("Brave API request failed: {e}"))?;

    response
        .json::<serde_json::Value>()
        .await
        .map_err(|e| format!("Brave API returned non-JSON payload: {e}"))
}

async fn tavily_request(
    api_key: Option<&str>,
    tavily_base_url: &str,
    endpoint: &str,
    payload: &serde_json::Value,
    timeout_sec: u64,
) -> Result<serde_json::Value, String> {
    let api_key = match api_key {
        Some(value) if !value.trim().is_empty() => value,
        _ => return Err("TAVILY_API_KEY not configured".into()),
    };

    let url = format!("{}{}", tavily_base_url.trim_end_matches('/'), endpoint);
    let client = reqwest::Client::new();
    let response = client
        .post(&url)
        .header("Authorization", format!("Bearer {api_key}"))
        .header("Content-Type", "application/json")
        .timeout(Duration::from_secs(timeout_sec))
        .json(payload)
        .send()
        .await
        .map_err(|e| format!("Tavily API request failed: {e}"))?;

    let response = response
        .error_for_status()
        .map_err(|e| format!("Tavily API request failed: {e}"))?;

    response
        .json::<serde_json::Value>()
        .await
        .map_err(|e| format!("Tavily API returned non-JSON payload: {e}"))
}

async fn fetch_direct_page(url: &str, timeout_sec: u64) -> serde_json::Value {
    let client = reqwest::Client::new();
    let response = match client
        .get(url)
        .header(
            "Accept",
            "text/html,application/xhtml+xml,application/json,text/plain;q=0.9,*/*;q=0.8",
        )
        .header("User-Agent", "OpenPlanter/1.0")
        .timeout(Duration::from_secs(timeout_sec))
        .send()
        .await
    {
        Ok(response) => response,
        Err(error) => {
            return json!({
                "url": url,
                "title": "",
                "text": format!("Direct fetch failed: {error}"),
            });
        }
    };

    let final_url = response.url().to_string();
    let content_type = response
        .headers()
        .get(reqwest::header::CONTENT_TYPE)
        .and_then(|value| value.to_str().ok())
        .unwrap_or("")
        .to_lowercase();

    let response = match response.error_for_status() {
        Ok(response) => response,
        Err(error) => {
            return json!({
                "url": url,
                "title": "",
                "text": format!("Direct fetch failed: {error}"),
            });
        }
    };

    let body = match response.text().await {
        Ok(body) => body,
        Err(error) => {
            return json!({
                "url": final_url,
                "title": "",
                "text": format!("Direct fetch failed: {error}"),
            });
        }
    };

    let (title, extracted_text) = if content_type.contains("html") {
        extract_html_text(&body)
    } else {
        (String::new(), body.clone())
    };
    let text = if extracted_text.is_empty() {
        body
    } else {
        extracted_text
    };

    json!({
        "url": final_url,
        "title": title,
        "text": clip(&text, 8_000),
    })
}

pub async fn web_search(
    provider: &str,
    exa_api_key: Option<&str>,
    exa_base_url: &str,
    firecrawl_api_key: Option<&str>,
    firecrawl_base_url: &str,
    brave_api_key: Option<&str>,
    brave_base_url: &str,
    tavily_api_key: Option<&str>,
    tavily_base_url: &str,
    query: &str,
    num_results: i64,
    include_text: bool,
    max_file_chars: usize,
    timeout_sec: u64,
) -> ToolResult {
    let query = query.trim();
    if query.is_empty() {
        return ToolResult::error("web_search requires non-empty query".into());
    }

    let provider = normalize_web_search_provider(Some(provider));
    let clamped = num_results.clamp(1, 20);

    let output = if provider == "firecrawl" {
        let mut payload = json!({
            "query": query,
            "limit": clamped,
        });
        if include_text {
            payload["scrapeOptions"] = json!({ "formats": ["markdown"] });
        }

        match firecrawl_request(
            firecrawl_api_key,
            firecrawl_base_url,
            "/search",
            &payload,
            timeout_sec,
        )
        .await
        {
            Ok(body) => {
                let mut rows: Vec<serde_json::Value> = Vec::new();
                if let Some(items) = body.get("data").and_then(|value| value.as_array()) {
                    rows.extend(items.iter().cloned());
                } else if let Some(items) = body
                    .get("data")
                    .and_then(|value| value.get("web"))
                    .and_then(|value| value.as_array())
                {
                    rows.extend(items.iter().cloned());
                }

                let mut results: Vec<serde_json::Value> = Vec::new();
                for row in rows {
                    let metadata = row.get("metadata").and_then(|value| value.as_object());
                    let title = row
                        .get("title")
                        .and_then(|value| value.as_str())
                        .filter(|value| !value.is_empty())
                        .or_else(|| {
                            metadata
                                .and_then(|meta| meta.get("title"))
                                .and_then(|value| value.as_str())
                        })
                        .unwrap_or("");

                    let mut item = json!({
                        "url": row.get("url").and_then(|value| value.as_str()).unwrap_or(""),
                        "title": title,
                        "snippet": row
                            .get("description")
                            .and_then(|value| value.as_str())
                            .or_else(|| row.get("snippet").and_then(|value| value.as_str()))
                            .unwrap_or(""),
                    });

                    if include_text {
                        if let Some(text) = row
                            .get("markdown")
                            .and_then(|value| value.as_str())
                            .or_else(|| row.get("text").and_then(|value| value.as_str()))
                        {
                            if !text.is_empty() {
                                item["text"] = json!(clip(text, 4_000));
                            }
                        }
                    }

                    results.push(item);
                }

                json!({
                    "query": query,
                    "provider": provider,
                    "results": results,
                    "total": results.len(),
                })
            }
            Err(error) => return ToolResult::error(format!("Web search failed: {error}")),
        }
    } else if provider == "brave" {
        let mut params = vec![("q", query.to_string()), ("count", clamped.to_string())];
        if include_text {
            params.push(("extra_snippets", "true".to_string()));
        }

        match brave_request(
            brave_api_key,
            brave_base_url,
            "/web/search",
            &params,
            timeout_sec,
        )
        .await
        {
            Ok(body) => {
                let rows = body
                    .get("web")
                    .and_then(|value| value.get("results"))
                    .and_then(|value| value.as_array())
                    .or_else(|| body.get("results").and_then(|value| value.as_array()));
                let mut results: Vec<serde_json::Value> = Vec::new();
                if let Some(rows) = rows {
                    for row in rows {
                        let description = row
                            .get("description")
                            .and_then(|value| value.as_str())
                            .or_else(|| row.get("snippet").and_then(|value| value.as_str()))
                            .unwrap_or("")
                            .to_string();
                        let extra_texts = row
                            .get("extra_snippets")
                            .and_then(|value| value.as_array())
                            .map(|items| {
                                items
                                    .iter()
                                    .filter_map(|value| value.as_str())
                                    .filter(|value| !value.is_empty())
                                    .map(str::to_string)
                                    .collect::<Vec<_>>()
                            })
                            .unwrap_or_default();
                        let snippet = if !description.is_empty() {
                            description.clone()
                        } else {
                            extra_texts.first().cloned().unwrap_or_default()
                        };

                        let mut item = json!({
                            "url": row.get("url").and_then(|value| value.as_str()).unwrap_or(""),
                            "title": row.get("title").and_then(|value| value.as_str()).unwrap_or(""),
                            "snippet": snippet,
                        });
                        if include_text {
                            let mut text_parts = Vec::new();
                            if !description.is_empty() {
                                text_parts.push(description.clone());
                            }
                            text_parts.extend(extra_texts.clone());
                            if !text_parts.is_empty() {
                                item["text"] = json!(clip(&text_parts.join("\n\n"), 4_000));
                            }
                        }
                        results.push(item);
                    }
                }

                json!({
                    "query": query,
                    "provider": provider,
                    "results": results,
                    "total": results.len(),
                })
            }
            Err(error) => return ToolResult::error(format!("Web search failed: {error}")),
        }
    } else if provider == "tavily" {
        let mut payload = json!({
            "query": query,
            "max_results": clamped,
        });
        if include_text {
            payload["include_raw_content"] = json!("markdown");
        }

        match tavily_request(
            tavily_api_key,
            tavily_base_url,
            "/search",
            &payload,
            timeout_sec,
        )
        .await
        {
            Ok(body) => {
                let mut results: Vec<serde_json::Value> = Vec::new();
                if let Some(rows) = body.get("results").and_then(|value| value.as_array()) {
                    for row in rows {
                        let snippet = row
                            .get("content")
                            .and_then(|value| value.as_str())
                            .or_else(|| row.get("snippet").and_then(|value| value.as_str()))
                            .unwrap_or("");
                        let mut item = json!({
                            "url": row.get("url").and_then(|value| value.as_str()).unwrap_or(""),
                            "title": row.get("title").and_then(|value| value.as_str()).unwrap_or(""),
                            "snippet": snippet,
                        });
                        if include_text {
                            if let Some(text) = row
                                .get("raw_content")
                                .and_then(|value| value.as_str())
                                .or_else(|| row.get("content").and_then(|value| value.as_str()))
                            {
                                if !text.is_empty() {
                                    item["text"] = json!(clip(text, 4_000));
                                }
                            }
                        }
                        results.push(item);
                    }
                }

                json!({
                    "query": query,
                    "provider": provider,
                    "results": results,
                    "total": results.len(),
                })
            }
            Err(error) => return ToolResult::error(format!("Web search failed: {error}")),
        }
    } else {
        let mut payload = json!({
            "query": query,
            "numResults": clamped,
        });
        if include_text {
            payload["contents"] = json!({ "text": { "maxCharacters": 4_000 } });
        }

        match exa_request(exa_api_key, exa_base_url, "/search", &payload, timeout_sec).await {
            Ok(body) => {
                let mut results: Vec<serde_json::Value> = Vec::new();
                if let Some(rows) = body.get("results").and_then(|value| value.as_array()) {
                    for row in rows {
                        let mut item = json!({
                            "url": row.get("url").and_then(|value| value.as_str()).unwrap_or(""),
                            "title": row.get("title").and_then(|value| value.as_str()).unwrap_or(""),
                            "snippet": row
                                .get("highlight")
                                .and_then(|value| value.as_str())
                                .or_else(|| row.get("snippet").and_then(|value| value.as_str()))
                                .unwrap_or(""),
                        });
                        if include_text {
                            if let Some(text) = row.get("text").and_then(|value| value.as_str()) {
                                if !text.is_empty() {
                                    item["text"] = json!(clip(text, 4_000));
                                }
                            }
                        }
                        results.push(item);
                    }
                }

                json!({
                    "query": query,
                    "provider": provider,
                    "results": results,
                    "total": results.len(),
                })
            }
            Err(error) => return ToolResult::error(format!("Web search failed: {error}")),
        }
    };

    ToolResult::ok(clip(
        &serde_json::to_string_pretty(&output).unwrap_or_default(),
        max_file_chars,
    ))
}

pub async fn fetch_url(
    provider: &str,
    exa_api_key: Option<&str>,
    exa_base_url: &str,
    firecrawl_api_key: Option<&str>,
    firecrawl_base_url: &str,
    brave_api_key: Option<&str>,
    brave_base_url: &str,
    tavily_api_key: Option<&str>,
    tavily_base_url: &str,
    urls: &[String],
    max_file_chars: usize,
    timeout_sec: u64,
) -> ToolResult {
    let normalized: Vec<String> = urls
        .iter()
        .map(|value| value.trim())
        .filter(|value| !value.is_empty())
        .take(10)
        .map(String::from)
        .collect();

    if normalized.is_empty() {
        return ToolResult::error("fetch_url requires at least one valid URL".into());
    }

    let provider = normalize_web_search_provider(Some(provider));

    let output = if provider == "firecrawl" {
        let mut pages: Vec<serde_json::Value> = Vec::new();
        for url in &normalized {
            let payload = json!({
                "url": url,
                "formats": ["markdown"],
            });
            let body = match firecrawl_request(
                firecrawl_api_key,
                firecrawl_base_url,
                "/scrape",
                &payload,
                timeout_sec,
            )
            .await
            {
                Ok(body) => body,
                Err(error) => return ToolResult::error(format!("Fetch URL failed: {error}")),
            };

            if let Some(data) = body.get("data").and_then(|value| value.as_object()) {
                let title = data
                    .get("metadata")
                    .and_then(|value| value.as_object())
                    .and_then(|meta| meta.get("title"))
                    .and_then(|value| value.as_str())
                    .unwrap_or("");
                let text = data
                    .get("markdown")
                    .and_then(|value| value.as_str())
                    .or_else(|| data.get("text").and_then(|value| value.as_str()))
                    .or_else(|| data.get("html").and_then(|value| value.as_str()))
                    .unwrap_or("");

                pages.push(json!({
                    "url": data.get("url").and_then(|value| value.as_str()).unwrap_or(url),
                    "title": title,
                    "text": clip(text, 8_000),
                }));
            }
        }

        json!({
            "provider": provider,
            "pages": pages,
            "total": pages.len(),
        })
    } else if provider == "brave" {
        let _ = brave_api_key;
        let _ = brave_base_url;
        let mut pages: Vec<serde_json::Value> = Vec::new();
        for url in &normalized {
            pages.push(fetch_direct_page(url, timeout_sec).await);
        }

        json!({
            "provider": provider,
            "pages": pages,
            "total": pages.len(),
        })
    } else if provider == "tavily" {
        let payload = json!({
            "urls": normalized,
            "extract_depth": "basic",
            "include_images": false,
        });

        match tavily_request(
            tavily_api_key,
            tavily_base_url,
            "/extract",
            &payload,
            timeout_sec,
        )
        .await
        {
            Ok(body) => {
                let mut pages: Vec<serde_json::Value> = Vec::new();
                if let Some(rows) = body.get("results").and_then(|value| value.as_array()) {
                    for row in rows {
                        pages.push(json!({
                            "url": row.get("url").and_then(|value| value.as_str()).unwrap_or(""),
                            "title": row.get("title").and_then(|value| value.as_str()).unwrap_or(""),
                            "text": clip(
                                row.get("raw_content")
                                    .and_then(|value| value.as_str())
                                    .or_else(|| row.get("content").and_then(|value| value.as_str()))
                                    .unwrap_or(""),
                                8_000,
                            ),
                        }));
                    }
                }

                json!({
                    "provider": provider,
                    "pages": pages,
                    "total": pages.len(),
                })
            }
            Err(error) => return ToolResult::error(format!("Fetch URL failed: {error}")),
        }
    } else {
        let payload = json!({
            "ids": normalized,
            "text": { "maxCharacters": 8_000 },
        });

        match exa_request(
            exa_api_key,
            exa_base_url,
            "/contents",
            &payload,
            timeout_sec,
        )
        .await
        {
            Ok(body) => {
                let mut pages: Vec<serde_json::Value> = Vec::new();
                if let Some(rows) = body.get("results").and_then(|value| value.as_array()) {
                    for row in rows {
                        pages.push(json!({
                            "url": row.get("url").and_then(|value| value.as_str()).unwrap_or(""),
                            "title": row.get("title").and_then(|value| value.as_str()).unwrap_or(""),
                            "text": clip(
                                row.get("text").and_then(|value| value.as_str()).unwrap_or(""),
                                8_000,
                            ),
                        }));
                    }
                }

                json!({
                    "provider": provider,
                    "pages": pages,
                    "total": pages.len(),
                })
            }
            Err(error) => return ToolResult::error(format!("Fetch URL failed: {error}")),
        }
    };

    ToolResult::ok(clip(
        &serde_json::to_string_pretty(&output).unwrap_or_default(),
        max_file_chars,
    ))
}

#[cfg(test)]
mod tests {
    use axum::body::Body;
    use axum::http::StatusCode;
    use axum::response::Response;
    use axum::routing::{get, post};
    use axum::{Json, Router};
    use serde_json::{Value, json};

    use super::*;

    async fn start_json_server(
        path: &'static str,
        response_payload: Value,
    ) -> std::net::SocketAddr {
        let app = Router::new().route(
            path,
            post(move || {
                let response_payload = response_payload.clone();
                async move { Json(response_payload) }
            }),
        );
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });
        addr
    }

    async fn start_json_get_server(
        path: &'static str,
        response_payload: Value,
    ) -> std::net::SocketAddr {
        let app = Router::new().route(
            path,
            get(move || {
                let response_payload = response_payload.clone();
                async move { Json(response_payload) }
            }),
        );
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });
        addr
    }

    async fn start_text_get_server(
        path: &'static str,
        body: &'static str,
        content_type: &'static str,
    ) -> std::net::SocketAddr {
        let app = Router::new().route(
            path,
            get(move || async move {
                Response::builder()
                    .status(StatusCode::OK)
                    .header("Content-Type", content_type)
                    .body(Body::from(body))
                    .unwrap()
            }),
        );
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });
        addr
    }

    async fn start_status_server(path: &'static str, status: StatusCode) -> std::net::SocketAddr {
        let app = Router::new().route(
            path,
            post(move || async move {
                Response::builder()
                    .status(status)
                    .body(Body::from("{\"error\":\"boom\"}"))
                    .unwrap()
            }),
        );
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });
        addr
    }

    #[tokio::test]
    async fn test_web_search_exa_output_shape() {
        let addr = start_json_server(
            "/search",
            json!({
                "results": [
                    {
                        "url": "https://example.com",
                        "title": "Example",
                        "highlight": "Snippet",
                        "text": "Long page body"
                    }
                ]
            }),
        )
        .await;

        let result = web_search(
            "exa",
            Some("exa-key"),
            &format!("http://{addr}"),
            None,
            "https://api.firecrawl.dev/v1",
            None,
            "https://api.search.brave.com/res/v1",
            None,
            "https://api.tavily.com",
            "example query",
            5,
            true,
            20_000,
            5,
        )
        .await;

        assert!(!result.is_error);
        let parsed: Value = serde_json::from_str(&result.content).unwrap();
        assert_eq!(parsed["provider"], "exa");
        assert_eq!(parsed["query"], "example query");
        assert_eq!(parsed["results"][0]["url"], "https://example.com");
        assert_eq!(parsed["results"][0]["text"], "Long page body");
    }

    #[tokio::test]
    async fn test_web_search_firecrawl_output_shape() {
        let addr = start_json_server(
            "/search",
            json!({
                "data": [
                    {
                        "url": "https://example.com/firecrawl",
                        "description": "Firecrawl snippet",
                        "markdown": "# Hello",
                        "metadata": { "title": "Firecrawl Title" }
                    }
                ]
            }),
        )
        .await;

        let result = web_search(
            "firecrawl",
            None,
            "https://api.exa.ai",
            Some("fc-key"),
            &format!("http://{addr}"),
            None,
            "https://api.search.brave.com/res/v1",
            None,
            "https://api.tavily.com",
            "example query",
            5,
            true,
            20_000,
            5,
        )
        .await;

        assert!(!result.is_error);
        let parsed: Value = serde_json::from_str(&result.content).unwrap();
        assert_eq!(parsed["provider"], "firecrawl");
        assert_eq!(parsed["results"][0]["title"], "Firecrawl Title");
        assert_eq!(parsed["results"][0]["text"], "# Hello");
    }

    #[tokio::test]
    async fn test_fetch_url_firecrawl_output_shape() {
        let addr = start_json_server(
            "/scrape",
            json!({
                "data": {
                    "url": "https://example.com/article",
                    "markdown": "Article body",
                    "metadata": { "title": "Article Title" }
                }
            }),
        )
        .await;

        let result = fetch_url(
            "firecrawl",
            None,
            "https://api.exa.ai",
            Some("fc-key"),
            &format!("http://{addr}"),
            None,
            "https://api.search.brave.com/res/v1",
            None,
            "https://api.tavily.com",
            &[String::from("https://example.com/article")],
            20_000,
            5,
        )
        .await;

        assert!(!result.is_error);
        let parsed: Value = serde_json::from_str(&result.content).unwrap();
        assert_eq!(parsed["provider"], "firecrawl");
        assert_eq!(parsed["pages"][0]["title"], "Article Title");
        assert_eq!(parsed["pages"][0]["text"], "Article body");
    }

    #[tokio::test]
    async fn test_web_search_brave_output_shape() {
        let addr = start_json_get_server(
            "/web/search",
            json!({
                "web": {
                    "results": [
                        {
                            "url": "https://example.com/brave",
                            "title": "Brave Title",
                            "description": "Brave snippet",
                            "extra_snippets": ["Extra context"]
                        }
                    ]
                }
            }),
        )
        .await;

        let result = web_search(
            "brave",
            None,
            "https://api.exa.ai",
            None,
            "https://api.firecrawl.dev/v1",
            Some("brave-key"),
            &format!("http://{addr}"),
            None,
            "https://api.tavily.com",
            "example query",
            5,
            true,
            20_000,
            5,
        )
        .await;

        assert!(!result.is_error);
        let parsed: Value = serde_json::from_str(&result.content).unwrap();
        assert_eq!(parsed["provider"], "brave");
        assert_eq!(parsed["results"][0]["title"], "Brave Title");
        assert!(
            parsed["results"][0]["text"]
                .as_str()
                .unwrap()
                .contains("Extra context")
        );
    }

    #[tokio::test]
    async fn test_fetch_url_brave_output_shape() {
        let addr = start_text_get_server(
            "/page",
            "<html><head><title>Brave Page</title></head><body><h1>Hello Brave</h1><p>Readable text.</p></body></html>",
            "text/html; charset=utf-8",
        )
        .await;

        let result = fetch_url(
            "brave",
            None,
            "https://api.exa.ai",
            None,
            "https://api.firecrawl.dev/v1",
            None,
            "https://api.search.brave.com/res/v1",
            None,
            "https://api.tavily.com",
            &[format!("http://{addr}/page")],
            20_000,
            5,
        )
        .await;

        assert!(!result.is_error);
        let parsed: Value = serde_json::from_str(&result.content).unwrap();
        assert_eq!(parsed["provider"], "brave");
        assert_eq!(parsed["pages"][0]["title"], "Brave Page");
        assert!(
            parsed["pages"][0]["text"]
                .as_str()
                .unwrap()
                .contains("Hello Brave")
        );
    }

    #[tokio::test]
    async fn test_missing_firecrawl_key_errors() {
        let result = web_search(
            "firecrawl",
            None,
            "https://api.exa.ai",
            None,
            "https://api.firecrawl.dev/v1",
            None,
            "https://api.search.brave.com/res/v1",
            None,
            "https://api.tavily.com",
            "example query",
            5,
            false,
            20_000,
            5,
        )
        .await;

        assert!(result.is_error);
        assert!(result.content.contains("FIRECRAWL_API_KEY"));
    }

    #[tokio::test]
    async fn test_missing_brave_key_errors() {
        let result = web_search(
            "brave",
            None,
            "https://api.exa.ai",
            None,
            "https://api.firecrawl.dev/v1",
            None,
            "https://api.search.brave.com/res/v1",
            None,
            "https://api.tavily.com",
            "example query",
            5,
            false,
            20_000,
            5,
        )
        .await;

        assert!(result.is_error);
        assert!(result.content.contains("BRAVE_API_KEY"));
    }

    #[tokio::test]
    async fn test_web_search_tavily_output_shape() {
        let addr = start_json_server(
            "/search",
            json!({
                "results": [
                    {
                        "url": "https://example.com/tavily",
                        "title": "Tavily Title",
                        "content": "Tavily snippet",
                        "raw_content": "Tavily raw content"
                    }
                ]
            }),
        )
        .await;

        let result = web_search(
            "tavily",
            None,
            "https://api.exa.ai",
            None,
            "https://api.firecrawl.dev/v1",
            None,
            "https://api.search.brave.com/res/v1",
            Some("tavily-key"),
            &format!("http://{addr}"),
            "example query",
            5,
            true,
            20_000,
            5,
        )
        .await;

        assert!(!result.is_error);
        let parsed: Value = serde_json::from_str(&result.content).unwrap();
        assert_eq!(parsed["provider"], "tavily");
        assert_eq!(parsed["results"][0]["title"], "Tavily Title");
        assert_eq!(parsed["results"][0]["snippet"], "Tavily snippet");
        assert_eq!(parsed["results"][0]["text"], "Tavily raw content");
    }

    #[tokio::test]
    async fn test_fetch_url_tavily_output_shape() {
        let addr = start_json_server(
            "/extract",
            json!({
                "results": [
                    {
                        "url": "https://example.com/article",
                        "title": "Tavily Article",
                        "raw_content": "Article body"
                    }
                ]
            }),
        )
        .await;

        let result = fetch_url(
            "tavily",
            None,
            "https://api.exa.ai",
            None,
            "https://api.firecrawl.dev/v1",
            None,
            "https://api.search.brave.com/res/v1",
            Some("tavily-key"),
            &format!("http://{addr}"),
            &[String::from("https://example.com/article")],
            20_000,
            5,
        )
        .await;

        assert!(!result.is_error);
        let parsed: Value = serde_json::from_str(&result.content).unwrap();
        assert_eq!(parsed["provider"], "tavily");
        assert_eq!(parsed["pages"][0]["title"], "Tavily Article");
        assert_eq!(parsed["pages"][0]["text"], "Article body");
    }

    #[tokio::test]
    async fn test_missing_tavily_key_errors() {
        let result = web_search(
            "tavily",
            None,
            "https://api.exa.ai",
            None,
            "https://api.firecrawl.dev/v1",
            None,
            "https://api.search.brave.com/res/v1",
            None,
            "https://api.tavily.com",
            "example query",
            5,
            false,
            20_000,
            5,
        )
        .await;

        assert!(result.is_error);
        assert!(result.content.contains("TAVILY_API_KEY"));
    }

    #[tokio::test]
    async fn test_exa_http_error_bubbles_up() {
        let addr = start_status_server("/search", StatusCode::BAD_GATEWAY).await;

        let result = web_search(
            "exa",
            Some("exa-key"),
            &format!("http://{addr}"),
            None,
            "https://api.firecrawl.dev/v1",
            None,
            "https://api.search.brave.com/res/v1",
            None,
            "https://api.tavily.com",
            "example query",
            5,
            false,
            20_000,
            5,
        )
        .await;

        assert!(result.is_error);
        assert!(result.content.contains("Web search failed"));
    }
}

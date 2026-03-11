/// Web tools: Exa / Firecrawl search and fetch_url.
use std::time::Duration;

use serde_json::json;

use crate::config::normalize_web_search_provider;

use super::ToolResult;

fn clip(text: &str, max_chars: usize) -> String {
    if text.len() <= max_chars {
        return text.to_string();
    }
    let end = text.floor_char_boundary(max_chars);
    let omitted = text.len() - end;
    format!("{}\n\n...[truncated {omitted} chars]...", &text[..end])
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

pub async fn web_search(
    provider: &str,
    exa_api_key: Option<&str>,
    exa_base_url: &str,
    firecrawl_api_key: Option<&str>,
    firecrawl_base_url: &str,
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
    use axum::routing::post;
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
    async fn test_missing_firecrawl_key_errors() {
        let result = web_search(
            "firecrawl",
            None,
            "https://api.exa.ai",
            None,
            "https://api.firecrawl.dev/v1",
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
    async fn test_exa_http_error_bubbles_up() {
        let addr = start_status_server("/search", StatusCode::BAD_GATEWAY).await;

        let result = web_search(
            "exa",
            Some("exa-key"),
            &format!("http://{addr}"),
            None,
            "https://api.firecrawl.dev/v1",
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

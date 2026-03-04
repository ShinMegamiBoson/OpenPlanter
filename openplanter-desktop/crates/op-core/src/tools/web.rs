/// Web tools: Exa search, fetch_url.

use serde_json::json;

use super::ToolResult;

fn clip(text: &str, max_chars: usize) -> String {
    if text.len() <= max_chars {
        return text.to_string();
    }
    let end = text.floor_char_boundary(max_chars);
    let omitted = text.len() - end;
    format!(
        "{}\n\n...[truncated {omitted} chars]...",
        &text[..end]
    )
}

pub async fn web_search(
    exa_api_key: Option<&str>,
    exa_base_url: &str,
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

    let api_key = match exa_api_key {
        Some(k) if !k.trim().is_empty() => k,
        _ => return ToolResult::error("EXA_API_KEY not configured".into()),
    };

    let clamped = num_results.max(1).min(20);
    let mut payload = json!({
        "query": query,
        "numResults": clamped,
    });
    if include_text {
        payload["contents"] = json!({"text": {"maxCharacters": 4000}});
    }

    let url = format!("{}/search", exa_base_url.trim_end_matches('/'));
    let client = reqwest::Client::new();
    let response = client
        .post(&url)
        .header("x-api-key", api_key)
        .header("Content-Type", "application/json")
        .header("User-Agent", "exa-py 1.0.18")
        .timeout(std::time::Duration::from_secs(timeout_sec))
        .json(&payload)
        .send()
        .await;

    let resp = match response {
        Ok(r) => r,
        Err(e) => return ToolResult::error(format!("Web search failed: {e}")),
    };

    let body: serde_json::Value = match resp.json().await {
        Ok(b) => b,
        Err(e) => return ToolResult::error(format!("Web search response parse error: {e}")),
    };

    let mut out_results: Vec<serde_json::Value> = Vec::new();
    if let Some(results) = body.get("results").and_then(|r| r.as_array()) {
        for row in results {
            let mut item = json!({
                "url": row.get("url").and_then(|u| u.as_str()).unwrap_or(""),
                "title": row.get("title").and_then(|t| t.as_str()).unwrap_or(""),
                "snippet": row.get("highlight").and_then(|h| h.as_str())
                    .or_else(|| row.get("snippet").and_then(|s| s.as_str()))
                    .unwrap_or(""),
            });
            if include_text {
                if let Some(text) = row.get("text").and_then(|t| t.as_str()) {
                    item["text"] = json!(clip(text, 4000));
                }
            }
            out_results.push(item);
        }
    }

    let output = json!({
        "query": query,
        "results": out_results,
        "total": out_results.len(),
    });
    ToolResult::ok(clip(
        &serde_json::to_string_pretty(&output).unwrap_or_default(),
        max_file_chars,
    ))
}

pub async fn fetch_url(
    exa_api_key: Option<&str>,
    exa_base_url: &str,
    urls: &[String],
    max_file_chars: usize,
    timeout_sec: u64,
) -> ToolResult {
    if urls.is_empty() {
        return ToolResult::error("fetch_url requires at least one valid URL".into());
    }

    let api_key = match exa_api_key {
        Some(k) if !k.trim().is_empty() => k,
        _ => return ToolResult::error("EXA_API_KEY not configured".into()),
    };

    let normalized: Vec<&str> = urls
        .iter()
        .map(|u| u.trim())
        .filter(|u| !u.is_empty())
        .take(10)
        .collect();

    if normalized.is_empty() {
        return ToolResult::error("fetch_url requires at least one valid URL".into());
    }

    let payload = json!({
        "ids": normalized,
        "text": { "maxCharacters": 8000 },
    });

    let url = format!("{}/contents", exa_base_url.trim_end_matches('/'));
    let client = reqwest::Client::new();
    let response = client
        .post(&url)
        .header("x-api-key", api_key)
        .header("Content-Type", "application/json")
        .header("User-Agent", "exa-py 1.0.18")
        .timeout(std::time::Duration::from_secs(timeout_sec))
        .json(&payload)
        .send()
        .await;

    let resp = match response {
        Ok(r) => r,
        Err(e) => return ToolResult::error(format!("Fetch URL failed: {e}")),
    };

    let body: serde_json::Value = match resp.json().await {
        Ok(b) => b,
        Err(e) => return ToolResult::error(format!("Fetch URL response parse error: {e}")),
    };

    let mut pages: Vec<serde_json::Value> = Vec::new();
    if let Some(results) = body.get("results").and_then(|r| r.as_array()) {
        for row in results {
            pages.push(json!({
                "url": row.get("url").and_then(|u| u.as_str()).unwrap_or(""),
                "title": row.get("title").and_then(|t| t.as_str()).unwrap_or(""),
                "text": clip(
                    row.get("text").and_then(|t| t.as_str()).unwrap_or(""),
                    8000,
                ),
            }));
        }
    }

    let output = json!({
        "pages": pages,
        "total": pages.len(),
    });
    ToolResult::ok(clip(
        &serde_json::to_string_pretty(&output).unwrap_or_default(),
        max_file_chars,
    ))
}

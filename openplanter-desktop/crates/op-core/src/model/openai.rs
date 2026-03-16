// OpenAI-compatible model implementation.
//
// Handles openai, openrouter, cerebras, zai, and ollama via /chat/completions.

use std::collections::HashMap;
use std::sync::{Arc, RwLock};
use std::time::Duration;

use anyhow::{Context, anyhow};
use chrono::{DateTime, Utc};
use reqwest_eventsource::{Event, RequestBuilderExt};
use tokio::time::sleep;
use tokio_util::sync::CancellationToken;

use super::{BaseModel, Message, ModelTurn, RateLimitError, ToolCall};
use crate::config::strip_foundry_model_prefix;
use crate::events::{DeltaEvent, DeltaKind};

#[derive(Debug, Clone, Default)]
pub struct ZaiRuntimeConfig {
    pub paygo_base_url: String,
    pub coding_base_url: String,
    pub stream_max_retries: usize,
}

struct StreamAttemptError {
    error: anyhow::Error,
    saw_output: bool,
}

pub struct OpenAIModel {
    client: reqwest::Client,
    model: String,
    provider: String,
    base_url: String,
    api_key: String,
    reasoning_effort: Option<String>,
    extra_headers: HashMap<String, String>,
    thinking_type: Option<String>,
    stream_max_retries: usize,
    fallback_base_urls: Vec<String>,
    active_base_url: Arc<RwLock<String>>,
}

impl OpenAIModel {
    pub fn new(
        model: String,
        provider: String,
        base_url: String,
        api_key: String,
        reasoning_effort: Option<String>,
        extra_headers: HashMap<String, String>,
    ) -> Self {
        Self {
            client: reqwest::Client::new(),
            model,
            provider,
            base_url: base_url.clone(),
            api_key,
            reasoning_effort,
            extra_headers,
            thinking_type: None,
            stream_max_retries: 1,
            fallback_base_urls: Vec::new(),
            active_base_url: Arc::new(RwLock::new(base_url)),
        }
    }

    pub fn with_zai_runtime(mut self, config: ZaiRuntimeConfig) -> Self {
        let effort = self
            .reasoning_effort
            .as_deref()
            .unwrap_or_default()
            .trim()
            .to_lowercase();
        self.thinking_type = Some(if effort.is_empty() || effort == "none" {
            "disabled".to_string()
        } else {
            "enabled".to_string()
        });
        self.stream_max_retries = config.stream_max_retries.max(1);

        let mut fallbacks = Vec::new();
        for candidate in [config.paygo_base_url, config.coding_base_url] {
            let trimmed = candidate.trim();
            if trimmed.is_empty() {
                continue;
            }
            if !fallbacks.iter().any(|url| url == trimmed) {
                fallbacks.push(trimmed.to_string());
            }
        }
        self.fallback_base_urls = fallbacks;
        self
    }

    fn is_reasoning_model(&self) -> bool {
        let lower = self.request_model_name().to_lowercase();
        if lower.starts_with("o1-")
            || lower == "o1"
            || lower.starts_with("o3-")
            || lower == "o3"
            || lower.starts_with("o4-")
            || lower == "o4"
        {
            return true;
        }
        if lower.starts_with("gpt-5") {
            return true;
        }
        false
    }

    fn request_model_name(&self) -> String {
        strip_foundry_model_prefix(&self.model)
    }

    fn convert_messages(messages: &[Message]) -> Vec<serde_json::Value> {
        messages
            .iter()
            .map(|msg| match msg {
                Message::System { content } => serde_json::json!({
                    "role": "system",
                    "content": content,
                }),
                Message::User { content } => serde_json::json!({
                    "role": "user",
                    "content": content,
                }),
                Message::Assistant {
                    content,
                    tool_calls,
                } => {
                    let mut obj = serde_json::json!({
                        "role": "assistant",
                        "content": content,
                    });
                    if let Some(tcs) = tool_calls {
                        let tc_arr: Vec<serde_json::Value> = tcs
                            .iter()
                            .map(|tc| {
                                serde_json::json!({
                                    "id": tc.id,
                                    "type": "function",
                                    "function": {
                                        "name": tc.name,
                                        "arguments": tc.arguments,
                                    }
                                })
                            })
                            .collect();
                        obj["tool_calls"] = serde_json::Value::Array(tc_arr);
                    }
                    obj
                }
                Message::Tool {
                    tool_call_id,
                    content,
                } => serde_json::json!({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": content,
                }),
            })
            .collect()
    }

    fn build_payload(
        &self,
        messages: &[Message],
        tools: &[serde_json::Value],
        stream: bool,
    ) -> serde_json::Value {
        let mut payload = serde_json::json!({
            "model": self.request_model_name(),
            "messages": Self::convert_messages(messages),
        });

        if stream {
            payload["stream"] = serde_json::json!(true);
            payload["stream_options"] = serde_json::json!({ "include_usage": true });
        }

        if !tools.is_empty() {
            payload["tools"] = serde_json::Value::Array(tools.to_vec());
            payload["tool_choice"] = serde_json::json!("auto");
        }

        if !self.is_reasoning_model() {
            payload["temperature"] = serde_json::json!(0.0);
        }

        if let Some(ref effort) = self.reasoning_effort {
            let effort_lower = effort.trim().to_lowercase();
            if !effort_lower.is_empty() {
                payload["reasoning_effort"] = serde_json::json!(effort_lower);
            }
        }

        if let Some(ref thinking_type) = self.thinking_type {
            let value = thinking_type.trim().to_lowercase();
            if matches!(value.as_str(), "enabled" | "disabled") {
                payload["thinking"] = serde_json::json!({ "type": value });
            }
        }

        payload
    }

    fn build_request(&self, url: &str, payload: &serde_json::Value) -> reqwest::RequestBuilder {
        let mut request = self
            .client
            .post(url)
            .header("Authorization", format!("Bearer {}", self.api_key))
            .header("Content-Type", "application/json");

        for (k, v) in &self.extra_headers {
            request = request.header(k.as_str(), v.as_str());
        }

        request.json(payload)
    }

    fn current_base_url(&self) -> String {
        self.active_base_url
            .read()
            .map(|value| value.clone())
            .unwrap_or_else(|_| self.base_url.clone())
    }

    fn set_active_base_url(&self, base_url: &str) {
        if let Ok(mut guard) = self.active_base_url.write() {
            *guard = base_url.to_string();
        }
    }

    fn candidate_base_urls(&self) -> Vec<String> {
        let mut urls = Vec::new();
        let current = self.current_base_url();
        urls.push(current);
        for candidate in &self.fallback_base_urls {
            if !urls.iter().any(|url| url == candidate) {
                urls.push(candidate.clone());
            }
        }
        urls
    }

    fn should_try_next_zai_base_url(&self, err: &anyhow::Error) -> bool {
        if self.provider != "zai" {
            return false;
        }
        let text = err.to_string().to_lowercase();
        text.contains("404") || text.contains("405") || text.contains("not found")
    }

    fn should_retry_zai_error(&self, err: &StreamAttemptError) -> bool {
        if self.provider != "zai" || err.saw_output {
            return false;
        }
        if err.error.downcast_ref::<RateLimitError>().is_some() {
            return true;
        }
        let text = err.error.to_string().to_lowercase();
        text.contains("429")
            || text.contains("1302")
            || text.contains("rate limit")
            || text.contains("too many requests")
            || text.contains("connection")
            || text.contains("timed out")
            || text.contains("timeout")
            || text.contains("stream ended")
            || text.contains("broken pipe")
            || text.contains("500")
            || text.contains("502")
            || text.contains("503")
            || text.contains("504")
    }

    fn parse_retry_after_value(value: Option<&serde_json::Value>) -> Option<f64> {
        match value {
            Some(serde_json::Value::Number(num)) => num.as_f64().map(|v| v.max(0.0)),
            Some(serde_json::Value::String(text)) => Self::parse_retry_after_text(text),
            _ => None,
        }
    }

    fn parse_retry_after_text(text: &str) -> Option<f64> {
        let trimmed = text.trim();
        if trimmed.is_empty() {
            return None;
        }
        if let Ok(seconds) = trimmed.parse::<f64>() {
            return Some(seconds.max(0.0));
        }
        let parsed = DateTime::parse_from_rfc2822(trimmed).ok()?;
        Some(
            (parsed.with_timezone(&Utc) - Utc::now())
                .num_milliseconds()
                .max(0) as f64
                / 1000.0,
        )
    }

    fn parse_retry_after_header(headers: &reqwest::header::HeaderMap) -> Option<f64> {
        let value = headers.get(reqwest::header::RETRY_AFTER)?;
        let text = value.to_str().ok()?;
        Self::parse_retry_after_text(text)
    }

    fn extract_provider_code(value: Option<&serde_json::Value>) -> Option<String> {
        match value {
            Some(serde_json::Value::String(text)) => {
                let trimmed = text.trim();
                (!trimmed.is_empty()).then(|| trimmed.to_string())
            }
            Some(serde_json::Value::Number(num)) => Some(num.to_string()),
            Some(other) => {
                let rendered = other.to_string();
                let trimmed = rendered.trim();
                (!trimmed.is_empty()).then(|| trimmed.to_string())
            }
            None => None,
        }
    }

    fn extract_openai_style_error(
        payload: &serde_json::Value,
    ) -> (String, Option<String>, Option<f64>) {
        if let Some(error) = payload.get("error").and_then(|value| value.as_object()) {
            let message = error
                .get("message")
                .and_then(|value| value.as_str())
                .unwrap_or_default()
                .trim()
                .to_string();
            let provider_code = Self::extract_provider_code(error.get("code"));
            let retry_after = Self::parse_retry_after_value(error.get("retry_after"))
                .or_else(|| Self::parse_retry_after_value(payload.get("retry_after")));
            return (message, provider_code, retry_after);
        }
        (
            String::new(),
            None,
            Self::parse_retry_after_value(payload.get("retry_after")),
        )
    }

    fn is_rate_limit_error(
        status_code: Option<u16>,
        provider_code: Option<&str>,
        message: &str,
    ) -> bool {
        if status_code == Some(429) {
            return true;
        }
        if let Some(code) = provider_code {
            let code = code.trim().to_lowercase();
            if matches!(
                code.as_str(),
                "1302" | "429" | "rate_limit" | "rate_limit_exceeded" | "too_many_requests"
            ) {
                return true;
            }
        }
        let text = message.to_lowercase();
        text.contains("rate limit") || text.contains("too many requests")
    }

    fn classify_stream_payload_error(payload: &serde_json::Value) -> Option<anyhow::Error> {
        let is_error_type = payload
            .get("type")
            .and_then(|value| value.as_str())
            .is_some_and(|value| value == "error");
        let error = payload.get("error")?;
        let message = error
            .get("message")
            .and_then(|value| value.as_str())
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(str::to_string)
            .unwrap_or_else(|| payload.to_string());
        let provider_code = Self::extract_provider_code(error.get("code"));
        let retry_after = Self::parse_retry_after_value(error.get("retry_after"));
        let prefixed_message = format!("Stream error: {message}");

        if Self::is_rate_limit_error(None, provider_code.as_deref(), &message) {
            return Some(anyhow::Error::new(RateLimitError {
                message: prefixed_message,
                status_code: None,
                provider_code,
                body: payload.to_string(),
                retry_after_sec: retry_after,
            }));
        }

        if is_error_type || provider_code.is_some() || payload.get("retry_after").is_some() {
            return Some(anyhow!(prefixed_message));
        }

        None
    }

    async fn classify_sse_error(
        &self,
        url: &str,
        error: reqwest_eventsource::Error,
    ) -> anyhow::Error {
        match error {
            reqwest_eventsource::Error::InvalidStatusCode(status, response) => {
                self.classify_invalid_status(url, status, response).await
            }
            other => anyhow!("SSE stream error: {other}"),
        }
    }

    async fn classify_invalid_status(
        &self,
        url: &str,
        status: reqwest::StatusCode,
        response: reqwest::Response,
    ) -> anyhow::Error {
        let response_url = response.url().clone();
        let headers = response.headers().clone();
        let body = response.text().await.unwrap_or_default();
        let parsed = serde_json::from_str::<serde_json::Value>(&body).ok();
        let mut message = String::new();
        let mut provider_code = None;
        let mut retry_after = Self::parse_retry_after_header(&headers);

        if let Some(ref payload) = parsed {
            let (body_message, body_code, body_retry_after) =
                Self::extract_openai_style_error(payload);
            message = body_message;
            provider_code = body_code;
            if retry_after.is_none() {
                retry_after = body_retry_after;
            }
        }

        let detail = if !message.is_empty() {
            message.clone()
        } else if !body.trim().is_empty() {
            body.clone()
        } else {
            status.to_string()
        };

        if Self::is_rate_limit_error(Some(status.as_u16()), provider_code.as_deref(), &detail) {
            return anyhow::Error::new(RateLimitError {
                message: format!(
                    "HTTP {} calling {}: {}",
                    status.as_u16(),
                    response_url,
                    detail
                ),
                status_code: Some(status.as_u16()),
                provider_code,
                body,
                retry_after_sec: retry_after,
            });
        }

        anyhow!(
            "HTTP {} calling {}: {}",
            status.as_u16(),
            if response_url.as_str().is_empty() {
                url
            } else {
                response_url.as_str()
            },
            detail
        )
    }

    async fn chat_stream_once(
        &self,
        base_url: &str,
        messages: &[Message],
        tools: &[serde_json::Value],
        on_delta: &(dyn Fn(DeltaEvent) + Send + Sync),
        cancel: &CancellationToken,
    ) -> Result<ModelTurn, StreamAttemptError> {
        let url = format!("{}/chat/completions", base_url.trim_end_matches('/'));
        let payload = self.build_payload(messages, tools, true);
        let request = self.build_request(&url, &payload);
        let mut es = request.eventsource().map_err(|e| StreamAttemptError {
            error: anyhow!("Failed to open SSE stream: {e}"),
            saw_output: false,
        })?;

        let mut text = String::new();
        let mut thinking = String::new();
        let mut tool_calls_by_index: HashMap<usize, (String, String, String)> = HashMap::new();
        let mut input_tokens: u64 = 0;
        let mut output_tokens: u64 = 0;
        let mut saw_output = false;

        use futures::StreamExt;
        loop {
            if cancel.is_cancelled() {
                es.close();
                return Err(StreamAttemptError {
                    error: anyhow!("Cancelled"),
                    saw_output,
                });
            }

            let event = tokio::select! {
                _ = cancel.cancelled() => {
                    es.close();
                    return Err(StreamAttemptError {
                        error: anyhow!("Cancelled"),
                        saw_output,
                    });
                }
                ev = es.next() => ev,
            };

            let event = match event {
                Some(Ok(ev)) => ev,
                Some(Err(reqwest_eventsource::Error::StreamEnded)) => break,
                Some(Err(e)) => {
                    es.close();
                    let error = self.classify_sse_error(&url, e).await;
                    return Err(StreamAttemptError { error, saw_output });
                }
                None => break,
            };

            match event {
                Event::Open => {}
                Event::Message(msg) => {
                    if msg.data == "[DONE]" {
                        break;
                    }

                    let chunk: serde_json::Value = serde_json::from_str(&msg.data)
                        .with_context(|| format!("Failed to parse SSE chunk: {}", &msg.data))
                        .map_err(|error| StreamAttemptError { error, saw_output })?;

                    if let Some(error) = Self::classify_stream_payload_error(&chunk) {
                        return Err(StreamAttemptError { error, saw_output });
                    }

                    if let Some(usage) = chunk.get("usage") {
                        if let Some(pt) = usage.get("prompt_tokens").and_then(|v| v.as_u64()) {
                            input_tokens = pt;
                        }
                        if let Some(ct) = usage.get("completion_tokens").and_then(|v| v.as_u64()) {
                            output_tokens = ct;
                        }
                    }

                    let choices = match chunk.get("choices").and_then(|c| c.as_array()) {
                        Some(c) => c,
                        None => continue,
                    };
                    if choices.is_empty() {
                        continue;
                    }

                    let delta = match choices[0].get("delta") {
                        Some(d) => d,
                        None => continue,
                    };

                    if let Some(content) = delta.get("content").and_then(|c| c.as_str()) {
                        if !content.is_empty() {
                            saw_output = true;
                            text.push_str(content);
                            on_delta(DeltaEvent {
                                kind: DeltaKind::Text,
                                text: content.to_string(),
                            });
                        }
                    }

                    for field in ["reasoning_content", "reasoning", "thinking"] {
                        if let Some(value) = delta.get(field).and_then(|c| c.as_str()) {
                            if !value.is_empty() {
                                saw_output = true;
                                thinking.push_str(value);
                                on_delta(DeltaEvent {
                                    kind: DeltaKind::Thinking,
                                    text: value.to_string(),
                                });
                            }
                        }
                    }

                    if let Some(tc_deltas) = delta.get("tool_calls").and_then(|t| t.as_array()) {
                        for tc_delta in tc_deltas {
                            let idx = tc_delta.get("index").and_then(|i| i.as_u64()).unwrap_or(0)
                                as usize;
                            let entry = tool_calls_by_index
                                .entry(idx)
                                .or_insert_with(|| (String::new(), String::new(), String::new()));

                            if let Some(id) = tc_delta.get("id").and_then(|i| i.as_str()) {
                                if !id.is_empty() {
                                    entry.0 = id.to_string();
                                }
                            }

                            if let Some(func) = tc_delta.get("function") {
                                if let Some(name) = func.get("name").and_then(|n| n.as_str()) {
                                    if !name.is_empty() {
                                        saw_output = true;
                                        entry.1 = name.to_string();
                                        on_delta(DeltaEvent {
                                            kind: DeltaKind::ToolCallStart,
                                            text: name.to_string(),
                                        });
                                    }
                                }
                                if let Some(args) = func.get("arguments").and_then(|a| a.as_str()) {
                                    if !args.is_empty() {
                                        saw_output = true;
                                        entry.2.push_str(args);
                                        on_delta(DeltaEvent {
                                            kind: DeltaKind::ToolCallArgs,
                                            text: args.to_string(),
                                        });
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        let mut tool_calls: Vec<ToolCall> = Vec::new();
        let mut indices: Vec<usize> = tool_calls_by_index.keys().copied().collect();
        indices.sort();
        for idx in indices {
            let (id, name, arguments) = tool_calls_by_index.remove(&idx).unwrap();
            tool_calls.push(ToolCall {
                id,
                name,
                arguments,
            });
        }

        Ok(ModelTurn {
            text,
            thinking: if thinking.is_empty() {
                None
            } else {
                Some(thinking)
            },
            tool_calls,
            input_tokens,
            output_tokens,
        })
    }
}

#[async_trait::async_trait]
impl BaseModel for OpenAIModel {
    async fn chat(
        &self,
        messages: &[Message],
        tools: &[serde_json::Value],
    ) -> anyhow::Result<ModelTurn> {
        let noop = |_: DeltaEvent| {};
        let cancel = CancellationToken::new();
        self.chat_stream(messages, tools, &noop, &cancel).await
    }

    async fn chat_stream(
        &self,
        messages: &[Message],
        tools: &[serde_json::Value],
        on_delta: &(dyn Fn(DeltaEvent) + Send + Sync),
        cancel: &CancellationToken,
    ) -> anyhow::Result<ModelTurn> {
        let max_attempts = if self.provider == "zai" {
            self.stream_max_retries.max(1)
        } else {
            1
        };
        let mut last_error: Option<anyhow::Error> = None;

        for attempt in 0..max_attempts {
            for base_url in self.candidate_base_urls() {
                match self
                    .chat_stream_once(&base_url, messages, tools, on_delta, cancel)
                    .await
                {
                    Ok(turn) => {
                        self.set_active_base_url(&base_url);
                        return Ok(turn);
                    }
                    Err(err) => {
                        let should_try_next = self.should_try_next_zai_base_url(&err.error);
                        let should_retry = self.should_retry_zai_error(&err);
                        last_error = Some(err.error);

                        if should_try_next {
                            continue;
                        }

                        if should_retry && attempt + 1 < max_attempts {
                            break;
                        }

                        return Err(last_error
                            .take()
                            .unwrap_or_else(|| anyhow!("OpenAI-compatible request failed")));
                    }
                }
            }

            if attempt + 1 < max_attempts {
                let backoff_ms = (250_u64 << attempt.min(3)).min(2_000);
                sleep(Duration::from_millis(backoff_ms)).await;
            }
        }

        Err(last_error.unwrap_or_else(|| anyhow!("OpenAI-compatible request failed")))
    }

    fn model_name(&self) -> &str {
        &self.model
    }

    fn provider_name(&self) -> &str {
        &self.provider
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_model(model: &str, reasoning_effort: Option<&str>) -> OpenAIModel {
        OpenAIModel::new(
            model.to_string(),
            "openai".to_string(),
            "https://api.openai.com/v1".to_string(),
            "sk-test".to_string(),
            reasoning_effort.map(|s| s.to_string()),
            HashMap::new(),
        )
    }

    #[test]
    fn test_reasoning_model_o1() {
        assert!(make_model("o1", None).is_reasoning_model());
        assert!(make_model("o1-preview", None).is_reasoning_model());
    }

    #[test]
    fn test_reasoning_model_o3() {
        assert!(make_model("o3", None).is_reasoning_model());
        assert!(make_model("o3-mini", None).is_reasoning_model());
    }

    #[test]
    fn test_reasoning_model_gpt5() {
        assert!(make_model("gpt-5.2", None).is_reasoning_model());
        assert!(make_model("gpt-5", None).is_reasoning_model());
        assert!(make_model("azure-foundry/gpt-5.3-codex", None).is_reasoning_model());
    }

    #[test]
    fn test_not_reasoning_model() {
        assert!(!make_model("gpt-4o", None).is_reasoning_model());
        assert!(!make_model("claude-opus-4-6", None).is_reasoning_model());
    }

    #[test]
    fn test_convert_system_message() {
        let msgs = vec![Message::System {
            content: "You are helpful.".to_string(),
        }];
        let converted = OpenAIModel::convert_messages(&msgs);
        assert_eq!(converted.len(), 1);
        assert_eq!(converted[0]["role"], "system");
        assert_eq!(converted[0]["content"], "You are helpful.");
    }

    #[test]
    fn test_convert_user_message() {
        let msgs = vec![Message::User {
            content: "Hello".to_string(),
        }];
        let converted = OpenAIModel::convert_messages(&msgs);
        assert_eq!(converted[0]["role"], "user");
        assert_eq!(converted[0]["content"], "Hello");
    }

    #[test]
    fn test_convert_assistant_with_tool_calls() {
        let msgs = vec![Message::Assistant {
            content: "Let me help.".to_string(),
            tool_calls: Some(vec![ToolCall {
                id: "call_1".to_string(),
                name: "read_file".to_string(),
                arguments: r#"{"path":"test.txt"}"#.to_string(),
            }]),
        }];
        let converted = OpenAIModel::convert_messages(&msgs);
        assert_eq!(converted[0]["role"], "assistant");
        assert_eq!(converted[0]["content"], "Let me help.");
        let tcs = converted[0]["tool_calls"].as_array().unwrap();
        assert_eq!(tcs.len(), 1);
        assert_eq!(tcs[0]["id"], "call_1");
        assert_eq!(tcs[0]["function"]["name"], "read_file");
    }

    #[test]
    fn test_convert_tool_message() {
        let msgs = vec![Message::Tool {
            tool_call_id: "call_1".to_string(),
            content: "file contents".to_string(),
        }];
        let converted = OpenAIModel::convert_messages(&msgs);
        assert_eq!(converted[0]["role"], "tool");
        assert_eq!(converted[0]["tool_call_id"], "call_1");
        assert_eq!(converted[0]["content"], "file contents");
    }

    #[test]
    fn test_payload_non_reasoning_has_temperature() {
        let model = make_model("gpt-4o", None);
        let msgs = vec![Message::User {
            content: "Hi".to_string(),
        }];
        let payload = model.build_payload(&msgs, &[], true);
        assert_eq!(payload["temperature"], 0.0);
        assert_eq!(payload["stream"], true);
        assert!(payload.get("stream_options").is_some());
    }

    #[test]
    fn test_payload_reasoning_omits_temperature() {
        let model = make_model("o3", Some("high"));
        let msgs = vec![Message::User {
            content: "Hi".to_string(),
        }];
        let payload = model.build_payload(&msgs, &[], true);
        assert!(payload.get("temperature").is_none());
        assert_eq!(payload["reasoning_effort"], "high");
    }

    #[test]
    fn test_payload_strips_foundry_prefix() {
        let model = make_model("azure-foundry/gpt-5.3-codex", Some("high"));
        let msgs = vec![Message::User {
            content: "Hi".to_string(),
        }];
        let payload = model.build_payload(&msgs, &[], true);
        assert_eq!(payload["model"], "gpt-5.3-codex");
    }

    #[test]
    fn test_payload_with_tools() {
        let model = make_model("gpt-4o", None);
        let msgs = vec![Message::User {
            content: "Hi".to_string(),
        }];
        let tools = vec![serde_json::json!({"type": "function", "function": {"name": "test"}})];
        let payload = model.build_payload(&msgs, &tools, true);
        assert!(payload.get("tools").is_some());
        assert_eq!(payload["tool_choice"], "auto");
    }

    #[test]
    fn test_payload_no_tools_omits_tool_choice() {
        let model = make_model("gpt-4o", None);
        let msgs = vec![Message::User {
            content: "Hi".to_string(),
        }];
        let payload = model.build_payload(&msgs, &[], true);
        assert!(payload.get("tools").is_none());
        assert!(payload.get("tool_choice").is_none());
    }

    #[test]
    fn test_payload_zai_includes_thinking() {
        let model = OpenAIModel::new(
            "glm-5".to_string(),
            "zai".to_string(),
            "https://api.z.ai/api/paas/v4".to_string(),
            "zai-key".to_string(),
            Some("high".to_string()),
            HashMap::new(),
        )
        .with_zai_runtime(ZaiRuntimeConfig {
            paygo_base_url: "https://api.z.ai/api/paas/v4".to_string(),
            coding_base_url: "https://api.z.ai/api/coding/paas/v4".to_string(),
            stream_max_retries: 4,
        });
        let msgs = vec![Message::User {
            content: "Hi".to_string(),
        }];
        let payload = model.build_payload(&msgs, &[], true);
        assert_eq!(payload["thinking"]["type"], "enabled");
    }

    #[test]
    fn test_zai_runtime_switches_to_disabled_when_no_effort() {
        let model = OpenAIModel::new(
            "glm-5".to_string(),
            "zai".to_string(),
            "https://api.z.ai/api/paas/v4".to_string(),
            "zai-key".to_string(),
            None,
            HashMap::new(),
        )
        .with_zai_runtime(ZaiRuntimeConfig {
            paygo_base_url: "https://api.z.ai/api/paas/v4".to_string(),
            coding_base_url: "https://api.z.ai/api/coding/paas/v4".to_string(),
            stream_max_retries: 4,
        });
        let msgs = vec![Message::User {
            content: "Hi".to_string(),
        }];
        let payload = model.build_payload(&msgs, &[], true);
        assert_eq!(payload["thinking"]["type"], "disabled");
    }

    #[test]
    fn test_zai_candidate_base_urls_prefers_active() {
        let model = OpenAIModel::new(
            "glm-5".to_string(),
            "zai".to_string(),
            "https://api.z.ai/api/paas/v4".to_string(),
            "zai-key".to_string(),
            Some("medium".to_string()),
            HashMap::new(),
        )
        .with_zai_runtime(ZaiRuntimeConfig {
            paygo_base_url: "https://api.z.ai/api/paas/v4".to_string(),
            coding_base_url: "https://api.z.ai/api/coding/paas/v4".to_string(),
            stream_max_retries: 4,
        });
        model.set_active_base_url("https://api.z.ai/api/coding/paas/v4");
        assert_eq!(
            model.candidate_base_urls(),
            vec![
                "https://api.z.ai/api/coding/paas/v4".to_string(),
                "https://api.z.ai/api/paas/v4".to_string(),
            ]
        );
    }

    #[test]
    fn test_retry_after_parses_seconds_and_http_dates() {
        assert_eq!(OpenAIModel::parse_retry_after_text("3"), Some(3.0));
        assert!(OpenAIModel::parse_retry_after_text("Wed, 21 Oct 2015 07:28:00 GMT").is_some());
        assert_eq!(OpenAIModel::parse_retry_after_text(""), None);
    }

    #[test]
    fn test_classify_stream_payload_rate_limit_error() {
        let payload = serde_json::json!({
            "type": "error",
            "error": {
                "message": "Too many requests",
                "code": "1302",
                "retry_after": 4
            }
        });
        let error = OpenAIModel::classify_stream_payload_error(&payload)
            .expect("payload should classify as an error");
        let rate_limit = error
            .downcast_ref::<RateLimitError>()
            .expect("expected a structured rate-limit error");
        assert_eq!(rate_limit.provider_code.as_deref(), Some("1302"));
        assert_eq!(rate_limit.retry_after_sec, Some(4.0));
    }

    #[test]
    fn test_model_name_and_provider() {
        let model = make_model("gpt-4o", None);
        assert_eq!(model.model_name(), "gpt-4o");
        assert_eq!(model.provider_name(), "openai");
    }
}

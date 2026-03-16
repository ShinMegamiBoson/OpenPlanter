// OpenAI-compatible model implementation.
//
// Handles openai, openrouter, cerebras, and ollama — all use /chat/completions.

use std::collections::HashMap;

use anyhow::{anyhow, Context};
use reqwest_eventsource::{Event, RequestBuilderExt};
use tokio_util::sync::CancellationToken;

use crate::events::{DeltaEvent, DeltaKind};
use super::{BaseModel, Message, ModelTurn, ToolCall};

pub struct OpenAIModel {
    client: reqwest::Client,
    model: String,
    provider: String,
    base_url: String,
    api_key: String,
    reasoning_effort: Option<String>,
    extra_headers: HashMap<String, String>,
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
            base_url,
            api_key,
            reasoning_effort,
            extra_headers,
        }
    }

    fn is_reasoning_model(&self) -> bool {
        let lower = self.model.to_lowercase();
        if lower.starts_with("o1-") || lower == "o1"
            || lower.starts_with("o3-") || lower == "o3"
            || lower.starts_with("o4-") || lower == "o4"
        {
            return true;
        }
        if lower.starts_with("gpt-5") {
            return true;
        }
        false
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
                Message::Assistant { content, tool_calls } => {
                    let mut obj = serde_json::json!({
                        "role": "assistant",
                        "content": content,
                    });
                    if let Some(tcs) = tool_calls {
                        let tc_arr: Vec<serde_json::Value> = tcs
                            .iter()
                            .map(|tc| serde_json::json!({
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": tc.arguments,
                                }
                            }))
                            .collect();
                        obj["tool_calls"] = serde_json::Value::Array(tc_arr);
                    }
                    obj
                }
                Message::Tool { tool_call_id, content } => serde_json::json!({
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
            "model": self.model,
            "messages": Self::convert_messages(messages),
        });

        if stream {
            payload["stream"] = serde_json::json!(true);
            payload["stream_options"] = serde_json::json!({"include_usage": true});
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

        payload
    }
}

#[async_trait::async_trait]
impl BaseModel for OpenAIModel {
    async fn chat(
        &self,
        messages: &[Message],
        tools: &[serde_json::Value],
    ) -> anyhow::Result<ModelTurn> {
        // Default: call chat_stream with a no-op callback
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
        let url = format!("{}/chat/completions", self.base_url.trim_end_matches('/'));
        let payload = self.build_payload(messages, tools, true);

        let mut request = self
            .client
            .post(&url)
            .header("Authorization", format!("Bearer {}", self.api_key))
            .header("Content-Type", "application/json");

        for (k, v) in &self.extra_headers {
            request = request.header(k.as_str(), v.as_str());
        }

        let mut es = request.json(&payload).eventsource()?;

        let mut text = String::new();
        let mut tool_calls_by_index: HashMap<usize, (String, String, String)> = HashMap::new(); // (id, name, args)
        let mut input_tokens: u64 = 0;
        let mut output_tokens: u64 = 0;

        use futures::StreamExt;
        loop {
            if cancel.is_cancelled() {
                es.close();
                return Err(anyhow!("Cancelled"));
            }

            let event = tokio::select! {
                _ = cancel.cancelled() => {
                    es.close();
                    return Err(anyhow!("Cancelled"));
                }
                ev = es.next() => ev,
            };

            let event = match event {
                Some(Ok(ev)) => ev,
                Some(Err(reqwest_eventsource::Error::StreamEnded)) => break,
                Some(Err(e)) => {
                    es.close();
                    return Err(anyhow!("SSE stream error: {e}"));
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
                        .with_context(|| format!("Failed to parse SSE chunk: {}", &msg.data))?;

                    // Extract usage from any chunk that has it
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

                    // Text content delta
                    if let Some(content) = delta.get("content").and_then(|c| c.as_str()) {
                        if !content.is_empty() {
                            text.push_str(content);
                            on_delta(DeltaEvent {
                                kind: DeltaKind::Text,
                                text: content.to_string(),
                            });
                        }
                    }

                    // Tool call deltas
                    if let Some(tc_deltas) = delta.get("tool_calls").and_then(|t| t.as_array()) {
                        for tc_delta in tc_deltas {
                            let idx = tc_delta.get("index").and_then(|i| i.as_u64()).unwrap_or(0) as usize;
                            let entry = tool_calls_by_index.entry(idx).or_insert_with(|| {
                                (String::new(), String::new(), String::new())
                            });

                            if let Some(id) = tc_delta.get("id").and_then(|i| i.as_str()) {
                                if !id.is_empty() {
                                    entry.0 = id.to_string();
                                }
                            }

                            if let Some(func) = tc_delta.get("function") {
                                if let Some(name) = func.get("name").and_then(|n| n.as_str()) {
                                    if !name.is_empty() {
                                        entry.1 = name.to_string();
                                        on_delta(DeltaEvent {
                                            kind: DeltaKind::ToolCallStart,
                                            text: name.to_string(),
                                        });
                                    }
                                }
                                if let Some(args) = func.get("arguments").and_then(|a| a.as_str()) {
                                    if !args.is_empty() {
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

        // Build tool calls from accumulated data
        let mut tool_calls: Vec<ToolCall> = Vec::new();
        let mut indices: Vec<usize> = tool_calls_by_index.keys().copied().collect();
        indices.sort();
        for idx in indices {
            let (id, name, arguments) = tool_calls_by_index.remove(&idx).unwrap();
            tool_calls.push(ToolCall { id, name, arguments });
        }

        Ok(ModelTurn {
            text,
            thinking: None,
            tool_calls,
            input_tokens,
            output_tokens,
        })
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

    // ── is_reasoning_model ──

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
    }

    #[test]
    fn test_not_reasoning_model() {
        assert!(!make_model("gpt-4o", None).is_reasoning_model());
        assert!(!make_model("claude-opus-4-6", None).is_reasoning_model());
    }

    // ── convert_messages ──

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

    // ── build_payload ──

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

    // ── model_name / provider_name ──

    #[test]
    fn test_model_name_and_provider() {
        let model = make_model("gpt-4o", None);
        assert_eq!(model.model_name(), "gpt-4o");
        assert_eq!(model.provider_name(), "openai");
    }
}

/// Model abstraction layer — trait + provider implementations.
///
/// Full implementation in Phase 2.
pub mod openai;
pub mod anthropic;
pub mod sse;

use serde::{Deserialize, Serialize};

/// A single tool call returned by the model.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolCall {
    pub id: String,
    pub name: String,
    pub arguments: String,
}

/// A single model turn — text, thinking, and/or tool calls.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ModelTurn {
    pub text: String,
    pub thinking: Option<String>,
    pub tool_calls: Vec<ToolCall>,
    pub input_tokens: u64,
    pub output_tokens: u64,
}

/// A conversation message.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "role")]
pub enum Message {
    #[serde(rename = "system")]
    System { content: String },
    #[serde(rename = "user")]
    User { content: String },
    #[serde(rename = "assistant")]
    Assistant { content: String, tool_calls: Option<Vec<ToolCall>> },
    #[serde(rename = "tool")]
    Tool { tool_call_id: String, content: String },
}

/// Trait for LLM model implementations.
#[async_trait::async_trait]
pub trait BaseModel: Send + Sync {
    /// Send a conversation and return the model's turn.
    async fn chat(&self, messages: &[Message], tools: &[serde_json::Value]) -> anyhow::Result<ModelTurn>;

    /// The model name.
    fn model_name(&self) -> &str;

    /// The provider name.
    fn provider_name(&self) -> &str;
}

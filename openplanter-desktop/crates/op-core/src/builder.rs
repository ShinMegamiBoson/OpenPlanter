/// Engine construction and provider inference.
///
/// Mirrors `agent/builder.py` — regex-based provider detection,
/// model validation, and engine factory.
use regex::Regex;
use std::sync::LazyLock;

use crate::config::{AgentConfig, PROVIDER_DEFAULT_MODELS};

/// Error type for model/builder operations.
#[derive(Debug, thiserror::Error)]
pub enum ModelError {
    #[error("{0}")]
    Message(String),
}

// Provider inference regexes — order matters (Cerebras `qwen-3` before Ollama `qwen`).
static ANTHROPIC_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?i)^claude").unwrap());

static OPENAI_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?i)^(gpt|o[1-4]-|o[1-4]$|chatgpt|dall-e|tts-|whisper)").unwrap());

static CEREBRAS_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?i)^(llama.*cerebras|qwen-3|gpt-oss|zai-glm)").unwrap());

// Ollama regex: `qwen` without lookahead — Cerebras check runs first, so
// `qwen-3*` is already caught before we reach this regex.
static OLLAMA_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r"(?i)^(llama|mistral|gemma|phi|codellama|deepseek|vicuna|tinyllama|neural-chat|dolphin|wizardlm|orca|nous-hermes|command-r|qwen)",
    )
    .unwrap()
});

/// Infer the likely provider for a model name, or `None` if ambiguous.
pub fn infer_provider_for_model(model: &str) -> Option<&'static str> {
    if model.contains('/') {
        return Some("openrouter");
    }
    if ANTHROPIC_RE.is_match(model) {
        return Some("anthropic");
    }
    if CEREBRAS_RE.is_match(model) {
        return Some("cerebras");
    }
    if OPENAI_RE.is_match(model) {
        return Some("openai");
    }
    if OLLAMA_RE.is_match(model) {
        return Some("ollama");
    }
    None
}

/// Validate that a model name is compatible with the given provider.
pub fn validate_model_provider(model_name: &str, provider: &str) -> Result<(), ModelError> {
    if provider == "openrouter" {
        return Ok(());
    }
    let inferred = infer_provider_for_model(model_name);
    match inferred {
        None | Some("openrouter") => Ok(()),
        Some(p) if p == provider => Ok(()),
        Some(p) => Err(ModelError::Message(format!(
            "Model '{}' belongs to provider '{}', not '{}'. \
             Use --provider {} or pick a model that matches the current provider.",
            model_name, p, provider, p
        ))),
    }
}

/// Resolve the model name from config, handling the "newest" keyword.
pub fn resolve_model_name(cfg: &AgentConfig) -> Result<String, ModelError> {
    let selected = cfg.model.trim();
    if !selected.is_empty() && selected.to_lowercase() != "newest" {
        return Ok(selected.to_string());
    }
    if selected.to_lowercase() == "newest" {
        // In the full implementation this would call list_models for the provider.
        // For now, fall through to defaults.
        return Ok(PROVIDER_DEFAULT_MODELS
            .get(cfg.provider.as_str())
            .unwrap_or(&"claude-opus-4-6")
            .to_string());
    }
    Ok(PROVIDER_DEFAULT_MODELS
        .get(cfg.provider.as_str())
        .unwrap_or(&"claude-opus-4-6")
        .to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_infer_anthropic() {
        assert_eq!(
            infer_provider_for_model("claude-opus-4-6"),
            Some("anthropic")
        );
        assert_eq!(
            infer_provider_for_model("claude-sonnet-4-5"),
            Some("anthropic")
        );
        assert_eq!(
            infer_provider_for_model("claude-haiku-4-5"),
            Some("anthropic")
        );
    }

    #[test]
    fn test_infer_openai() {
        assert_eq!(infer_provider_for_model("gpt-5.2"), Some("openai"));
        assert_eq!(infer_provider_for_model("o1-preview"), Some("openai"));
        assert_eq!(infer_provider_for_model("o3"), Some("openai"));
        assert_eq!(infer_provider_for_model("chatgpt-4o"), Some("openai"));
    }

    #[test]
    fn test_infer_openrouter() {
        assert_eq!(
            infer_provider_for_model("anthropic/claude-sonnet-4-5"),
            Some("openrouter")
        );
        assert_eq!(
            infer_provider_for_model("openai/gpt-5.2"),
            Some("openrouter")
        );
    }

    #[test]
    fn test_infer_cerebras() {
        assert_eq!(
            infer_provider_for_model("qwen-3-235b-a22b-instruct-2507"),
            Some("cerebras")
        );
    }

    #[test]
    fn test_infer_ollama() {
        assert_eq!(infer_provider_for_model("llama3.2"), Some("ollama"));
        assert_eq!(infer_provider_for_model("mistral"), Some("ollama"));
        assert_eq!(infer_provider_for_model("phi"), Some("ollama"));
        assert_eq!(infer_provider_for_model("deepseek"), Some("ollama"));
        // qwen without -3 should be ollama
        assert_eq!(infer_provider_for_model("qwen2"), Some("ollama"));
    }

    #[test]
    fn test_cerebras_before_ollama_qwen() {
        // qwen-3 → cerebras, qwen (no -3) → ollama
        assert_eq!(infer_provider_for_model("qwen-3"), Some("cerebras"));
        assert_eq!(infer_provider_for_model("qwen2"), Some("ollama"));
    }

    #[test]
    fn test_infer_unknown() {
        assert_eq!(infer_provider_for_model("some-random-model"), None);
    }

    #[test]
    fn test_validate_model_provider_ok() {
        assert!(validate_model_provider("gpt-5.2", "openai").is_ok());
        assert!(validate_model_provider("claude-opus-4-6", "anthropic").is_ok());
        // OpenRouter accepts anything
        assert!(validate_model_provider("gpt-5.2", "openrouter").is_ok());
        // Unknown model is accepted
        assert!(validate_model_provider("some-model", "openai").is_ok());
    }

    #[test]
    fn test_validate_model_provider_mismatch() {
        let result = validate_model_provider("gpt-5.2", "anthropic");
        assert!(result.is_err());
        let err = result.unwrap_err().to_string();
        assert!(err.contains("openai"));
        assert!(err.contains("anthropic"));
    }

    #[test]
    fn test_resolve_model_name_explicit() {
        let cfg = AgentConfig {
            model: "gpt-5.2".into(),
            provider: "openai".into(),
            ..Default::default()
        };
        assert_eq!(resolve_model_name(&cfg).unwrap(), "gpt-5.2");
    }

    #[test]
    fn test_resolve_model_name_default() {
        let cfg = AgentConfig {
            model: "".into(),
            provider: "openai".into(),
            ..Default::default()
        };
        assert_eq!(resolve_model_name(&cfg).unwrap(), "gpt-5.2");
    }
}

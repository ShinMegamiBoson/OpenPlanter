use std::collections::HashMap;
use std::env;
use std::path::{Path, PathBuf};
use std::sync::LazyLock;

use serde::{Deserialize, Serialize};

pub const AZURE_FOUNDRY_MODEL_PREFIX: &str = "azure-foundry/";
pub const ANTHROPIC_FOUNDRY_MODEL_PREFIX: &str = "anthropic-foundry/";
pub const FOUNDRY_OPENAI_BASE_URL: &str = "https://foundry-proxy.cheetah-koi.ts.net/openai/v1";
pub const FOUNDRY_ANTHROPIC_BASE_URL: &str =
    "https://foundry-proxy.cheetah-koi.ts.net/anthropic/v1";
pub const FOUNDRY_OPENAI_API_KEY_PLACEHOLDER: &str = "dont-worry-this-key-will-be-auto-injected";
pub const FOUNDRY_ANTHROPIC_API_KEY_PLACEHOLDER: &str = "dont-worry-it-will-be-injected";
pub const ZAI_PAYGO_BASE_URL: &str = "https://api.z.ai/api/paas/v4";
pub const ZAI_CODING_BASE_URL: &str = "https://api.z.ai/api/coding/paas/v4";
pub const BRAVE_BASE_URL: &str = "https://api.search.brave.com/res/v1";
pub const TAVILY_BASE_URL: &str = "https://api.tavily.com";

/// Default model for each supported provider.
pub static PROVIDER_DEFAULT_MODELS: LazyLock<HashMap<&'static str, &'static str>> =
    LazyLock::new(|| {
        HashMap::from([
            ("openai", "azure-foundry/gpt-5.4"),
            ("anthropic", "anthropic-foundry/claude-opus-4-6"),
            ("openrouter", "anthropic/claude-sonnet-4-5"),
            ("cerebras", "qwen-3-235b-a22b-instruct-2507"),
            ("zai", "glm-5"),
            ("ollama", "llama3.2"),
        ])
    });

fn env_or(key: &str, default: &str) -> String {
    env::var(key).unwrap_or_else(|_| default.to_string())
}

fn env_opt(key: &str) -> Option<String> {
    env::var(key).ok().filter(|s| !s.trim().is_empty())
}

fn env_int(key: &str, default: i64) -> i64 {
    env::var(key)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

fn env_float(key: &str, default: f64) -> f64 {
    env::var(key)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

fn env_bool(key: &str, default: bool) -> bool {
    match env::var(key) {
        Ok(v) => matches!(v.trim().to_lowercase().as_str(), "1" | "true" | "yes"),
        Err(_) => default,
    }
}

pub fn normalize_zai_plan(value: Option<&str>) -> String {
    match value.unwrap_or_default().trim().to_lowercase().as_str() {
        "coding" => "coding".to_string(),
        _ => "paygo".to_string(),
    }
}

pub fn resolve_zai_base_url(plan: &str, paygo_base_url: &str, coding_base_url: &str) -> String {
    if normalize_zai_plan(Some(plan)) == "coding" {
        coding_base_url.to_string()
    } else {
        paygo_base_url.to_string()
    }
}

pub fn normalize_web_search_provider(value: Option<&str>) -> String {
    match value.unwrap_or_default().trim().to_lowercase().as_str() {
        "firecrawl" => "firecrawl".to_string(),
        "brave" => "brave".to_string(),
        "tavily" => "tavily".to_string(),
        _ => "exa".to_string(),
    }
}

fn normalize_base_url(value: &str) -> String {
    value.trim().trim_end_matches('/').to_string()
}

pub fn is_foundry_openai_base_url(value: &str) -> bool {
    normalize_base_url(value) == FOUNDRY_OPENAI_BASE_URL
}

pub fn is_foundry_anthropic_base_url(value: &str) -> bool {
    normalize_base_url(value) == FOUNDRY_ANTHROPIC_BASE_URL
}

pub fn has_real_openai_api_key(api_key: Option<&str>) -> bool {
    api_key
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .is_some_and(|value| value != FOUNDRY_OPENAI_API_KEY_PLACEHOLDER)
}

pub fn has_openai_auth(api_key: Option<&str>, openai_oauth_token: Option<&str>) -> bool {
    has_real_openai_api_key(api_key)
        || openai_oauth_token
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .is_some()
}

pub fn resolve_openai_api_key(
    api_key: Option<String>,
    base_url: &str,
    openai_oauth_token: Option<String>,
) -> Option<String> {
    let normalized = api_key
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string);
    let real_key = normalized.filter(|value| value != FOUNDRY_OPENAI_API_KEY_PLACEHOLDER);
    if real_key.is_some() {
        return real_key;
    }
    let token = openai_oauth_token
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string);
    if token.is_some() {
        return token;
    }
    if is_foundry_openai_base_url(base_url) {
        return Some(FOUNDRY_OPENAI_API_KEY_PLACEHOLDER.to_string());
    }
    None
}

pub fn resolve_anthropic_api_key(api_key: Option<String>, base_url: &str) -> Option<String> {
    let normalized = api_key
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string);
    if normalized.as_deref() == Some(FOUNDRY_ANTHROPIC_API_KEY_PLACEHOLDER)
        && !is_foundry_anthropic_base_url(base_url)
    {
        return None;
    }
    if normalized.is_some() {
        return normalized;
    }
    if is_foundry_anthropic_base_url(base_url) {
        return Some(FOUNDRY_ANTHROPIC_API_KEY_PLACEHOLDER.to_string());
    }
    None
}

pub fn strip_foundry_model_prefix(model: &str) -> String {
    let trimmed = model.trim();
    let lower = trimmed.to_lowercase();
    if lower.starts_with(AZURE_FOUNDRY_MODEL_PREFIX) {
        return trimmed[AZURE_FOUNDRY_MODEL_PREFIX.len()..].to_string();
    }
    if lower.starts_with(ANTHROPIC_FOUNDRY_MODEL_PREFIX) {
        return trimmed[ANTHROPIC_FOUNDRY_MODEL_PREFIX.len()..].to_string();
    }
    trimmed.to_string()
}

/// Central configuration for the OpenPlanter agent.
///
/// Mirrors the Python `AgentConfig` dataclass field-for-field.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentConfig {
    pub workspace: PathBuf,
    pub provider: String,
    pub model: String,
    pub reasoning_effort: Option<String>,

    // Base URLs
    pub base_url: String,
    pub openai_base_url: String,
    pub anthropic_base_url: String,
    pub openrouter_base_url: String,
    pub cerebras_base_url: String,
    pub zai_plan: String,
    pub zai_paygo_base_url: String,
    pub zai_coding_base_url: String,
    pub zai_base_url: String,
    pub ollama_base_url: String,
    pub exa_base_url: String,
    pub firecrawl_base_url: String,
    pub brave_base_url: String,
    pub tavily_base_url: String,

    // API keys
    pub api_key: Option<String>,
    pub openai_api_key: Option<String>,
    pub openai_oauth_token: Option<String>,
    pub anthropic_api_key: Option<String>,
    pub openrouter_api_key: Option<String>,
    pub cerebras_api_key: Option<String>,
    pub zai_api_key: Option<String>,
    pub exa_api_key: Option<String>,
    pub firecrawl_api_key: Option<String>,
    pub brave_api_key: Option<String>,
    pub tavily_api_key: Option<String>,
    pub web_search_provider: String,
    pub voyage_api_key: Option<String>,

    // Limits
    pub max_depth: i64,
    pub max_steps_per_call: i64,
    pub max_observation_chars: i64,
    pub command_timeout_sec: i64,
    pub shell: String,
    pub max_files_listed: i64,
    pub max_file_chars: i64,
    pub max_search_hits: i64,
    pub max_shell_output_chars: i64,
    pub session_root_dir: String,
    pub max_persisted_observations: i64,
    pub max_solve_seconds: i64,
    pub rate_limit_max_retries: i64,
    pub rate_limit_backoff_base_sec: f64,
    pub rate_limit_backoff_max_sec: f64,
    pub rate_limit_retry_after_cap_sec: f64,
    pub zai_stream_max_retries: i64,
    pub recursive: bool,
    pub min_subtask_depth: i64,
    pub acceptance_criteria: bool,
    pub max_plan_chars: i64,
    pub max_turn_summaries: i64,
    pub demo: bool,
}

impl Default for AgentConfig {
    fn default() -> Self {
        Self {
            workspace: PathBuf::from("."),
            provider: "auto".into(),
            model: "anthropic-foundry/claude-opus-4-6".into(),
            reasoning_effort: Some("high".into()),
            base_url: FOUNDRY_OPENAI_BASE_URL.into(),
            openai_base_url: FOUNDRY_OPENAI_BASE_URL.into(),
            anthropic_base_url: FOUNDRY_ANTHROPIC_BASE_URL.into(),
            openrouter_base_url: "https://openrouter.ai/api/v1".into(),
            cerebras_base_url: "https://api.cerebras.ai/v1".into(),
            zai_plan: "paygo".into(),
            zai_paygo_base_url: ZAI_PAYGO_BASE_URL.into(),
            zai_coding_base_url: ZAI_CODING_BASE_URL.into(),
            zai_base_url: ZAI_PAYGO_BASE_URL.into(),
            ollama_base_url: "http://localhost:11434/v1".into(),
            exa_base_url: "https://api.exa.ai".into(),
            firecrawl_base_url: "https://api.firecrawl.dev/v1".into(),
            brave_base_url: BRAVE_BASE_URL.into(),
            tavily_base_url: TAVILY_BASE_URL.into(),
            api_key: Some(FOUNDRY_OPENAI_API_KEY_PLACEHOLDER.into()),
            openai_api_key: Some(FOUNDRY_OPENAI_API_KEY_PLACEHOLDER.into()),
            openai_oauth_token: None,
            anthropic_api_key: Some(FOUNDRY_ANTHROPIC_API_KEY_PLACEHOLDER.into()),
            openrouter_api_key: None,
            cerebras_api_key: None,
            zai_api_key: None,
            exa_api_key: None,
            firecrawl_api_key: None,
            brave_api_key: None,
            tavily_api_key: None,
            web_search_provider: "exa".into(),
            voyage_api_key: None,
            max_depth: 4,
            max_steps_per_call: 100,
            max_observation_chars: 6000,
            command_timeout_sec: 45,
            shell: "/bin/sh".into(),
            max_files_listed: 400,
            max_file_chars: 20000,
            max_search_hits: 200,
            max_shell_output_chars: 16000,
            session_root_dir: ".openplanter".into(),
            max_persisted_observations: 400,
            max_solve_seconds: 0,
            rate_limit_max_retries: 12,
            rate_limit_backoff_base_sec: 1.0,
            rate_limit_backoff_max_sec: 60.0,
            rate_limit_retry_after_cap_sec: 120.0,
            zai_stream_max_retries: 10,
            recursive: true,
            min_subtask_depth: 0,
            acceptance_criteria: true,
            max_plan_chars: 40_000,
            max_turn_summaries: 50,
            demo: false,
        }
    }
}

impl AgentConfig {
    /// Build configuration from environment variables, mirroring `AgentConfig.from_env()`.
    pub fn from_env(workspace: impl AsRef<Path>) -> Self {
        let ws = dunce_canonicalize(workspace.as_ref());

        let openai_api_key =
            env_opt("OPENPLANTER_OPENAI_API_KEY").or_else(|| env_opt("OPENAI_API_KEY"));
        let openai_oauth_token =
            env_opt("OPENPLANTER_OPENAI_OAUTH_TOKEN").or_else(|| env_opt("OPENAI_OAUTH_TOKEN"));

        let anthropic_api_key =
            env_opt("OPENPLANTER_ANTHROPIC_API_KEY").or_else(|| env_opt("ANTHROPIC_API_KEY"));

        let openrouter_api_key =
            env_opt("OPENPLANTER_OPENROUTER_API_KEY").or_else(|| env_opt("OPENROUTER_API_KEY"));

        let cerebras_api_key =
            env_opt("OPENPLANTER_CEREBRAS_API_KEY").or_else(|| env_opt("CEREBRAS_API_KEY"));

        let zai_api_key = env_opt("OPENPLANTER_ZAI_API_KEY").or_else(|| env_opt("ZAI_API_KEY"));

        let exa_api_key = env_opt("OPENPLANTER_EXA_API_KEY").or_else(|| env_opt("EXA_API_KEY"));

        let firecrawl_api_key =
            env_opt("OPENPLANTER_FIRECRAWL_API_KEY").or_else(|| env_opt("FIRECRAWL_API_KEY"));
        let brave_api_key =
            env_opt("OPENPLANTER_BRAVE_API_KEY").or_else(|| env_opt("BRAVE_API_KEY"));
        let tavily_api_key =
            env_opt("OPENPLANTER_TAVILY_API_KEY").or_else(|| env_opt("TAVILY_API_KEY"));

        let voyage_api_key =
            env_opt("OPENPLANTER_VOYAGE_API_KEY").or_else(|| env_opt("VOYAGE_API_KEY"));

        let openai_base_url = env_opt("OPENPLANTER_OPENAI_BASE_URL")
            .or_else(|| env_opt("OPENPLANTER_BASE_URL"))
            .unwrap_or_else(|| FOUNDRY_OPENAI_BASE_URL.into());
        let anthropic_base_url =
            env_or("OPENPLANTER_ANTHROPIC_BASE_URL", FOUNDRY_ANTHROPIC_BASE_URL);
        let openai_api_key =
            resolve_openai_api_key(openai_api_key, &openai_base_url, openai_oauth_token.clone());
        let anthropic_api_key = resolve_anthropic_api_key(anthropic_api_key, &anthropic_base_url);

        let reasoning_effort_raw = env_or("OPENPLANTER_REASONING_EFFORT", "high")
            .trim()
            .to_lowercase();
        let reasoning_effort = if reasoning_effort_raw.is_empty() {
            None
        } else {
            Some(reasoning_effort_raw)
        };

        let provider_raw = env_or("OPENPLANTER_PROVIDER", "auto").trim().to_lowercase();
        let provider = if provider_raw.is_empty() {
            "auto".into()
        } else {
            provider_raw
        };

        let zai_plan = normalize_zai_plan(env_opt("OPENPLANTER_ZAI_PLAN").as_deref());
        let zai_paygo_base_url = env_or("OPENPLANTER_ZAI_PAYGO_BASE_URL", ZAI_PAYGO_BASE_URL);
        let zai_coding_base_url = env_or("OPENPLANTER_ZAI_CODING_BASE_URL", ZAI_CODING_BASE_URL);
        let zai_base_url = env_opt("OPENPLANTER_ZAI_BASE_URL").unwrap_or_else(|| {
            resolve_zai_base_url(&zai_plan, &zai_paygo_base_url, &zai_coding_base_url)
        });
        let web_search_provider =
            normalize_web_search_provider(env_opt("OPENPLANTER_WEB_SEARCH_PROVIDER").as_deref());

        Self {
            workspace: ws,
            provider,
            model: env_or("OPENPLANTER_MODEL", PROVIDER_DEFAULT_MODELS["anthropic"]),
            reasoning_effort,
            base_url: openai_base_url.clone(),
            api_key: openai_api_key.clone(),
            openai_base_url,
            anthropic_base_url,
            openrouter_base_url: env_or(
                "OPENPLANTER_OPENROUTER_BASE_URL",
                "https://openrouter.ai/api/v1",
            ),
            cerebras_base_url: env_or(
                "OPENPLANTER_CEREBRAS_BASE_URL",
                "https://api.cerebras.ai/v1",
            ),
            zai_plan,
            zai_paygo_base_url,
            zai_coding_base_url,
            zai_base_url,
            ollama_base_url: env_or("OPENPLANTER_OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            exa_base_url: env_or("OPENPLANTER_EXA_BASE_URL", "https://api.exa.ai"),
            firecrawl_base_url: env_or(
                "OPENPLANTER_FIRECRAWL_BASE_URL",
                "https://api.firecrawl.dev/v1",
            ),
            brave_base_url: env_or("OPENPLANTER_BRAVE_BASE_URL", BRAVE_BASE_URL),
            tavily_base_url: env_or("OPENPLANTER_TAVILY_BASE_URL", TAVILY_BASE_URL),
            openai_api_key,
            openai_oauth_token,
            anthropic_api_key,
            openrouter_api_key,
            cerebras_api_key,
            zai_api_key,
            exa_api_key,
            firecrawl_api_key,
            brave_api_key,
            tavily_api_key,
            web_search_provider,
            voyage_api_key,
            max_depth: env_int("OPENPLANTER_MAX_DEPTH", 4),
            max_steps_per_call: env_int("OPENPLANTER_MAX_STEPS", 100),
            max_observation_chars: env_int("OPENPLANTER_MAX_OBS_CHARS", 6000),
            command_timeout_sec: env_int("OPENPLANTER_CMD_TIMEOUT", 45),
            shell: env_or("OPENPLANTER_SHELL", "/bin/sh"),
            max_files_listed: env_int("OPENPLANTER_MAX_FILES", 400),
            max_file_chars: env_int("OPENPLANTER_MAX_FILE_CHARS", 20000),
            max_search_hits: env_int("OPENPLANTER_MAX_SEARCH_HITS", 200),
            max_shell_output_chars: env_int("OPENPLANTER_MAX_SHELL_CHARS", 16000),
            session_root_dir: env_or("OPENPLANTER_SESSION_DIR", ".openplanter"),
            max_persisted_observations: env_int("OPENPLANTER_MAX_PERSISTED_OBS", 400),
            max_solve_seconds: env_int("OPENPLANTER_MAX_SOLVE_SECONDS", 0),
            rate_limit_max_retries: env_int("OPENPLANTER_RATE_LIMIT_MAX_RETRIES", 12),
            rate_limit_backoff_base_sec: env_float("OPENPLANTER_RATE_LIMIT_BACKOFF_BASE_SEC", 1.0),
            rate_limit_backoff_max_sec: env_float("OPENPLANTER_RATE_LIMIT_BACKOFF_MAX_SEC", 60.0),
            rate_limit_retry_after_cap_sec: env_float(
                "OPENPLANTER_RATE_LIMIT_RETRY_AFTER_CAP_SEC",
                120.0,
            ),
            zai_stream_max_retries: env_int("OPENPLANTER_ZAI_STREAM_MAX_RETRIES", 10),
            recursive: env_bool("OPENPLANTER_RECURSIVE", true),
            min_subtask_depth: env_int("OPENPLANTER_MIN_SUBTASK_DEPTH", 0),
            acceptance_criteria: env_bool("OPENPLANTER_ACCEPTANCE_CRITERIA", true),
            max_plan_chars: env_int("OPENPLANTER_MAX_PLAN_CHARS", 40_000),
            max_turn_summaries: env_int("OPENPLANTER_MAX_TURN_SUMMARIES", 50),
            demo: env_bool("OPENPLANTER_DEMO", false),
        }
    }
}

/// Canonicalize a path, expanding `~` and resolving symlinks.
/// Falls back to the original path on error.
fn dunce_canonicalize(p: &Path) -> PathBuf {
    let expanded = if p.starts_with("~") {
        if let Some(home) = dirs_home() {
            home.join(p.strip_prefix("~").unwrap_or(p))
        } else {
            p.to_path_buf()
        }
    } else {
        p.to_path_buf()
    };
    std::fs::canonicalize(&expanded).unwrap_or(expanded)
}

fn dirs_home() -> Option<PathBuf> {
    env::var("HOME")
        .ok()
        .map(PathBuf::from)
        .or_else(|| env::var("USERPROFILE").ok().map(PathBuf::from))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config() {
        let cfg = AgentConfig::default();
        assert_eq!(cfg.provider, "auto");
        assert_eq!(cfg.model, "anthropic-foundry/claude-opus-4-6");
        assert_eq!(cfg.reasoning_effort, Some("high".into()));
        assert_eq!(cfg.openai_base_url, FOUNDRY_OPENAI_BASE_URL);
        assert_eq!(cfg.anthropic_base_url, FOUNDRY_ANTHROPIC_BASE_URL);
        assert_eq!(
            cfg.openai_api_key.as_deref(),
            Some(FOUNDRY_OPENAI_API_KEY_PLACEHOLDER)
        );
        assert_eq!(
            cfg.anthropic_api_key.as_deref(),
            Some(FOUNDRY_ANTHROPIC_API_KEY_PLACEHOLDER)
        );
        assert_eq!(cfg.max_depth, 4);
        assert_eq!(cfg.max_steps_per_call, 100);
        assert_eq!(cfg.zai_plan, "paygo");
        assert_eq!(cfg.zai_base_url, ZAI_PAYGO_BASE_URL);
        assert_eq!(cfg.web_search_provider, "exa");
        assert_eq!(cfg.brave_base_url, BRAVE_BASE_URL);
        assert!(cfg.brave_api_key.is_none());
        assert_eq!(cfg.tavily_base_url, TAVILY_BASE_URL);
        assert!(cfg.tavily_api_key.is_none());
        assert_eq!(cfg.rate_limit_max_retries, 12);
        assert_eq!(cfg.rate_limit_backoff_base_sec, 1.0);
        assert_eq!(cfg.rate_limit_backoff_max_sec, 60.0);
        assert_eq!(cfg.rate_limit_retry_after_cap_sec, 120.0);
        assert!(cfg.recursive);
        assert!(cfg.acceptance_criteria);
        assert!(!cfg.demo);
    }

    #[test]
    fn test_provider_default_models() {
        assert_eq!(
            PROVIDER_DEFAULT_MODELS.get("openai"),
            Some(&"azure-foundry/gpt-5.4")
        );
        assert_eq!(
            PROVIDER_DEFAULT_MODELS.get("anthropic"),
            Some(&"anthropic-foundry/claude-opus-4-6")
        );
        assert_eq!(
            PROVIDER_DEFAULT_MODELS.get("openrouter"),
            Some(&"anthropic/claude-sonnet-4-5")
        );
        assert_eq!(
            PROVIDER_DEFAULT_MODELS.get("cerebras"),
            Some(&"qwen-3-235b-a22b-instruct-2507")
        );
        assert_eq!(PROVIDER_DEFAULT_MODELS.get("zai"), Some(&"glm-5"));
        assert_eq!(PROVIDER_DEFAULT_MODELS.get("ollama"), Some(&"llama3.2"));
    }

    /// Combined env-based test to avoid race conditions from parallel test execution.
    /// Tests both default and custom env var loading in sequence.
    #[test]
    fn test_from_env_defaults_and_custom() {
        let keys = [
            "OPENPLANTER_PROVIDER",
            "OPENPLANTER_MODEL",
            "OPENPLANTER_REASONING_EFFORT",
            "OPENPLANTER_OPENAI_API_KEY",
            "OPENAI_API_KEY",
            "OPENPLANTER_OPENAI_OAUTH_TOKEN",
            "OPENAI_OAUTH_TOKEN",
            "OPENPLANTER_OPENAI_BASE_URL",
            "OPENPLANTER_BASE_URL",
            "OPENPLANTER_ANTHROPIC_API_KEY",
            "ANTHROPIC_API_KEY",
            "OPENPLANTER_ANTHROPIC_BASE_URL",
            "OPENPLANTER_ZAI_API_KEY",
            "ZAI_API_KEY",
            "OPENPLANTER_MAX_DEPTH",
            "OPENPLANTER_RECURSIVE",
            "OPENPLANTER_DEMO",
            "OPENPLANTER_WEB_SEARCH_PROVIDER",
            "OPENPLANTER_BRAVE_API_KEY",
            "BRAVE_API_KEY",
            "OPENPLANTER_BRAVE_BASE_URL",
            "OPENPLANTER_TAVILY_API_KEY",
            "TAVILY_API_KEY",
            "OPENPLANTER_TAVILY_BASE_URL",
            "OPENPLANTER_ZAI_PLAN",
            "OPENPLANTER_ZAI_BASE_URL",
            "OPENPLANTER_RATE_LIMIT_MAX_RETRIES",
            "OPENPLANTER_RATE_LIMIT_BACKOFF_BASE_SEC",
            "OPENPLANTER_RATE_LIMIT_BACKOFF_MAX_SEC",
            "OPENPLANTER_RATE_LIMIT_RETRY_AFTER_CAP_SEC",
            "OPENPLANTER_ZAI_STREAM_MAX_RETRIES",
        ];
        // Save original values
        let saved: Vec<_> = keys.iter().map(|k| (*k, env::var(k).ok())).collect();

        // SAFETY: test-only; combined into one test to avoid parallel env mutation
        unsafe {
            // --- Phase 1: test defaults (all cleared) ---
            for k in &keys {
                env::remove_var(k);
            }
        }

        let cfg = AgentConfig::from_env("/tmp");
        assert_eq!(cfg.provider, "auto");
        assert_eq!(cfg.model, "anthropic-foundry/claude-opus-4-6");
        assert_eq!(cfg.reasoning_effort, Some("high".into()));
        assert_eq!(cfg.max_depth, 4);
        assert!(cfg.recursive);
        assert!(!cfg.demo);
        assert_eq!(
            cfg.openai_api_key.as_deref(),
            Some(FOUNDRY_OPENAI_API_KEY_PLACEHOLDER)
        );
        assert_eq!(
            cfg.anthropic_api_key.as_deref(),
            Some(FOUNDRY_ANTHROPIC_API_KEY_PLACEHOLDER)
        );
        assert!(cfg.zai_api_key.is_none());
        assert!(cfg.brave_api_key.is_none());
        assert!(cfg.tavily_api_key.is_none());
        assert_eq!(cfg.openai_base_url, FOUNDRY_OPENAI_BASE_URL);
        assert_eq!(cfg.anthropic_base_url, FOUNDRY_ANTHROPIC_BASE_URL);
        assert_eq!(cfg.web_search_provider, "exa");
        assert_eq!(cfg.rate_limit_max_retries, 12);
        assert_eq!(cfg.rate_limit_backoff_base_sec, 1.0);
        assert_eq!(cfg.rate_limit_backoff_max_sec, 60.0);
        assert_eq!(cfg.rate_limit_retry_after_cap_sec, 120.0);

        unsafe {
            // --- Phase 2: test custom values ---
            env::set_var("OPENPLANTER_PROVIDER", "openai");
            env::set_var("OPENPLANTER_MODEL", "azure-foundry/gpt-5.4");
            env::set_var("OPENPLANTER_REASONING_EFFORT", "low");
            env::set_var("OPENPLANTER_MAX_DEPTH", "8");
            env::set_var("OPENPLANTER_RECURSIVE", "false");
            env::set_var("OPENPLANTER_DEMO", "true");
            env::set_var("OPENAI_API_KEY", "sk-test123");
            env::set_var("ZAI_API_KEY", "zai-test123");
            env::set_var("BRAVE_API_KEY", "brave-test123");
            env::set_var("TAVILY_API_KEY", "tavily-test123");
            env::set_var("OPENPLANTER_WEB_SEARCH_PROVIDER", "tavily");
            env::set_var("OPENPLANTER_RATE_LIMIT_MAX_RETRIES", "5");
            env::set_var("OPENPLANTER_RATE_LIMIT_BACKOFF_BASE_SEC", "2.5");
            env::set_var("OPENPLANTER_RATE_LIMIT_BACKOFF_MAX_SEC", "30.0");
            env::set_var("OPENPLANTER_RATE_LIMIT_RETRY_AFTER_CAP_SEC", "90.0");
            env::set_var("OPENPLANTER_ZAI_PLAN", "coding");
            env::set_var("OPENPLANTER_ZAI_STREAM_MAX_RETRIES", "7");
            env::set_var("OPENPLANTER_TAVILY_BASE_URL", "https://tavily.example");
        }

        let cfg = AgentConfig::from_env("/tmp");
        assert_eq!(cfg.provider, "openai");
        assert_eq!(cfg.model, "azure-foundry/gpt-5.4");
        assert_eq!(cfg.reasoning_effort, Some("low".into()));
        assert_eq!(cfg.max_depth, 8);
        assert!(!cfg.recursive);
        assert!(cfg.demo);
        assert_eq!(cfg.openai_api_key, Some("sk-test123".into()));
        assert_eq!(cfg.zai_api_key, Some("zai-test123".into()));
        assert_eq!(cfg.brave_api_key, Some("brave-test123".into()));
        assert_eq!(cfg.tavily_api_key, Some("tavily-test123".into()));
        assert_eq!(cfg.zai_plan, "coding");
        assert_eq!(cfg.zai_base_url, ZAI_CODING_BASE_URL);
        assert_eq!(cfg.zai_stream_max_retries, 7);
        assert_eq!(cfg.web_search_provider, "tavily");
        assert_eq!(cfg.tavily_base_url, "https://tavily.example");
        assert_eq!(cfg.rate_limit_max_retries, 5);
        assert_eq!(cfg.rate_limit_backoff_base_sec, 2.5);
        assert_eq!(cfg.rate_limit_backoff_max_sec, 30.0);
        assert_eq!(cfg.rate_limit_retry_after_cap_sec, 90.0);

        // Restore original values
        unsafe {
            env::remove_var("OPENAI_API_KEY");
            env::set_var("OPENAI_OAUTH_TOKEN", "oauth-token");
        }

        let cfg = AgentConfig::from_env("/tmp");
        assert_eq!(cfg.openai_oauth_token.as_deref(), Some("oauth-token"));
        assert_eq!(cfg.openai_api_key.as_deref(), Some("oauth-token"));
        assert_eq!(cfg.api_key.as_deref(), Some("oauth-token"));

        unsafe {
            env::set_var("OPENAI_API_KEY", "sk-test456");
        }

        let cfg = AgentConfig::from_env("/tmp");
        assert_eq!(cfg.openai_oauth_token.as_deref(), Some("oauth-token"));
        assert_eq!(cfg.openai_api_key.as_deref(), Some("sk-test456"));
        assert_eq!(cfg.api_key.as_deref(), Some("sk-test456"));

        for (k, v) in saved {
            unsafe {
                match v {
                    Some(val) => env::set_var(k, val),
                    None => env::remove_var(k),
                }
            }
        }
    }

    #[test]
    fn test_normalizers() {
        assert_eq!(normalize_zai_plan(Some("coding")), "coding");
        assert_eq!(normalize_zai_plan(Some("bad-value")), "paygo");
        assert_eq!(
            resolve_zai_base_url("coding", "https://paygo.example", "https://coding.example"),
            "https://coding.example"
        );
        assert_eq!(
            normalize_web_search_provider(Some("firecrawl")),
            "firecrawl"
        );
        assert_eq!(normalize_web_search_provider(Some("brave")), "brave");
        assert_eq!(normalize_web_search_provider(Some("tavily")), "tavily");
        assert_eq!(normalize_web_search_provider(Some("other")), "exa");
        assert!(is_foundry_openai_base_url(FOUNDRY_OPENAI_BASE_URL));
        assert!(is_foundry_anthropic_base_url(FOUNDRY_ANTHROPIC_BASE_URL));
        assert_eq!(
            resolve_openai_api_key(None, FOUNDRY_OPENAI_BASE_URL, None).as_deref(),
            Some(FOUNDRY_OPENAI_API_KEY_PLACEHOLDER)
        );
        assert_eq!(
            resolve_openai_api_key(
                Some(FOUNDRY_OPENAI_API_KEY_PLACEHOLDER.to_string()),
                FOUNDRY_OPENAI_BASE_URL,
                Some("oauth-token".to_string()),
            )
            .as_deref(),
            Some("oauth-token")
        );
        assert_eq!(
            resolve_openai_api_key(
                Some("sk-openai".to_string()),
                FOUNDRY_OPENAI_BASE_URL,
                Some("oauth-token".to_string()),
            )
            .as_deref(),
            Some("sk-openai")
        );
        assert_eq!(
            resolve_anthropic_api_key(None, FOUNDRY_ANTHROPIC_BASE_URL).as_deref(),
            Some(FOUNDRY_ANTHROPIC_API_KEY_PLACEHOLDER)
        );
        assert_eq!(
            strip_foundry_model_prefix("azure-foundry/gpt-5.4"),
            "gpt-5.4"
        );
        assert_eq!(
            strip_foundry_model_prefix("anthropic-foundry/claude-opus-4-6"),
            "claude-opus-4-6"
        );
    }
}

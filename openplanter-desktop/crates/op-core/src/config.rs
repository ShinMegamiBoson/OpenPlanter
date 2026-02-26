use std::collections::HashMap;
use std::env;
use std::path::{Path, PathBuf};
use std::sync::LazyLock;

use serde::{Deserialize, Serialize};

/// Default model for each supported provider.
pub static PROVIDER_DEFAULT_MODELS: LazyLock<HashMap<&'static str, &'static str>> =
    LazyLock::new(|| {
        HashMap::from([
            ("openai", "gpt-5.2"),
            ("anthropic", "claude-opus-4-6"),
            ("openrouter", "anthropic/claude-sonnet-4-5"),
            ("cerebras", "qwen-3-235b-a22b-instruct-2507"),
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

fn env_bool(key: &str, default: bool) -> bool {
    match env::var(key) {
        Ok(v) => matches!(v.trim().to_lowercase().as_str(), "1" | "true" | "yes"),
        Err(_) => default,
    }
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
    pub ollama_base_url: String,
    pub exa_base_url: String,

    // API keys
    pub api_key: Option<String>,
    pub openai_api_key: Option<String>,
    pub anthropic_api_key: Option<String>,
    pub openrouter_api_key: Option<String>,
    pub cerebras_api_key: Option<String>,
    pub exa_api_key: Option<String>,
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
            model: "claude-opus-4-6".into(),
            reasoning_effort: Some("high".into()),
            base_url: "https://api.openai.com/v1".into(),
            openai_base_url: "https://api.openai.com/v1".into(),
            anthropic_base_url: "https://api.anthropic.com/v1".into(),
            openrouter_base_url: "https://openrouter.ai/api/v1".into(),
            cerebras_base_url: "https://api.cerebras.ai/v1".into(),
            ollama_base_url: "http://localhost:11434/v1".into(),
            exa_base_url: "https://api.exa.ai".into(),
            api_key: None,
            openai_api_key: None,
            anthropic_api_key: None,
            openrouter_api_key: None,
            cerebras_api_key: None,
            exa_api_key: None,
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

        let openai_api_key = env_opt("OPENPLANTER_OPENAI_API_KEY")
            .or_else(|| env_opt("OPENAI_API_KEY"));

        let anthropic_api_key = env_opt("OPENPLANTER_ANTHROPIC_API_KEY")
            .or_else(|| env_opt("ANTHROPIC_API_KEY"));

        let openrouter_api_key = env_opt("OPENPLANTER_OPENROUTER_API_KEY")
            .or_else(|| env_opt("OPENROUTER_API_KEY"));

        let cerebras_api_key = env_opt("OPENPLANTER_CEREBRAS_API_KEY")
            .or_else(|| env_opt("CEREBRAS_API_KEY"));

        let exa_api_key = env_opt("OPENPLANTER_EXA_API_KEY")
            .or_else(|| env_opt("EXA_API_KEY"));

        let voyage_api_key = env_opt("OPENPLANTER_VOYAGE_API_KEY")
            .or_else(|| env_opt("VOYAGE_API_KEY"));

        let openai_base_url = env_opt("OPENPLANTER_OPENAI_BASE_URL")
            .or_else(|| env_opt("OPENPLANTER_BASE_URL"))
            .unwrap_or_else(|| "https://api.openai.com/v1".into());

        let reasoning_effort_raw = env_or("OPENPLANTER_REASONING_EFFORT", "high")
            .trim()
            .to_lowercase();
        let reasoning_effort = if reasoning_effort_raw.is_empty() {
            None
        } else {
            Some(reasoning_effort_raw)
        };

        let provider_raw = env_or("OPENPLANTER_PROVIDER", "auto")
            .trim()
            .to_lowercase();
        let provider = if provider_raw.is_empty() {
            "auto".into()
        } else {
            provider_raw
        };

        Self {
            workspace: ws,
            provider,
            model: env_or("OPENPLANTER_MODEL", "claude-opus-4-6"),
            reasoning_effort,
            base_url: openai_base_url.clone(),
            api_key: openai_api_key.clone(),
            openai_base_url,
            anthropic_base_url: env_or(
                "OPENPLANTER_ANTHROPIC_BASE_URL",
                "https://api.anthropic.com/v1",
            ),
            openrouter_base_url: env_or(
                "OPENPLANTER_OPENROUTER_BASE_URL",
                "https://openrouter.ai/api/v1",
            ),
            cerebras_base_url: env_or(
                "OPENPLANTER_CEREBRAS_BASE_URL",
                "https://api.cerebras.ai/v1",
            ),
            ollama_base_url: env_or(
                "OPENPLANTER_OLLAMA_BASE_URL",
                "http://localhost:11434/v1",
            ),
            exa_base_url: env_or("OPENPLANTER_EXA_BASE_URL", "https://api.exa.ai"),
            openai_api_key,
            anthropic_api_key,
            openrouter_api_key,
            cerebras_api_key,
            exa_api_key,
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
        assert_eq!(cfg.model, "claude-opus-4-6");
        assert_eq!(cfg.reasoning_effort, Some("high".into()));
        assert_eq!(cfg.max_depth, 4);
        assert_eq!(cfg.max_steps_per_call, 100);
        assert!(cfg.recursive);
        assert!(cfg.acceptance_criteria);
        assert!(!cfg.demo);
    }

    #[test]
    fn test_provider_default_models() {
        assert_eq!(PROVIDER_DEFAULT_MODELS.get("openai"), Some(&"gpt-5.2"));
        assert_eq!(
            PROVIDER_DEFAULT_MODELS.get("anthropic"),
            Some(&"claude-opus-4-6")
        );
        assert_eq!(
            PROVIDER_DEFAULT_MODELS.get("openrouter"),
            Some(&"anthropic/claude-sonnet-4-5")
        );
        assert_eq!(
            PROVIDER_DEFAULT_MODELS.get("cerebras"),
            Some(&"qwen-3-235b-a22b-instruct-2507")
        );
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
            "OPENPLANTER_ANTHROPIC_API_KEY",
            "ANTHROPIC_API_KEY",
            "OPENPLANTER_MAX_DEPTH",
            "OPENPLANTER_RECURSIVE",
            "OPENPLANTER_DEMO",
        ];
        // Save original values
        let saved: Vec<_> = keys
            .iter()
            .map(|k| (*k, env::var(k).ok()))
            .collect();

        // SAFETY: test-only; combined into one test to avoid parallel env mutation
        unsafe {
            // --- Phase 1: test defaults (all cleared) ---
            for k in &keys {
                env::remove_var(k);
            }
        }

        let cfg = AgentConfig::from_env("/tmp");
        assert_eq!(cfg.provider, "auto");
        assert_eq!(cfg.model, "claude-opus-4-6");
        assert_eq!(cfg.reasoning_effort, Some("high".into()));
        assert_eq!(cfg.max_depth, 4);
        assert!(cfg.recursive);
        assert!(!cfg.demo);
        assert!(cfg.openai_api_key.is_none());
        assert!(cfg.anthropic_api_key.is_none());

        unsafe {
            // --- Phase 2: test custom values ---
            env::set_var("OPENPLANTER_PROVIDER", "openai");
            env::set_var("OPENPLANTER_MODEL", "gpt-5.2");
            env::set_var("OPENPLANTER_REASONING_EFFORT", "low");
            env::set_var("OPENPLANTER_MAX_DEPTH", "8");
            env::set_var("OPENPLANTER_RECURSIVE", "false");
            env::set_var("OPENPLANTER_DEMO", "true");
            env::set_var("OPENAI_API_KEY", "sk-test123");
        }

        let cfg = AgentConfig::from_env("/tmp");
        assert_eq!(cfg.provider, "openai");
        assert_eq!(cfg.model, "gpt-5.2");
        assert_eq!(cfg.reasoning_effort, Some("low".into()));
        assert_eq!(cfg.max_depth, 8);
        assert!(!cfg.recursive);
        assert!(cfg.demo);
        assert_eq!(cfg.openai_api_key, Some("sk-test123".into()));

        // Restore original values
        for (k, v) in saved {
            unsafe {
                match v {
                    Some(val) => env::set_var(k, val),
                    None => env::remove_var(k),
                }
            }
        }
    }
}

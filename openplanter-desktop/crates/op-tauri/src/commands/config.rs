use crate::state::AppState;
use op_core::config::{normalize_web_search_provider, normalize_zai_plan, resolve_zai_base_url};
use op_core::credentials::credentials_from_env;
use op_core::events::{ConfigView, ModelInfo, PartialConfig};
use op_core::settings::{PersistentSettings, SettingsStore};
use std::collections::HashMap;
use tauri::State;

fn make_config_view(cfg: &op_core::config::AgentConfig, session_id: Option<String>) -> ConfigView {
    ConfigView {
        provider: cfg.provider.clone(),
        model: cfg.model.clone(),
        reasoning_effort: cfg.reasoning_effort.clone(),
        zai_plan: cfg.zai_plan.clone(),
        web_search_provider: cfg.web_search_provider.clone(),
        workspace: cfg.workspace.display().to_string(),
        session_id,
        recursive: cfg.recursive,
        max_depth: cfg.max_depth,
        max_steps_per_call: cfg.max_steps_per_call,
        demo: cfg.demo,
    }
}

fn merge_settings(
    existing: PersistentSettings,
    incoming: PersistentSettings,
) -> PersistentSettings {
    PersistentSettings {
        default_model: incoming.default_model.or(existing.default_model),
        default_reasoning_effort: incoming
            .default_reasoning_effort
            .or(existing.default_reasoning_effort),
        default_model_openai: incoming
            .default_model_openai
            .or(existing.default_model_openai),
        default_model_anthropic: incoming
            .default_model_anthropic
            .or(existing.default_model_anthropic),
        default_model_openrouter: incoming
            .default_model_openrouter
            .or(existing.default_model_openrouter),
        default_model_cerebras: incoming
            .default_model_cerebras
            .or(existing.default_model_cerebras),
        default_model_zai: incoming.default_model_zai.or(existing.default_model_zai),
        default_model_ollama: incoming
            .default_model_ollama
            .or(existing.default_model_ollama),
        zai_plan: incoming.zai_plan.or(existing.zai_plan),
        web_search_provider: incoming
            .web_search_provider
            .or(existing.web_search_provider),
    }
}

/// Get the current configuration.
#[tauri::command]
pub async fn get_config(state: State<'_, AppState>) -> Result<ConfigView, String> {
    let cfg = state.config.lock().await;
    let session_id = state.session_id.lock().await;
    Ok(make_config_view(&cfg, session_id.clone()))
}

/// Update configuration fields.
#[tauri::command]
pub async fn update_config(
    partial: PartialConfig,
    state: State<'_, AppState>,
) -> Result<ConfigView, String> {
    let mut cfg = state.config.lock().await;
    if let Some(provider) = partial.provider {
        cfg.provider = provider;
    }
    if let Some(model) = partial.model {
        cfg.model = model;
    }
    if let Some(effort) = partial.reasoning_effort {
        cfg.reasoning_effort = if effort.is_empty() {
            None
        } else {
            Some(effort)
        };
    }
    if let Some(plan) = partial.zai_plan {
        cfg.zai_plan = normalize_zai_plan(Some(&plan));
        cfg.zai_base_url = resolve_zai_base_url(
            &cfg.zai_plan,
            &cfg.zai_paygo_base_url,
            &cfg.zai_coding_base_url,
        );
    }
    if let Some(provider) = partial.web_search_provider {
        cfg.web_search_provider = normalize_web_search_provider(Some(&provider));
    }
    let session_id = state.session_id.lock().await;
    Ok(make_config_view(&cfg, session_id.clone()))
}

/// Known models per provider for listing.
fn known_models_for_provider(provider: &str) -> Vec<ModelInfo> {
    let models: Vec<(&str, &str)> = match provider {
        "openai" => vec![
            ("azure-foundry/gpt-5.3-codex", "GPT-5.3 Codex (Foundry)"),
            ("azure-foundry/Kimi-K2.5", "Kimi K2.5 (Foundry)"),
        ],
        "anthropic" => vec![
            ("anthropic-foundry/claude-opus-4-6", "Claude Opus 4.6 (Foundry)"),
            (
                "anthropic-foundry/claude-sonnet-4-6",
                "Claude Sonnet 4.6 (Foundry)",
            ),
            ("anthropic-foundry/claude-haiku-4-5", "Claude Haiku 4.5 (Foundry)"),
        ],
        "openrouter" => vec![
            ("anthropic/claude-sonnet-4-5", "Claude Sonnet 4.5 (OR)"),
            ("anthropic/claude-opus-4-6", "Claude Opus 4.6 (OR)"),
            ("openai/gpt-5.2", "GPT-5.2 (OR)"),
        ],
        "cerebras" => vec![
            ("qwen-3-235b-a22b-instruct-2507", "Qwen-3 235B"),
            ("llama-4-scout-17b-16e-instruct", "Llama-4 Scout"),
        ],
        "zai" => vec![
            ("glm-5", "GLM-5"),
            ("glm-4.6", "GLM-4.6"),
            ("zai-glm-4.6", "Z.AI GLM 4.6"),
        ],
        "ollama" => vec![
            ("llama3.2", "Llama 3.2"),
            ("mistral", "Mistral"),
            ("gemma", "Gemma"),
            ("phi", "Phi"),
            ("deepseek", "DeepSeek"),
            ("qwen2", "Qwen 2"),
        ],
        _ => vec![],
    };

    models
        .into_iter()
        .map(|(id, name)| ModelInfo {
            id: id.to_string(),
            name: Some(name.to_string()),
            provider: provider.to_string(),
        })
        .collect()
}

/// List available models for a provider.
#[tauri::command]
pub async fn list_models(
    provider: String,
    _state: State<'_, AppState>,
) -> Result<Vec<ModelInfo>, String> {
    if provider == "all" {
        let mut all = Vec::new();
        for p in &[
            "openai",
            "anthropic",
            "openrouter",
            "cerebras",
            "zai",
            "ollama",
        ] {
            all.extend(known_models_for_provider(p));
        }
        Ok(all)
    } else {
        Ok(known_models_for_provider(&provider))
    }
}

/// Save persistent settings to disk.
#[tauri::command]
pub async fn save_settings(
    settings: PersistentSettings,
    state: State<'_, AppState>,
) -> Result<(), String> {
    let cfg = state.config.lock().await;
    let store = SettingsStore::new(&cfg.workspace, &cfg.session_root_dir);
    let merged = merge_settings(store.load(), settings);
    store.save(&merged).map_err(|e| e.to_string())
}

/// Build credential status from config: which providers/services have API keys configured.
pub fn build_credential_status(cfg: &op_core::config::AgentConfig) -> HashMap<String, bool> {
    let mut status = HashMap::new();
    status.insert("openai".to_string(), cfg.openai_api_key.is_some());
    status.insert("anthropic".to_string(), cfg.anthropic_api_key.is_some());
    status.insert("openrouter".to_string(), cfg.openrouter_api_key.is_some());
    status.insert("cerebras".to_string(), cfg.cerebras_api_key.is_some());
    status.insert("zai".to_string(), cfg.zai_api_key.is_some());
    status.insert("ollama".to_string(), true); // Ollama never needs a key
    status.insert("exa".to_string(), cfg.exa_api_key.is_some());
    status.insert("firecrawl".to_string(), cfg.firecrawl_api_key.is_some());
    status
}

/// Get credential status: which providers/services have API keys configured.
#[tauri::command]
pub async fn get_credentials_status(
    state: State<'_, AppState>,
) -> Result<HashMap<String, bool>, String> {
    let cfg = state.config.lock().await;
    let env_creds = credentials_from_env();

    let mut status = HashMap::new();
    status.insert(
        "openai".to_string(),
        cfg.openai_api_key.is_some() || env_creds.openai_api_key.is_some(),
    );
    status.insert(
        "anthropic".to_string(),
        cfg.anthropic_api_key.is_some() || env_creds.anthropic_api_key.is_some(),
    );
    status.insert(
        "openrouter".to_string(),
        cfg.openrouter_api_key.is_some() || env_creds.openrouter_api_key.is_some(),
    );
    status.insert(
        "cerebras".to_string(),
        cfg.cerebras_api_key.is_some() || env_creds.cerebras_api_key.is_some(),
    );
    status.insert(
        "zai".to_string(),
        cfg.zai_api_key.is_some() || env_creds.zai_api_key.is_some(),
    );
    status.insert("ollama".to_string(), true); // Ollama never needs a key
    status.insert(
        "exa".to_string(),
        cfg.exa_api_key.is_some() || env_creds.exa_api_key.is_some(),
    );
    status.insert(
        "firecrawl".to_string(),
        cfg.firecrawl_api_key.is_some() || env_creds.firecrawl_api_key.is_some(),
    );
    Ok(status)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashSet;

    // ── known_models_for_provider ──

    #[test]
    fn test_openai_models_nonempty() {
        let models = known_models_for_provider("openai");
        assert!(!models.is_empty(), "openai should have known models");
    }

    #[test]
    fn test_anthropic_models_nonempty() {
        let models = known_models_for_provider("anthropic");
        assert!(!models.is_empty(), "anthropic should have known models");
    }

    #[test]
    fn test_openrouter_models_nonempty() {
        let models = known_models_for_provider("openrouter");
        assert!(!models.is_empty(), "openrouter should have known models");
    }

    #[test]
    fn test_cerebras_models_nonempty() {
        let models = known_models_for_provider("cerebras");
        assert!(!models.is_empty(), "cerebras should have known models");
    }

    #[test]
    fn test_ollama_models_nonempty() {
        let models = known_models_for_provider("ollama");
        assert!(!models.is_empty(), "ollama should have known models");
    }

    #[test]
    fn test_zai_models_nonempty() {
        let models = known_models_for_provider("zai");
        assert!(!models.is_empty(), "zai should have known models");
    }

    #[test]
    fn test_unknown_provider_empty() {
        let models = known_models_for_provider("foo");
        assert!(
            models.is_empty(),
            "unknown provider should return empty vec"
        );
    }

    #[test]
    fn test_all_providers_model_ids_unique() {
        let mut all_ids = HashSet::new();
        for p in &[
            "openai",
            "anthropic",
            "openrouter",
            "cerebras",
            "zai",
            "ollama",
        ] {
            for m in known_models_for_provider(p) {
                assert!(all_ids.insert(m.id.clone()), "duplicate model ID: {}", m.id);
            }
        }
    }

    #[test]
    fn test_model_info_fields() {
        for provider in &[
            "openai",
            "anthropic",
            "openrouter",
            "cerebras",
            "zai",
            "ollama",
        ] {
            for m in known_models_for_provider(provider) {
                assert!(!m.id.is_empty(), "model id should not be empty");
                assert!(m.name.is_some(), "model name should be Some for {}", m.id);
                assert_eq!(m.provider, *provider, "provider mismatch for {}", m.id);
            }
        }
    }

    // ── build_credential_status ──

    #[test]
    fn test_cred_status_all_none() {
        let cfg = op_core::config::AgentConfig::from_env("/nonexistent");
        // Force all keys to None
        let mut cfg = cfg;
        cfg.openai_api_key = None;
        cfg.anthropic_api_key = None;
        cfg.openrouter_api_key = None;
        cfg.cerebras_api_key = None;
        cfg.zai_api_key = None;
        cfg.exa_api_key = None;
        cfg.firecrawl_api_key = None;
        let status = build_credential_status(&cfg);
        assert_eq!(status["openai"], false);
        assert_eq!(status["anthropic"], false);
        assert_eq!(status["openrouter"], false);
        assert_eq!(status["cerebras"], false);
        assert_eq!(status["zai"], false);
        assert_eq!(status["ollama"], true, "ollama always true");
    }

    #[test]
    fn test_cred_status_openai_set() {
        let mut cfg = op_core::config::AgentConfig::from_env("/nonexistent");
        cfg.openai_api_key = Some("sk-test".to_string());
        cfg.anthropic_api_key = None;
        cfg.openrouter_api_key = None;
        cfg.cerebras_api_key = None;
        cfg.zai_api_key = None;
        let status = build_credential_status(&cfg);
        assert_eq!(status["openai"], true);
        assert_eq!(status["anthropic"], false);
    }

    #[test]
    fn test_cred_status_anthropic_set() {
        let mut cfg = op_core::config::AgentConfig::from_env("/nonexistent");
        cfg.openai_api_key = None;
        cfg.anthropic_api_key = Some("sk-ant-test".to_string());
        cfg.openrouter_api_key = None;
        cfg.cerebras_api_key = None;
        let status = build_credential_status(&cfg);
        assert_eq!(status["anthropic"], true);
        assert_eq!(status["openai"], false);
    }

    #[test]
    fn test_cred_status_ollama_always_true() {
        let mut cfg = op_core::config::AgentConfig::from_env("/nonexistent");
        cfg.openai_api_key = None;
        cfg.anthropic_api_key = None;
        cfg.openrouter_api_key = None;
        cfg.cerebras_api_key = None;
        cfg.zai_api_key = None;
        let status = build_credential_status(&cfg);
        assert_eq!(status["ollama"], true);
    }

    #[test]
    fn test_cred_status_all_set() {
        let mut cfg = op_core::config::AgentConfig::from_env("/nonexistent");
        cfg.openai_api_key = Some("k1".to_string());
        cfg.anthropic_api_key = Some("k2".to_string());
        cfg.openrouter_api_key = Some("k3".to_string());
        cfg.cerebras_api_key = Some("k4".to_string());
        cfg.zai_api_key = Some("k5".to_string());
        cfg.exa_api_key = Some("k6".to_string());
        cfg.firecrawl_api_key = Some("k7".to_string());
        let status = build_credential_status(&cfg);
        for (provider, has_key) in &status {
            assert!(has_key, "{} should be true when key is set", provider);
        }
    }

    #[test]
    fn test_cred_status_has_eight_entries() {
        let cfg = op_core::config::AgentConfig::from_env("/nonexistent");
        let status = build_credential_status(&cfg);
        assert_eq!(
            status.len(),
            8,
            "should have 8 entries (6 providers + 2 web services)"
        );
    }
}

use std::collections::HashMap;
use tauri::State;
use crate::state::AppState;
use op_core::events::{ConfigView, ModelInfo, PartialConfig};
use op_core::settings::{PersistentSettings, SettingsStore};
use op_core::credentials::credentials_from_env;

/// Get the current configuration.
#[tauri::command]
pub async fn get_config(
    state: State<'_, AppState>,
) -> Result<ConfigView, String> {
    let cfg = state.config.lock().await;
    let session_id = state.session_id.lock().await;
    Ok(ConfigView {
        provider: cfg.provider.clone(),
        model: cfg.model.clone(),
        reasoning_effort: cfg.reasoning_effort.clone(),
        workspace: cfg.workspace.display().to_string(),
        session_id: session_id.clone(),
        recursive: cfg.recursive,
        max_depth: cfg.max_depth,
        max_steps_per_call: cfg.max_steps_per_call,
        demo: cfg.demo,
    })
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
    let session_id = state.session_id.lock().await;
    Ok(ConfigView {
        provider: cfg.provider.clone(),
        model: cfg.model.clone(),
        reasoning_effort: cfg.reasoning_effort.clone(),
        workspace: cfg.workspace.display().to_string(),
        session_id: session_id.clone(),
        recursive: cfg.recursive,
        max_depth: cfg.max_depth,
        max_steps_per_call: cfg.max_steps_per_call,
        demo: cfg.demo,
    })
}

/// Known models per provider for listing.
fn known_models_for_provider(provider: &str) -> Vec<ModelInfo> {
    let models: Vec<(&str, &str)> = match provider {
        "openai" => vec![
            ("gpt-5.2", "GPT-5.2"),
            ("gpt-4o", "GPT-4o"),
            ("gpt-4o-mini", "GPT-4o Mini"),
            ("o1", "o1"),
            ("o3", "o3"),
            ("o4-mini", "o4-mini"),
        ],
        "anthropic" => vec![
            ("claude-opus-4-6", "Claude Opus 4.6"),
            ("claude-sonnet-4-5", "Claude Sonnet 4.5"),
            ("claude-haiku-4-5", "Claude Haiku 4.5"),
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
        for p in &["openai", "anthropic", "openrouter", "cerebras", "ollama"] {
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
    store.save(&settings).map_err(|e| e.to_string())
}

/// Get credential status: which providers have API keys configured.
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
    status.insert("ollama".to_string(), true); // Ollama never needs a key
    Ok(status)
}

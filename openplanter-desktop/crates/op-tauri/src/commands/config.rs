use tauri::State;
use crate::state::AppState;
use op_core::events::{ConfigView, ModelInfo, PartialConfig};

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

/// List available models for a provider.
#[tauri::command]
pub async fn list_models(
    provider: String,
    _state: State<'_, AppState>,
) -> Result<Vec<ModelInfo>, String> {
    // Phase 2: call model listing functions
    let _ = provider;
    Ok(vec![])
}

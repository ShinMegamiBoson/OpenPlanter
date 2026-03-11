use op_core::config::{
    AgentConfig, normalize_web_search_provider, normalize_zai_plan, resolve_zai_base_url,
};
use op_core::credentials::{
    CredentialBundle, credentials_from_env, discover_env_candidates, parse_env_file,
};
use op_core::settings::{PersistentSettings, SettingsStore};
use std::env;
use std::sync::Arc;
use tokio::sync::Mutex;
use tokio_util::sync::CancellationToken;

/// Merge credentials into an AgentConfig.
/// Priority: existing config value > env_creds > file_creds.
pub fn merge_credentials_into_config(
    cfg: &mut AgentConfig,
    env_creds: &CredentialBundle,
    file_creds: &CredentialBundle,
) {
    macro_rules! merge {
        ($field:ident) => {
            if cfg.$field.is_none() {
                cfg.$field = env_creds
                    .$field
                    .clone()
                    .or_else(|| file_creds.$field.clone());
            }
        };
    }
    merge!(openai_api_key);
    merge!(anthropic_api_key);
    merge!(openrouter_api_key);
    merge!(cerebras_api_key);
    merge!(zai_api_key);
    merge!(exa_api_key);
    merge!(firecrawl_api_key);
    merge!(voyage_api_key);
}

fn has_env_value(keys: &[&str]) -> bool {
    keys.iter().any(|key| {
        env::var(key)
            .ok()
            .map(|value| !value.trim().is_empty())
            .unwrap_or(false)
    })
}

fn apply_settings_to_config(cfg: &mut AgentConfig, settings: &PersistentSettings) {
    if !has_env_value(&["OPENPLANTER_REASONING_EFFORT"]) {
        if let Some(reasoning_effort) = settings.default_reasoning_effort.clone() {
            cfg.reasoning_effort = Some(reasoning_effort);
        }
    }

    if !has_env_value(&["OPENPLANTER_ZAI_PLAN"]) {
        if let Some(plan) = settings.zai_plan.as_deref() {
            cfg.zai_plan = normalize_zai_plan(Some(plan));
        }
    }

    if !has_env_value(&["OPENPLANTER_ZAI_BASE_URL"]) {
        cfg.zai_base_url = resolve_zai_base_url(
            &cfg.zai_plan,
            &cfg.zai_paygo_base_url,
            &cfg.zai_coding_base_url,
        );
    }

    if !has_env_value(&["OPENPLANTER_WEB_SEARCH_PROVIDER"]) {
        if let Some(provider) = settings.web_search_provider.as_deref() {
            cfg.web_search_provider = normalize_web_search_provider(Some(provider));
        }
    }

    if !has_env_value(&["OPENPLANTER_MODEL"]) {
        let saved_model = if cfg.provider == "auto" {
            settings.default_model.as_deref()
        } else {
            settings
                .default_model_for_provider(cfg.provider.as_str())
                .or(settings.default_model.as_deref())
        };
        if let Some(model) = saved_model {
            cfg.model = model.to_string();
        }
    }
}

/// Application state shared across Tauri commands.
pub struct AppState {
    pub config: Arc<Mutex<AgentConfig>>,
    pub session_id: Arc<Mutex<Option<String>>>,
    pub cancel_token: Arc<Mutex<CancellationToken>>,
}

impl AppState {
    pub fn new() -> Self {
        let mut cfg = AgentConfig::from_env(".");

        // Load .env files and merge credentials into config
        let env_creds = credentials_from_env();
        let candidates = discover_env_candidates(&cfg.workspace);
        for candidate in &candidates {
            let file_creds = parse_env_file(candidate);
            merge_credentials_into_config(&mut cfg, &env_creds, &file_creds);
        }

        // If no .env candidates found, still merge from process env
        if candidates.is_empty() {
            let empty = CredentialBundle::default();
            merge_credentials_into_config(&mut cfg, &env_creds, &empty);
        }

        let settings = SettingsStore::new(&cfg.workspace, &cfg.session_root_dir).load();
        apply_settings_to_config(&mut cfg, &settings);

        Self {
            config: Arc::new(Mutex::new(cfg)),
            session_id: Arc::new(Mutex::new(None)),
            cancel_token: Arc::new(Mutex::new(CancellationToken::new())),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::env;

    fn empty_cfg() -> AgentConfig {
        let mut cfg = AgentConfig::from_env("/nonexistent");
        cfg.openai_api_key = None;
        cfg.anthropic_api_key = None;
        cfg.openrouter_api_key = None;
        cfg.cerebras_api_key = None;
        cfg.zai_api_key = None;
        cfg.exa_api_key = None;
        cfg.firecrawl_api_key = None;
        cfg.voyage_api_key = None;
        cfg
    }

    #[test]
    fn test_merge_fills_missing() {
        let mut cfg = empty_cfg();
        let env_creds = CredentialBundle {
            openai_api_key: Some("env-key".to_string()),
            ..Default::default()
        };
        let file_creds = CredentialBundle::default();
        merge_credentials_into_config(&mut cfg, &env_creds, &file_creds);
        assert_eq!(cfg.openai_api_key, Some("env-key".to_string()));
    }

    #[test]
    fn test_merge_preserves_existing() {
        let mut cfg = empty_cfg();
        cfg.openai_api_key = Some("existing".to_string());
        let env_creds = CredentialBundle {
            openai_api_key: Some("env-key".to_string()),
            ..Default::default()
        };
        let file_creds = CredentialBundle::default();
        merge_credentials_into_config(&mut cfg, &env_creds, &file_creds);
        assert_eq!(cfg.openai_api_key, Some("existing".to_string()));
    }

    #[test]
    fn test_merge_env_over_file() {
        let mut cfg = empty_cfg();
        let env_creds = CredentialBundle {
            anthropic_api_key: Some("env-ant".to_string()),
            ..Default::default()
        };
        let file_creds = CredentialBundle {
            anthropic_api_key: Some("file-ant".to_string()),
            ..Default::default()
        };
        merge_credentials_into_config(&mut cfg, &env_creds, &file_creds);
        assert_eq!(cfg.anthropic_api_key, Some("env-ant".to_string()));
    }

    #[test]
    fn test_merge_file_fills_when_env_missing() {
        let mut cfg = empty_cfg();
        let env_creds = CredentialBundle::default();
        let file_creds = CredentialBundle {
            cerebras_api_key: Some("file-cer".to_string()),
            ..Default::default()
        };
        merge_credentials_into_config(&mut cfg, &env_creds, &file_creds);
        assert_eq!(cfg.cerebras_api_key, Some("file-cer".to_string()));
    }

    #[test]
    fn test_merge_includes_zai_and_firecrawl() {
        let mut cfg = empty_cfg();
        let env_creds = CredentialBundle {
            zai_api_key: Some("zai-env".to_string()),
            firecrawl_api_key: Some("fc-env".to_string()),
            ..Default::default()
        };
        merge_credentials_into_config(&mut cfg, &env_creds, &CredentialBundle::default());
        assert_eq!(cfg.zai_api_key, Some("zai-env".to_string()));
        assert_eq!(cfg.firecrawl_api_key, Some("fc-env".to_string()));
    }

    #[test]
    fn test_apply_settings_to_config_sets_model_and_web_search() {
        let keys = [
            "OPENPLANTER_MODEL",
            "OPENPLANTER_REASONING_EFFORT",
            "OPENPLANTER_ZAI_PLAN",
            "OPENPLANTER_ZAI_BASE_URL",
            "OPENPLANTER_WEB_SEARCH_PROVIDER",
        ];
        let saved: Vec<_> = keys.iter().map(|key| (*key, env::var(key).ok())).collect();
        unsafe {
            for key in &keys {
                env::remove_var(key);
            }
        }

        let mut cfg = empty_cfg();
        cfg.provider = "zai".to_string();
        let settings = PersistentSettings {
            default_model_zai: Some("glm-5".to_string()),
            default_reasoning_effort: Some("medium".to_string()),
            zai_plan: Some("coding".to_string()),
            web_search_provider: Some("firecrawl".to_string()),
            ..Default::default()
        };
        apply_settings_to_config(&mut cfg, &settings);
        assert_eq!(cfg.model, "glm-5");
        assert_eq!(cfg.reasoning_effort, Some("medium".to_string()));
        assert_eq!(cfg.zai_plan, "coding");
        assert_eq!(cfg.zai_base_url, op_core::config::ZAI_CODING_BASE_URL);
        assert_eq!(cfg.web_search_provider, "firecrawl");

        for (key, value) in saved {
            unsafe {
                match value {
                    Some(value) => env::set_var(key, value),
                    None => env::remove_var(key),
                }
            }
        }
    }
}

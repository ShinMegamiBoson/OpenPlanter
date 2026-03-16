use std::sync::Arc;
use tokio::sync::Mutex;
use tokio_util::sync::CancellationToken;
use op_core::config::AgentConfig;
use op_core::credentials::{credentials_from_env, discover_env_candidates, parse_env_file, CredentialBundle};

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
                cfg.$field = env_creds.$field.clone()
                    .or_else(|| file_creds.$field.clone());
            }
        };
    }
    merge!(openai_api_key);
    merge!(anthropic_api_key);
    merge!(openrouter_api_key);
    merge!(cerebras_api_key);
    merge!(exa_api_key);
    merge!(voyage_api_key);
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

    fn empty_cfg() -> AgentConfig {
        let mut cfg = AgentConfig::from_env("/nonexistent");
        cfg.openai_api_key = None;
        cfg.anthropic_api_key = None;
        cfg.openrouter_api_key = None;
        cfg.cerebras_api_key = None;
        cfg.exa_api_key = None;
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
}

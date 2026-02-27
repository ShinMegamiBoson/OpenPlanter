use std::sync::Arc;
use tokio::sync::Mutex;
use tokio_util::sync::CancellationToken;
use op_core::config::AgentConfig;
use op_core::credentials::{credentials_from_env, discover_env_candidates, parse_env_file};

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
        for candidate in discover_env_candidates(&cfg.workspace) {
            let file_creds = parse_env_file(&candidate);
            // .env file values fill in anything missing from process env
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

        // If no .env candidates found, still merge from process env
        if discover_env_candidates(&cfg.workspace).is_empty() {
            macro_rules! merge_env {
                ($field:ident) => {
                    if cfg.$field.is_none() {
                        cfg.$field = env_creds.$field.clone();
                    }
                };
            }
            merge_env!(openai_api_key);
            merge_env!(anthropic_api_key);
            merge_env!(openrouter_api_key);
            merge_env!(cerebras_api_key);
            merge_env!(exa_api_key);
            merge_env!(voyage_api_key);
        }

        Self {
            config: Arc::new(Mutex::new(cfg)),
            session_id: Arc::new(Mutex::new(None)),
            cancel_token: Arc::new(Mutex::new(CancellationToken::new())),
        }
    }
}

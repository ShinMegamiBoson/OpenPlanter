use std::env;

use crate::config::{
    AgentConfig, FOUNDRY_OPENAI_API_KEY_PLACEHOLDER, normalize_web_search_provider,
    normalize_zai_plan, resolve_openai_api_key, resolve_zai_base_url,
};
use crate::credentials::CredentialBundle;
use crate::settings::PersistentSettings;

/// Merge credentials into an AgentConfig.
/// Priority: existing config value > env_creds > file_creds.
pub fn merge_credentials_into_config(
    cfg: &mut AgentConfig,
    env_creds: &CredentialBundle,
    file_creds: &CredentialBundle,
) {
    if cfg.openai_oauth_token.is_none() {
        cfg.openai_oauth_token = env_creds
            .openai_oauth_token
            .clone()
            .or_else(|| file_creds.openai_oauth_token.clone());
    }
    cfg.openai_api_key = cfg
        .openai_api_key
        .clone()
        .filter(|value| {
            let trimmed = value.trim();
            !trimmed.is_empty() && trimmed != FOUNDRY_OPENAI_API_KEY_PLACEHOLDER
        })
        .or_else(|| env_creds.openai_api_key.clone())
        .or_else(|| file_creds.openai_api_key.clone())
        .or_else(|| cfg.openai_api_key.clone());
    cfg.openai_api_key = resolve_openai_api_key(
        cfg.openai_api_key.clone(),
        &cfg.openai_base_url,
        cfg.openai_oauth_token.clone(),
    );
    cfg.api_key = resolve_openai_api_key(
        cfg.openai_api_key
            .clone()
            .filter(|value| {
                let trimmed = value.trim();
                !trimmed.is_empty() && trimmed != FOUNDRY_OPENAI_API_KEY_PLACEHOLDER
            })
            .or_else(|| {
                cfg.api_key.clone().filter(|value| {
                    let trimmed = value.trim();
                    !trimmed.is_empty() && trimmed != FOUNDRY_OPENAI_API_KEY_PLACEHOLDER
                })
            })
            .or_else(|| cfg.openai_api_key.clone())
            .or_else(|| cfg.api_key.clone()),
        &cfg.base_url,
        cfg.openai_oauth_token.clone(),
    );

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
    merge!(anthropic_api_key);
    merge!(openrouter_api_key);
    merge!(cerebras_api_key);
    merge!(zai_api_key);
    merge!(exa_api_key);
    merge!(firecrawl_api_key);
    merge!(brave_api_key);
    merge!(tavily_api_key);
    merge!(voyage_api_key);
    merge!(mistral_transcription_api_key);
}

pub fn apply_settings_to_config(cfg: &mut AgentConfig, settings: &PersistentSettings) {
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

fn has_env_value(keys: &[&str]) -> bool {
    keys.iter().any(|key| {
        env::var(key)
            .ok()
            .map(|value| !value.trim().is_empty())
            .unwrap_or(false)
    })
}

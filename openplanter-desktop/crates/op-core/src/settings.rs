use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::config::{normalize_web_search_provider, normalize_zai_plan};

const VALID_REASONING_EFFORTS: &[&str] = &["low", "medium", "high"];

/// Normalize and validate a reasoning effort value.
pub fn normalize_reasoning_effort(value: Option<&str>) -> Result<Option<String>, String> {
    match value {
        None => Ok(None),
        Some(v) => {
            let cleaned = v.trim().to_lowercase();
            if cleaned.is_empty() {
                return Ok(None);
            }
            if !VALID_REASONING_EFFORTS.contains(&cleaned.as_str()) {
                return Err(format!(
                    "Invalid reasoning effort '{}'. Expected one of: {}",
                    v,
                    VALID_REASONING_EFFORTS.join(", ")
                ));
            }
            Ok(Some(cleaned))
        }
    }
}

/// Persistent settings stored per workspace.
///
/// Mirrors the Python `PersistentSettings` dataclass.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct PersistentSettings {
    pub default_model: Option<String>,
    pub default_reasoning_effort: Option<String>,
    pub default_model_openai: Option<String>,
    pub default_model_anthropic: Option<String>,
    pub default_model_openrouter: Option<String>,
    pub default_model_cerebras: Option<String>,
    pub default_model_zai: Option<String>,
    pub default_model_ollama: Option<String>,
    pub zai_plan: Option<String>,
    pub web_search_provider: Option<String>,
}

impl PersistentSettings {
    /// Get the default model for a specific provider.
    pub fn default_model_for_provider(&self, provider: &str) -> Option<&str> {
        let specific = match provider {
            "openai" => self.default_model_openai.as_deref(),
            "anthropic" => self.default_model_anthropic.as_deref(),
            "openrouter" => self.default_model_openrouter.as_deref(),
            "cerebras" => self.default_model_cerebras.as_deref(),
            "zai" => self.default_model_zai.as_deref(),
            "ollama" => self.default_model_ollama.as_deref(),
            _ => None,
        };
        if specific.is_some() {
            return specific;
        }
        self.default_model.as_deref()
    }

    /// Return a normalized copy with trimmed/validated values.
    pub fn normalized(&self) -> Result<Self, String> {
        let model = self
            .default_model
            .as_deref()
            .map(|s| s.trim())
            .filter(|s| !s.is_empty())
            .map(String::from);

        let effort = normalize_reasoning_effort(self.default_reasoning_effort.as_deref())?;

        let web_search_provider = self
            .web_search_provider
            .as_deref()
            .map(|value| normalize_web_search_provider(Some(value)));
        let zai_plan = self
            .zai_plan
            .as_deref()
            .map(|value| normalize_zai_plan(Some(value)));

        fn trim_opt(v: &Option<String>) -> Option<String> {
            v.as_deref()
                .map(|s| s.trim())
                .filter(|s| !s.is_empty())
                .map(String::from)
        }

        Ok(Self {
            default_model: model,
            default_reasoning_effort: effort,
            default_model_openai: trim_opt(&self.default_model_openai),
            default_model_anthropic: trim_opt(&self.default_model_anthropic),
            default_model_openrouter: trim_opt(&self.default_model_openrouter),
            default_model_cerebras: trim_opt(&self.default_model_cerebras),
            default_model_zai: trim_opt(&self.default_model_zai),
            default_model_ollama: trim_opt(&self.default_model_ollama),
            zai_plan,
            web_search_provider,
        })
    }

    /// Serialize to JSON map, omitting `None` values.
    pub fn to_json(&self) -> HashMap<String, String> {
        let mut payload = HashMap::new();
        macro_rules! add {
            ($field:ident, $key:expr) => {
                if let Some(ref v) = self.$field {
                    payload.insert($key.to_string(), v.clone());
                }
            };
        }
        add!(default_model, "default_model");
        add!(default_reasoning_effort, "default_reasoning_effort");
        add!(default_model_openai, "default_model_openai");
        add!(default_model_anthropic, "default_model_anthropic");
        add!(default_model_openrouter, "default_model_openrouter");
        add!(default_model_cerebras, "default_model_cerebras");
        add!(default_model_zai, "default_model_zai");
        add!(default_model_ollama, "default_model_ollama");
        add!(zai_plan, "zai_plan");
        add!(web_search_provider, "web_search_provider");
        payload
    }

    /// Deserialize from a JSON map.
    pub fn from_json(payload: &serde_json::Value) -> Result<Self, String> {
        let obj = match payload.as_object() {
            Some(o) => o,
            None => return Ok(Self::default()),
        };

        fn get_str(map: &serde_json::Map<String, serde_json::Value>, key: &str) -> Option<String> {
            map.get(key)
                .and_then(|v| v.as_str())
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
        }

        let settings = Self {
            default_model: get_str(obj, "default_model"),
            default_reasoning_effort: get_str(obj, "default_reasoning_effort"),
            default_model_openai: get_str(obj, "default_model_openai"),
            default_model_anthropic: get_str(obj, "default_model_anthropic"),
            default_model_openrouter: get_str(obj, "default_model_openrouter"),
            default_model_cerebras: get_str(obj, "default_model_cerebras"),
            default_model_zai: get_str(obj, "default_model_zai"),
            default_model_ollama: get_str(obj, "default_model_ollama"),
            zai_plan: get_str(obj, "zai_plan"),
            web_search_provider: get_str(obj, "web_search_provider"),
        };
        settings.normalized()
    }
}

/// Persistent settings store at `{workspace}/.openplanter/settings.json`.
pub struct SettingsStore {
    pub settings_path: PathBuf,
}

impl SettingsStore {
    pub fn new(workspace: &Path, session_root_dir: &str) -> Self {
        let ws = workspace
            .canonicalize()
            .unwrap_or_else(|_| workspace.to_path_buf());
        let root = ws.join(session_root_dir);
        let _ = fs::create_dir_all(&root);
        Self {
            settings_path: root.join("settings.json"),
        }
    }

    pub fn load(&self) -> PersistentSettings {
        let content = match fs::read_to_string(&self.settings_path) {
            Ok(c) => c,
            Err(_) => return PersistentSettings::default(),
        };
        let parsed: serde_json::Value = match serde_json::from_str(&content) {
            Ok(v) => v,
            Err(_) => return PersistentSettings::default(),
        };
        PersistentSettings::from_json(&parsed).unwrap_or_default()
    }

    pub fn save(&self, settings: &PersistentSettings) -> std::io::Result<()> {
        let normalized = settings
            .normalized()
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidInput, e))?;
        let json = serde_json::to_string_pretty(&normalized.to_json())
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;
        fs::write(&self.settings_path, json)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_normalize_reasoning_effort_valid() {
        assert_eq!(
            normalize_reasoning_effort(Some("high")),
            Ok(Some("high".into()))
        );
        assert_eq!(
            normalize_reasoning_effort(Some(" LOW ")),
            Ok(Some("low".into()))
        );
        assert_eq!(
            normalize_reasoning_effort(Some("Medium")),
            Ok(Some("medium".into()))
        );
    }

    #[test]
    fn test_normalize_reasoning_effort_none() {
        assert_eq!(normalize_reasoning_effort(None), Ok(None));
        assert_eq!(normalize_reasoning_effort(Some("")), Ok(None));
        assert_eq!(normalize_reasoning_effort(Some("  ")), Ok(None));
    }

    #[test]
    fn test_normalize_reasoning_effort_invalid() {
        let result = normalize_reasoning_effort(Some("turbo"));
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("turbo"));
    }

    #[test]
    fn test_default_model_for_provider() {
        let settings = PersistentSettings {
            default_model: Some("global-model".into()),
            default_model_openai: Some("gpt-5.2".into()),
            default_model_zai: Some("glm-5".into()),
            ..Default::default()
        };
        assert_eq!(
            settings.default_model_for_provider("openai"),
            Some("gpt-5.2")
        );
        assert_eq!(
            settings.default_model_for_provider("anthropic"),
            Some("global-model")
        );
        assert_eq!(settings.default_model_for_provider("zai"), Some("glm-5"));
        assert_eq!(
            settings.default_model_for_provider("unknown"),
            Some("global-model")
        );
    }

    #[test]
    fn test_settings_store_save_load() {
        let dir = tempfile::tempdir().unwrap();
        let store = SettingsStore::new(dir.path(), ".openplanter");
        let settings = PersistentSettings {
            default_model: Some("gpt-5.2".into()),
            default_reasoning_effort: Some("high".into()),
            default_model_zai: Some("glm-5".into()),
            zai_plan: Some("coding".into()),
            web_search_provider: Some("firecrawl".into()),
            ..Default::default()
        };
        store.save(&settings).unwrap();
        let loaded = store.load();
        assert_eq!(loaded.default_model, Some("gpt-5.2".into()));
        assert_eq!(loaded.default_reasoning_effort, Some("high".into()));
        assert_eq!(loaded.default_model_zai, Some("glm-5".into()));
        assert_eq!(loaded.zai_plan, Some("coding".into()));
        assert_eq!(loaded.web_search_provider, Some("firecrawl".into()));
    }

    #[test]
    fn test_settings_store_load_missing() {
        let dir = tempfile::tempdir().unwrap();
        let store = SettingsStore::new(dir.path(), ".openplanter");
        let loaded = store.load();
        assert_eq!(loaded, PersistentSettings::default());
    }

    #[test]
    fn test_to_json_omits_none() {
        let settings = PersistentSettings {
            default_model: Some("test".into()),
            default_reasoning_effort: None,
            ..Default::default()
        };
        let json = settings.to_json();
        assert!(json.contains_key("default_model"));
        assert!(!json.contains_key("default_reasoning_effort"));
    }

    #[test]
    fn test_from_json_round_trip() {
        let settings = PersistentSettings {
            default_model: Some("gpt-5.2".into()),
            default_reasoning_effort: Some("high".into()),
            default_model_openai: Some("gpt-5.2".into()),
            default_model_zai: Some("glm-5".into()),
            zai_plan: Some("coding".into()),
            web_search_provider: Some("firecrawl".into()),
            ..Default::default()
        };
        let json_val = serde_json::to_value(settings.to_json()).unwrap();
        let loaded = PersistentSettings::from_json(&json_val).unwrap();
        assert_eq!(loaded.default_model, Some("gpt-5.2".into()));
        assert_eq!(loaded.default_reasoning_effort, Some("high".into()));
        assert_eq!(loaded.default_model_openai, Some("gpt-5.2".into()));
        assert_eq!(loaded.default_model_zai, Some("glm-5".into()));
        assert_eq!(loaded.zai_plan, Some("coding".into()));
        assert_eq!(loaded.web_search_provider, Some("firecrawl".into()));
    }

    #[test]
    fn test_web_search_provider_normalized() {
        let settings = PersistentSettings {
            web_search_provider: Some("unexpected".into()),
            ..Default::default()
        };
        let normalized = settings.normalized().unwrap();
        assert_eq!(normalized.web_search_provider, Some("exa".into()));
    }

    #[test]
    fn test_zai_plan_normalized() {
        let settings = PersistentSettings {
            zai_plan: Some("unexpected".into()),
            ..Default::default()
        };
        let normalized = settings.normalized().unwrap();
        assert_eq!(normalized.zai_plan, Some("paygo".into()));
    }
}

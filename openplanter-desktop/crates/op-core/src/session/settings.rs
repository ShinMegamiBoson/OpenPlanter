// Per-session settings overlay that can override global config.

use serde::{Deserialize, Serialize};
use std::path::Path;
use tokio::fs;

/// Session-level settings that override global configuration.
///
/// All fields are optional — `None` means "use the global default".
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SessionSettings {
    pub provider: Option<String>,
    pub model: Option<String>,
    pub reasoning_effort: Option<String>,
    pub recursive: Option<bool>,
    pub max_depth: Option<u32>,
    pub max_steps_per_call: Option<u32>,
}

impl SessionSettings {
    /// Load session settings from `settings.json` in the session directory.
    /// Returns default (all None) if the file doesn't exist.
    pub async fn load(session_dir: &Path) -> std::io::Result<Self> {
        let path = session_dir.join("settings.json");
        if !path.exists() {
            return Ok(Self::default());
        }
        let content = fs::read_to_string(&path).await?;
        serde_json::from_str(&content)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))
    }

    /// Save session settings to `settings.json` in the session directory.
    pub async fn save(&self, session_dir: &Path) -> std::io::Result<()> {
        let path = session_dir.join("settings.json");
        let json = serde_json::to_string_pretty(self)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;
        fs::write(&path, json).await
    }

    /// Returns true if all fields are None (no overrides).
    pub fn is_empty(&self) -> bool {
        self.provider.is_none()
            && self.model.is_none()
            && self.reasoning_effort.is_none()
            && self.recursive.is_none()
            && self.max_depth.is_none()
            && self.max_steps_per_call.is_none()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_default_is_empty() {
        let settings = SessionSettings::default();
        assert!(settings.is_empty());
    }

    #[test]
    fn test_not_empty_with_provider() {
        let settings = SessionSettings {
            provider: Some("anthropic".into()),
            ..Default::default()
        };
        assert!(!settings.is_empty());
    }

    #[tokio::test]
    async fn test_save_and_load() {
        let tmp = tempdir().unwrap();
        let settings = SessionSettings {
            provider: Some("openai".into()),
            model: Some("gpt-5.2".into()),
            recursive: Some(true),
            ..Default::default()
        };
        settings.save(tmp.path()).await.unwrap();

        let loaded = SessionSettings::load(tmp.path()).await.unwrap();
        assert_eq!(loaded.provider, Some("openai".into()));
        assert_eq!(loaded.model, Some("gpt-5.2".into()));
        assert_eq!(loaded.recursive, Some(true));
        assert!(loaded.reasoning_effort.is_none());
    }

    #[tokio::test]
    async fn test_load_missing_returns_default() {
        let tmp = tempdir().unwrap();
        let settings = SessionSettings::load(tmp.path()).await.unwrap();
        assert!(settings.is_empty());
    }
}

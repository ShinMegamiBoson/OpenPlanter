// Per-session credential references.
//
// Stores which credential set to use, not the raw keys themselves.

use serde::{Deserialize, Serialize};
use std::path::Path;
use tokio::fs;

/// Per-session credential reference.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SessionCredentials {
    /// Name of the credential set to use for this session.
    pub credential_set: Option<String>,
}

impl SessionCredentials {
    /// Load session credentials from `credentials.json` in the session directory.
    /// Returns default if the file doesn't exist.
    pub async fn load(session_dir: &Path) -> std::io::Result<Self> {
        let path = session_dir.join("credentials.json");
        if !path.exists() {
            return Ok(Self::default());
        }
        let content = fs::read_to_string(&path).await?;
        serde_json::from_str(&content)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))
    }

    /// Save session credentials to `credentials.json` in the session directory.
    pub async fn save(&self, session_dir: &Path) -> std::io::Result<()> {
        let path = session_dir.join("credentials.json");
        let json = serde_json::to_string_pretty(self)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;
        fs::write(&path, json).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[tokio::test]
    async fn test_save_and_load() {
        let tmp = tempdir().unwrap();
        let creds = SessionCredentials {
            credential_set: Some("production".into()),
        };
        creds.save(tmp.path()).await.unwrap();

        let loaded = SessionCredentials::load(tmp.path()).await.unwrap();
        assert_eq!(loaded.credential_set, Some("production".into()));
    }

    #[tokio::test]
    async fn test_load_missing_returns_default() {
        let tmp = tempdir().unwrap();
        let creds = SessionCredentials::load(tmp.path()).await.unwrap();
        assert!(creds.credential_set.is_none());
    }

    #[test]
    fn test_default_has_no_credential_set() {
        let creds = SessionCredentials::default();
        assert!(creds.credential_set.is_none());
    }
}

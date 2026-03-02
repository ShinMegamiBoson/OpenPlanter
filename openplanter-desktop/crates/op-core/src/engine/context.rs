// External context and turn summary types for multi-turn sessions.

use serde::{Deserialize, Serialize};
use std::path::Path;
use tokio::fs;

/// Summary of a completed turn for inclusion in subsequent prompts.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TurnSummary {
    pub turn_number: u32,
    pub objective: String,
    pub result_preview: String,
    pub timestamp: String,
    pub steps_used: u32,
    pub replay_seq_start: u64,
}

/// External context observations persisted to state.json.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExternalContext {
    pub observations: Vec<Observation>,
}

/// A single observation from an external source.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Observation {
    pub source: String,
    pub timestamp: String,
    pub content: String,
}

impl ExternalContext {
    pub fn new() -> Self {
        Self {
            observations: vec![],
        }
    }

    /// Add a new observation with the current timestamp.
    pub fn add_observation(&mut self, source: &str, content: &str) {
        self.observations.push(Observation {
            source: source.to_string(),
            timestamp: chrono::Utc::now().to_rfc3339(),
            content: content.to_string(),
        });
    }

    /// Load external context from state.json in the session directory.
    pub async fn load(session_dir: &Path) -> std::io::Result<Self> {
        let path = session_dir.join("state.json");
        if !path.exists() {
            return Ok(Self::new());
        }
        let content = fs::read_to_string(&path).await?;
        serde_json::from_str(&content)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))
    }

    /// Save external context to state.json in the session directory.
    pub async fn save(&self, session_dir: &Path) -> std::io::Result<()> {
        let path = session_dir.join("state.json");
        let json = serde_json::to_string_pretty(self)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;
        fs::write(&path, json).await
    }
}

impl Default for ExternalContext {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_new_context_empty() {
        let ctx = ExternalContext::new();
        assert!(ctx.observations.is_empty());
    }

    #[test]
    fn test_add_observation() {
        let mut ctx = ExternalContext::new();
        ctx.add_observation("wiki", "Found entity Acme Corp");
        assert_eq!(ctx.observations.len(), 1);
        assert_eq!(ctx.observations[0].source, "wiki");
        assert_eq!(ctx.observations[0].content, "Found entity Acme Corp");
        assert!(!ctx.observations[0].timestamp.is_empty());
    }

    #[tokio::test]
    async fn test_save_and_load() {
        let tmp = tempdir().unwrap();
        let mut ctx = ExternalContext::new();
        ctx.add_observation("wiki", "test observation");
        ctx.save(tmp.path()).await.unwrap();

        let loaded = ExternalContext::load(tmp.path()).await.unwrap();
        assert_eq!(loaded.observations.len(), 1);
        assert_eq!(loaded.observations[0].content, "test observation");
    }

    #[tokio::test]
    async fn test_load_missing_returns_empty() {
        let tmp = tempdir().unwrap();
        let ctx = ExternalContext::load(tmp.path()).await.unwrap();
        assert!(ctx.observations.is_empty());
    }

    #[test]
    fn test_turn_summary_serialization() {
        let ts = TurnSummary {
            turn_number: 1,
            objective: "Investigate Acme Corp".into(),
            result_preview: "Found connections to...".into(),
            timestamp: "2026-01-01T00:00:00Z".into(),
            steps_used: 3,
            replay_seq_start: 1,
        };
        let json = serde_json::to_string(&ts).unwrap();
        let parsed: TurnSummary = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed.turn_number, 1);
        assert_eq!(parsed.objective, "Investigate Acme Corp");
    }
}

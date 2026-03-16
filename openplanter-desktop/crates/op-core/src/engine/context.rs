// External context and turn summary types for multi-turn sessions.

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::path::Path;
use tokio::fs;

use super::investigation_state::InvestigationState;

struct ResolvedInvestigationState {
    state: InvestigationState,
    legacy_rust_observations: Option<Vec<Observation>>,
}

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

    /// Load external context from canonical investigation_state.json or legacy state.json.
    pub async fn load(session_dir: &Path) -> std::io::Result<Self> {
        let session_id = session_dir
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or_default();
        let resolved = resolve_investigation_state(session_dir, session_id).await?;
        if let Some(observations) = resolved.legacy_rust_observations {
            return Ok(Self { observations });
        }
        Ok(Self {
            observations: resolved
                .state
                .legacy_observations()
                .into_iter()
                .map(|content| Observation {
                    source: "legacy".to_string(),
                    timestamp: String::new(),
                    content,
                })
                .collect(),
        })
    }

    /// Save external context to additive investigation_state.json and legacy state.json.
    pub async fn save(&self, session_dir: &Path) -> std::io::Result<()> {
        let session_id = session_dir
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or_default();
        let typed_path = session_dir.join("investigation_state.json");
        let legacy_path = session_dir.join("state.json");

        let mut typed_state = load_or_migrate_investigation_state(session_dir).await?;
        if typed_state.session_id.is_empty() {
            typed_state.session_id = session_id.to_string();
        }
        let observations: Vec<String> = self
            .observations
            .iter()
            .map(|observation| observation.content.clone())
            .collect();
        typed_state.merge_legacy_updates(&observations, None, None, None);

        let typed_json = serde_json::to_string_pretty(&typed_state)
            .map_err(|e| std::io::Error::other(e.to_string()))?;
        fs::write(&typed_path, typed_json).await?;

        let legacy_json = serde_json::to_string_pretty(&typed_state.to_legacy_python_projection())
            .map_err(|e| std::io::Error::other(e.to_string()))?;
        fs::write(&legacy_path, legacy_json).await
    }
}

impl Default for ExternalContext {
    fn default() -> Self {
        Self::new()
    }
}

pub async fn load_or_migrate_investigation_state(
    session_dir: &Path,
) -> std::io::Result<InvestigationState> {
    let session_id = session_dir
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or_default();
    load_existing_investigation_state(session_dir, session_id).await
}

async fn load_existing_investigation_state(
    session_dir: &Path,
    session_id: &str,
) -> std::io::Result<InvestigationState> {
    Ok(resolve_investigation_state(session_dir, session_id)
        .await?
        .state)
}

async fn resolve_investigation_state(
    session_dir: &Path,
    session_id: &str,
) -> std::io::Result<ResolvedInvestigationState> {
    let typed_path = session_dir.join("investigation_state.json");
    if let Some(state) = try_load_typed_state(&typed_path).await? {
        return Ok(ResolvedInvestigationState {
            state,
            legacy_rust_observations: None,
        });
    }

    let legacy_path = session_dir.join("state.json");
    if !legacy_path.exists() {
        return Ok(ResolvedInvestigationState {
            state: InvestigationState::new(session_id),
            legacy_rust_observations: None,
        });
    }

    let content = fs::read_to_string(&legacy_path).await?;
    let value: Value = serde_json::from_str(&content)
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))?;

    if legacy_python_observations(&value).is_some() {
        return Ok(ResolvedInvestigationState {
            state: InvestigationState::from_legacy_python_state(session_id, &value),
            legacy_rust_observations: None,
        });
    }
    if let Some(observations) = legacy_rust_observations(&value) {
        return Ok(ResolvedInvestigationState {
            state: InvestigationState::from_legacy_rust_state(session_id, &value),
            legacy_rust_observations: Some(observations),
        });
    }

    Err(std::io::Error::new(
        std::io::ErrorKind::InvalidData,
        "state.json format not recognized",
    ))
}

async fn try_load_typed_state(path: &Path) -> std::io::Result<Option<InvestigationState>> {
    if !path.exists() {
        return Ok(None);
    }

    let content = match fs::read_to_string(path).await {
        Ok(content) => content,
        Err(err) if err.kind() == std::io::ErrorKind::InvalidData => return Ok(None),
        Err(err) => return Err(err),
    };

    match serde_json::from_str(&content) {
        Ok(state) => Ok(Some(state)),
        Err(_) => Ok(None),
    }
}

fn legacy_python_observations(value: &Value) -> Option<Vec<String>> {
    value
        .as_object()?
        .get("external_observations")?
        .as_array()
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .map(ToString::to_string)
                .collect()
        })
}

fn legacy_rust_observations(value: &Value) -> Option<Vec<Observation>> {
    let observations = value.as_object()?.get("observations")?.as_array()?;
    Some(
        observations
            .iter()
            .filter_map(|item| item.as_object())
            .map(|item| Observation {
                source: item
                    .get("source")
                    .and_then(Value::as_str)
                    .unwrap_or("legacy")
                    .to_string(),
                timestamp: item
                    .get("timestamp")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_string(),
                content: item
                    .get("content")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_string(),
            })
            .collect(),
    )
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
        assert!(tmp.path().join("investigation_state.json").exists());
        assert!(tmp.path().join("state.json").exists());
    }

    #[tokio::test]
    async fn test_load_missing_returns_empty() {
        let tmp = tempdir().unwrap();
        let ctx = ExternalContext::load(tmp.path()).await.unwrap();
        assert!(ctx.observations.is_empty());
    }

    #[tokio::test]
    async fn test_load_legacy_python_state_shape() {
        let tmp = tempdir().unwrap();
        fs::write(
            tmp.path().join("state.json"),
            r#"{"session_id":"sid","external_observations":["one","two"]}"#,
        )
        .await
        .unwrap();

        let ctx = ExternalContext::load(tmp.path()).await.unwrap();
        assert_eq!(ctx.observations.len(), 2);
        assert_eq!(ctx.observations[0].content, "one");
        assert_eq!(ctx.observations[1].content, "two");
    }

    #[tokio::test]
    async fn test_load_or_migrate_investigation_state_prefers_typed_state() {
        let tmp = tempdir().unwrap();
        fs::write(
            tmp.path().join("investigation_state.json"),
            r#"{"schema_version":"1.0.0","session_id":"sid","questions":{"q_1":{"id":"q_1","question_text":"keep me"}}}"#,
        )
        .await
        .unwrap();
        fs::write(
            tmp.path().join("state.json"),
            r#"{"session_id":"sid","external_observations":["legacy"]}"#,
        )
        .await
        .unwrap();

        let state = load_or_migrate_investigation_state(tmp.path())
            .await
            .unwrap();
        assert!(state.questions.contains_key("q_1"));
        assert!(state.legacy.external_observations.is_empty());
    }

    #[tokio::test]
    async fn test_load_or_migrate_investigation_state_migrates_legacy_state() {
        let tmp = tempdir().unwrap();
        fs::write(
            tmp.path().join("state.json"),
            r#"{"session_id":"sid","external_observations":["legacy one"]}"#,
        )
        .await
        .unwrap();

        let state = load_or_migrate_investigation_state(tmp.path())
            .await
            .unwrap();
        assert_eq!(state.legacy.external_observations, vec!["legacy one"]);
        assert_eq!(
            state.evidence["ev_legacy_000001"]["content"],
            Value::String("legacy one".to_string())
        );
    }

    #[tokio::test]
    async fn test_load_legacy_rust_state_shape() {
        let tmp = tempdir().unwrap();
        fs::write(
            tmp.path().join("state.json"),
            r#"{"observations":[{"source":"wiki","timestamp":"2026-03-13T00:00:00Z","content":"one"},{"source":"tool","timestamp":"2026-03-13T00:00:01Z","content":"two"}]}"#,
        )
        .await
        .unwrap();

        let ctx = ExternalContext::load(tmp.path()).await.unwrap();
        assert_eq!(ctx.observations.len(), 2);
        assert_eq!(ctx.observations[0].source, "wiki");
        assert_eq!(ctx.observations[1].content, "two");
    }

    #[tokio::test]
    async fn test_load_typed_state_falls_back_to_evidence() {
        let tmp = tempdir().unwrap();
        fs::write(
            tmp.path().join("investigation_state.json"),
            r#"{"schema_version":"1.0.0","session_id":"sid","evidence":{"ev_legacy_000002":{"content":"two","normalization":{"kind":"legacy_observation"}},"ev_legacy_000001":{"content":"one","normalization":{"kind":"legacy_observation"}}}}"#,
        )
        .await
        .unwrap();

        let ctx = ExternalContext::load(tmp.path()).await.unwrap();
        assert_eq!(ctx.observations.len(), 2);
        assert_eq!(ctx.observations[0].content, "one");
        assert_eq!(ctx.observations[1].content, "two");
    }

    #[tokio::test]
    async fn test_invalid_typed_state_falls_back_to_legacy_python_state() {
        let tmp = tempdir().unwrap();
        let typed_path = tmp.path().join("investigation_state.json");
        let corrupt_typed = "{not-json";
        fs::write(&typed_path, corrupt_typed).await.unwrap();
        fs::write(
            tmp.path().join("state.json"),
            r#"{"session_id":"sid","external_observations":["legacy fallback"]}"#,
        )
        .await
        .unwrap();

        let ctx = ExternalContext::load(tmp.path()).await.unwrap();
        assert_eq!(ctx.observations.len(), 1);
        assert_eq!(ctx.observations[0].content, "legacy fallback");

        let state = load_or_migrate_investigation_state(tmp.path())
            .await
            .unwrap();
        assert_eq!(state.legacy.external_observations, vec!["legacy fallback"]);
        assert_eq!(
            state.evidence["ev_legacy_000001"]["content"],
            Value::String("legacy fallback".to_string())
        );
        assert_eq!(
            fs::read_to_string(&typed_path).await.unwrap(),
            corrupt_typed
        );
    }

    #[tokio::test]
    async fn test_invalid_typed_state_falls_back_to_legacy_rust_observations() {
        let tmp = tempdir().unwrap();
        let typed_path = tmp.path().join("investigation_state.json");
        fs::write(&typed_path, "{not-json").await.unwrap();
        fs::write(
            tmp.path().join("state.json"),
            r#"{"observations":[{"source":"wiki","timestamp":"2026-03-13T00:00:00Z","content":"one"},{"source":"tool","timestamp":"2026-03-13T00:00:01Z","content":"two"}]}"#,
        )
        .await
        .unwrap();

        let ctx = ExternalContext::load(tmp.path()).await.unwrap();
        assert_eq!(ctx.observations.len(), 2);
        assert_eq!(ctx.observations[0].source, "wiki");
        assert_eq!(ctx.observations[0].timestamp, "2026-03-13T00:00:00Z");
        assert_eq!(ctx.observations[1].content, "two");

        let state = load_or_migrate_investigation_state(tmp.path())
            .await
            .unwrap();
        assert_eq!(state.legacy.external_observations, vec!["one", "two"]);
        assert_eq!(fs::read_to_string(&typed_path).await.unwrap(), "{not-json");
    }

    #[tokio::test]
    async fn test_invalid_typed_state_without_legacy_returns_empty_state() {
        let tmp = tempdir().unwrap();
        let typed_path = tmp.path().join("investigation_state.json");
        fs::write(&typed_path, "{not-json").await.unwrap();

        let ctx = ExternalContext::load(tmp.path()).await.unwrap();
        assert!(ctx.observations.is_empty());

        let state = load_or_migrate_investigation_state(tmp.path())
            .await
            .unwrap();
        assert_eq!(
            state.session_id,
            tmp.path()
                .file_name()
                .and_then(|value| value.to_str())
                .unwrap_or_default()
        );
        assert!(state.legacy.external_observations.is_empty());
        assert!(state.evidence.is_empty());
        assert_eq!(fs::read_to_string(&typed_path).await.unwrap(), "{not-json");
    }

    #[tokio::test]
    async fn test_invalid_typed_state_with_malformed_legacy_remains_error() {
        let tmp = tempdir().unwrap();
        fs::write(tmp.path().join("investigation_state.json"), "{not-json")
            .await
            .unwrap();
        fs::write(tmp.path().join("state.json"), "{still-not-json")
            .await
            .unwrap();

        let ctx_err = ExternalContext::load(tmp.path()).await.unwrap_err();
        assert_eq!(ctx_err.kind(), std::io::ErrorKind::InvalidData);

        let state_err = load_or_migrate_investigation_state(tmp.path())
            .await
            .unwrap_err();
        assert_eq!(state_err.kind(), std::io::ErrorKind::InvalidData);
    }

    #[tokio::test]
    async fn test_save_preserves_existing_typed_fields_and_extra_fields() {
        let tmp = tempdir().unwrap();
        fs::write(
            tmp.path().join("investigation_state.json"),
            r#"{
  "schema_version": "1.0.0",
  "session_id": "",
  "created_at": "2026-03-13T00:00:00Z",
  "updated_at": "2026-03-13T00:00:00Z",
  "objective": "",
  "ontology": {"namespace": "openplanter.core", "version": "2026-03"},
  "entities": {},
  "links": {},
  "claims": {},
  "evidence": {
    "ev_legacy_000002": {
      "id": "ev_legacy_000002",
      "content": "stale",
      "normalization": {"kind": "legacy_observation"}
    },
    "ev_other": {
      "id": "ev_other",
      "content": "keep me",
      "normalization": {"kind": "web_fetch"}
    }
  },
  "hypotheses": {},
  "questions": {"q_1": {"id": "q_1", "question_text": "keep me"}},
  "tasks": {},
  "actions": {},
  "provenance_nodes": {},
  "confidence_profiles": {},
  "timeline": [],
  "indexes": {"by_external_ref": {}, "by_tag": {}},
  "legacy": {
    "external_observations": ["stale"],
    "turn_history": [{"turn_number": 2}],
    "loop_metrics": {"turns": 2},
    "extra_fields": {"custom_field": "persist"}
  }
}"#,
        )
        .await
        .unwrap();

        let mut ctx = ExternalContext::new();
        ctx.add_observation("wiki", "fresh");
        ctx.save(tmp.path()).await.unwrap();

        let typed: Value = serde_json::from_str(
            &fs::read_to_string(tmp.path().join("investigation_state.json"))
                .await
                .unwrap(),
        )
        .unwrap();
        assert_eq!(
            typed["questions"]["q_1"]["question_text"],
            Value::String("keep me".to_string())
        );
        assert!(typed["evidence"].get("ev_other").is_some());
        assert!(typed["evidence"].get("ev_legacy_000002").is_none());
        assert_eq!(
            typed["evidence"]["ev_legacy_000001"]["content"],
            Value::String("fresh".to_string())
        );

        let legacy: Value = serde_json::from_str(
            &fs::read_to_string(tmp.path().join("state.json"))
                .await
                .unwrap(),
        )
        .unwrap();
        assert_eq!(
            legacy["external_observations"],
            serde_json::json!(["fresh"])
        );
        assert_eq!(legacy["custom_field"], Value::String("persist".to_string()));
        assert_eq!(legacy["loop_metrics"]["turns"], Value::from(2));
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

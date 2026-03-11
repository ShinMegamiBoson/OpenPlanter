// Replay logger — append-only JSONL log of session messages.
//
// Each session directory contains a `replay.jsonl` file with one JSON object
// per line. This enables message history reload when switching sessions.

use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use tokio::fs;
use tokio::io::AsyncWriteExt;

/// A single entry in the replay log.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReplayEntry {
    pub seq: u64,
    pub timestamp: String,
    pub role: String,
    pub content: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tool_name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub is_rendered: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub step_number: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub step_tokens_in: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub step_tokens_out: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub step_elapsed: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub step_model_preview: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub step_tool_calls: Option<Vec<StepToolCallEntry>>,
}

/// A tool call within a step summary entry.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StepToolCallEntry {
    pub name: String,
    pub key_arg: String,
    pub elapsed: u64,
}

/// Append-only JSONL logger for session replay.
pub struct ReplayLogger {
    path: PathBuf,
    seq: u64,
}

impl ReplayLogger {
    /// Create a new replay logger for the given session directory.
    pub fn new(session_dir: &Path) -> Self {
        Self {
            path: session_dir.join("replay.jsonl"),
            seq: 0,
        }
    }

    /// Append an entry to the replay log.
    pub async fn append(&mut self, mut entry: ReplayEntry) -> std::io::Result<()> {
        self.seq += 1;
        entry.seq = self.seq;
        if entry.timestamp.is_empty() {
            entry.timestamp = chrono::Utc::now().to_rfc3339();
        }
        let mut line = serde_json::to_string(&entry)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;
        line.push('\n');

        let mut file = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.path)
            .await?;
        file.write_all(line.as_bytes()).await?;
        file.flush().await?;
        Ok(())
    }

    /// Read all entries from a session's replay log.
    pub async fn read_all(session_dir: &Path) -> std::io::Result<Vec<ReplayEntry>> {
        let path = session_dir.join("replay.jsonl");
        if !path.exists() {
            return Ok(vec![]);
        }
        let content = fs::read_to_string(&path).await?;
        let mut entries = Vec::new();
        for line in content.lines() {
            let trimmed = line.trim();
            if trimmed.is_empty() {
                continue;
            }
            match serde_json::from_str::<ReplayEntry>(trimmed) {
                Ok(entry) => entries.push(entry),
                Err(e) => {
                    eprintln!("[replay] skipping malformed line: {e}");
                }
            }
        }
        Ok(entries)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[tokio::test]
    async fn test_append_creates_file() {
        let tmp = tempdir().unwrap();
        let mut logger = ReplayLogger::new(tmp.path());
        let entry = ReplayEntry {
            seq: 0,
            timestamp: String::new(),
            role: "user".into(),
            content: "hello".into(),
            tool_name: None,
            is_rendered: None,
            step_number: None,
            step_tokens_in: None,
            step_tokens_out: None,
            step_elapsed: None,
            step_model_preview: None,
            step_tool_calls: None,
        };
        logger.append(entry).await.unwrap();
        assert!(tmp.path().join("replay.jsonl").exists());
    }

    #[tokio::test]
    async fn test_append_increments_seq() {
        let tmp = tempdir().unwrap();
        let mut logger = ReplayLogger::new(tmp.path());
        for _ in 0..3 {
            let entry = ReplayEntry {
                seq: 0,
                timestamp: String::new(),
                role: "user".into(),
                content: "test".into(),
                tool_name: None,
                is_rendered: None,
                step_number: None,
                step_tokens_in: None,
                step_tokens_out: None,
                step_elapsed: None,
                step_model_preview: None,
                step_tool_calls: None,
            };
            logger.append(entry).await.unwrap();
        }
        let entries = ReplayLogger::read_all(tmp.path()).await.unwrap();
        assert_eq!(entries.len(), 3);
        assert_eq!(entries[0].seq, 1);
        assert_eq!(entries[1].seq, 2);
        assert_eq!(entries[2].seq, 3);
    }

    #[tokio::test]
    async fn test_read_all_empty_dir() {
        let tmp = tempdir().unwrap();
        let entries = ReplayLogger::read_all(tmp.path()).await.unwrap();
        assert!(entries.is_empty());
    }

    #[tokio::test]
    async fn test_roundtrip_with_step_summary() {
        let tmp = tempdir().unwrap();
        let mut logger = ReplayLogger::new(tmp.path());
        let entry = ReplayEntry {
            seq: 0,
            timestamp: String::new(),
            role: "step-summary".into(),
            content: String::new(),
            tool_name: None,
            is_rendered: None,
            step_number: Some(1),
            step_tokens_in: Some(12300),
            step_tokens_out: Some(2100),
            step_elapsed: Some(5000),
            step_model_preview: Some("The analysis shows...".into()),
            step_tool_calls: Some(vec![StepToolCallEntry {
                name: "read_file".into(),
                key_arg: "/src/main.ts".into(),
                elapsed: 1200,
            }]),
        };
        logger.append(entry).await.unwrap();

        let entries = ReplayLogger::read_all(tmp.path()).await.unwrap();
        assert_eq!(entries.len(), 1);
        assert_eq!(entries[0].role, "step-summary");
        assert_eq!(entries[0].step_number, Some(1));
        assert_eq!(entries[0].step_tokens_in, Some(12300));
        let tools = entries[0].step_tool_calls.as_ref().unwrap();
        assert_eq!(tools.len(), 1);
        assert_eq!(tools[0].name, "read_file");
    }

    #[tokio::test]
    async fn test_read_all_skips_malformed_lines() {
        let tmp = tempdir().unwrap();
        let path = tmp.path().join("replay.jsonl");
        let content = format!(
            "{}\nnot valid json\n{}\n",
            serde_json::to_string(&ReplayEntry {
                seq: 1,
                timestamp: "2026-01-01T00:00:00Z".into(),
                role: "user".into(),
                content: "first".into(),
                tool_name: None,
                is_rendered: None,
                step_number: None,
                step_tokens_in: None,
                step_tokens_out: None,
                step_elapsed: None,
                step_model_preview: None,
                step_tool_calls: None,
            })
            .unwrap(),
            serde_json::to_string(&ReplayEntry {
                seq: 2,
                timestamp: "2026-01-01T00:01:00Z".into(),
                role: "assistant".into(),
                content: "second".into(),
                tool_name: None,
                is_rendered: None,
                step_number: None,
                step_tokens_in: None,
                step_tokens_out: None,
                step_elapsed: None,
                step_model_preview: None,
                step_tool_calls: None,
            })
            .unwrap(),
        );
        fs::write(&path, content).await.unwrap();

        let entries = ReplayLogger::read_all(tmp.path()).await.unwrap();
        assert_eq!(entries.len(), 2);
        assert_eq!(entries[0].content, "first");
        assert_eq!(entries[1].content, "second");
    }

    #[tokio::test]
    async fn test_timestamp_auto_filled() {
        let tmp = tempdir().unwrap();
        let mut logger = ReplayLogger::new(tmp.path());
        let entry = ReplayEntry {
            seq: 0,
            timestamp: String::new(),
            role: "user".into(),
            content: "test".into(),
            tool_name: None,
            is_rendered: None,
            step_number: None,
            step_tokens_in: None,
            step_tokens_out: None,
            step_elapsed: None,
            step_model_preview: None,
            step_tool_calls: None,
        };
        logger.append(entry).await.unwrap();
        let entries = ReplayLogger::read_all(tmp.path()).await.unwrap();
        assert!(!entries[0].timestamp.is_empty());
    }

    #[tokio::test]
    async fn test_optional_fields_omitted_in_json() {
        let tmp = tempdir().unwrap();
        let mut logger = ReplayLogger::new(tmp.path());
        let entry = ReplayEntry {
            seq: 0,
            timestamp: String::new(),
            role: "user".into(),
            content: "hello".into(),
            tool_name: None,
            is_rendered: None,
            step_number: None,
            step_tokens_in: None,
            step_tokens_out: None,
            step_elapsed: None,
            step_model_preview: None,
            step_tool_calls: None,
        };
        logger.append(entry).await.unwrap();

        let content = fs::read_to_string(tmp.path().join("replay.jsonl"))
            .await
            .unwrap();
        assert!(!content.contains("tool_name"));
        assert!(!content.contains("step_number"));
        assert!(!content.contains("step_tool_calls"));
    }
}

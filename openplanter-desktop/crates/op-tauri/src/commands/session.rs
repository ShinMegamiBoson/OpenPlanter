use crate::state::AppState;
use op_core::events::SessionInfo;
use op_core::session::replay::{ReplayEntry, ReplayLogger};
use std::fs;
use std::path::{Path, PathBuf};
use tauri::State;

/// Get the sessions directory path from config.
pub async fn sessions_dir(state: &State<'_, AppState>) -> PathBuf {
    let cfg = state.config.lock().await;
    let ws = cfg.workspace.clone();
    let root = cfg.session_root_dir.clone();
    ws.join(root).join("sessions")
}

/// Collect sessions from a directory, sorted by created_at descending, limited to `limit`.
pub fn collect_sessions(dir: &Path, limit: usize) -> Vec<SessionInfo> {
    if !dir.exists() {
        return vec![];
    }

    let mut sessions: Vec<SessionInfo> = Vec::new();

    let entries = match fs::read_dir(dir) {
        Ok(e) => e,
        Err(_) => return vec![],
    };
    for entry in entries.flatten() {
        if !entry.path().is_dir() {
            continue;
        }
        let meta_path = entry.path().join("metadata.json");
        if !meta_path.exists() {
            continue;
        }
        let content = match fs::read_to_string(&meta_path) {
            Ok(c) => c,
            Err(_) => continue,
        };
        let info: SessionInfo = match serde_json::from_str(&content) {
            Ok(i) => i,
            Err(_) => continue,
        };
        sessions.push(info);
    }

    sessions.sort_by(|a, b| b.created_at.cmp(&a.created_at));
    sessions.truncate(limit);
    sessions
}

/// Create a new session in the given directory, returning the SessionInfo.
pub fn create_session(dir: &Path) -> Result<SessionInfo, std::io::Error> {
    fs::create_dir_all(dir)?;

    let now = chrono::Utc::now();
    let new_id = format!("{}-{:08x}", now.format("%Y%m%d-%H%M%S"), rand_hex());

    let session_dir = dir.join(&new_id);
    fs::create_dir_all(&session_dir)?;
    fs::create_dir_all(session_dir.join("artifacts"))?;

    let info = SessionInfo {
        id: new_id,
        created_at: now.to_rfc3339(),
        turn_count: 0,
        last_objective: None,
    };

    let json = serde_json::to_string_pretty(&info)
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;
    fs::write(session_dir.join("metadata.json"), json)?;

    Ok(info)
}

/// List recent sessions by scanning session directories.
#[tauri::command]
pub async fn list_sessions(
    limit: Option<u32>,
    state: State<'_, AppState>,
) -> Result<Vec<SessionInfo>, String> {
    let dir = sessions_dir(&state).await;
    let cap = limit.unwrap_or(20) as usize;
    Ok(collect_sessions(&dir, cap))
}

/// Open a session (create new or resume existing).
#[tauri::command]
pub async fn open_session(
    id: Option<String>,
    resume: bool,
    state: State<'_, AppState>,
) -> Result<SessionInfo, String> {
    let dir = sessions_dir(&state).await;

    if resume {
        if let Some(ref session_id) = id {
            let meta_path = dir.join(session_id).join("metadata.json");
            if meta_path.exists() {
                let content = fs::read_to_string(&meta_path).map_err(|e| e.to_string())?;
                let info: SessionInfo =
                    serde_json::from_str(&content).map_err(|e| e.to_string())?;
                let mut session_lock = state.session_id.lock().await;
                *session_lock = Some(info.id.clone());
                return Ok(info);
            }
        }
    }

    let info = create_session(&dir).map_err(|e| e.to_string())?;
    let mut session_lock = state.session_id.lock().await;
    *session_lock = Some(info.id.clone());
    Ok(info)
}

/// Delete a session by removing its directory.
#[tauri::command]
pub async fn delete_session(id: String, state: State<'_, AppState>) -> Result<(), String> {
    let dir = sessions_dir(&state).await;
    let session_dir = dir.join(&id);

    if !session_dir.exists() {
        return Err(format!("Session '{id}' not found"));
    }
    if !session_dir.is_dir() {
        return Err(format!("Session '{id}' is not a directory"));
    }
    // Ensure it's actually a session directory (has metadata.json)
    if !session_dir.join("metadata.json").exists() {
        return Err(format!(
            "Session '{id}' has no metadata — refusing to delete"
        ));
    }

    fs::remove_dir_all(&session_dir).map_err(|e| format!("Failed to delete session: {e}"))?;

    // If the deleted session is the current one, clear the active session
    let mut session_lock = state.session_id.lock().await;
    if session_lock.as_deref() == Some(id.as_str()) {
        *session_lock = None;
    }

    Ok(())
}

/// Get message history for a session from replay.jsonl.
#[tauri::command]
pub async fn get_session_history(
    session_id: String,
    state: State<'_, AppState>,
) -> Result<Vec<ReplayEntry>, String> {
    let dir = sessions_dir(&state).await.join(&session_id);
    ReplayLogger::read_all(&dir)
        .await
        .map_err(|e| e.to_string())
}

/// Update session metadata: increment turn_count, set last_objective.
pub async fn update_session_metadata(
    session_dir: &Path,
    objective: &str,
) -> Result<(), std::io::Error> {
    let meta_path = session_dir.join("metadata.json");
    if !meta_path.exists() {
        return Ok(());
    }
    let content = tokio::fs::read_to_string(&meta_path).await?;
    let mut info: SessionInfo = serde_json::from_str(&content)
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))?;
    info.turn_count += 1;
    info.last_objective = Some(if objective.len() > 100 {
        format!("{}...", &objective[..97])
    } else {
        objective.to_string()
    });
    let json = serde_json::to_string_pretty(&info)
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;
    tokio::fs::write(&meta_path, json).await
}

/// Simple pseudo-random hex value using system time.
fn rand_hex() -> u32 {
    use std::time::{SystemTime, UNIX_EPOCH};
    let d = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default();
    // Mix nanos for some randomness
    (d.subsec_nanos() ^ 0xDEAD_BEEF) & 0xFFFF_FFFF
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn write_session(dir: &Path, id: &str, created_at: &str) {
        let session_dir = dir.join(id);
        fs::create_dir_all(session_dir.join("artifacts")).unwrap();
        let info = SessionInfo {
            id: id.to_string(),
            created_at: created_at.to_string(),
            turn_count: 0,
            last_objective: None,
        };
        let json = serde_json::to_string_pretty(&info).unwrap();
        fs::write(session_dir.join("metadata.json"), json).unwrap();
    }

    // ── collect_sessions ──

    #[test]
    fn test_empty_dir_returns_empty() {
        let tmp = tempdir().unwrap();
        let sessions_dir = tmp.path().join("sessions");
        fs::create_dir_all(&sessions_dir).unwrap();
        let result = collect_sessions(&sessions_dir, 20);
        assert!(result.is_empty());
    }

    #[test]
    fn test_nonexistent_dir_returns_empty() {
        let tmp = tempdir().unwrap();
        let result = collect_sessions(&tmp.path().join("nope"), 20);
        assert!(result.is_empty());
    }

    #[test]
    fn test_single_session() {
        let tmp = tempdir().unwrap();
        let dir = tmp.path().join("sessions");
        fs::create_dir_all(&dir).unwrap();
        write_session(&dir, "20260101-120000-deadbeef", "2026-01-01T12:00:00Z");
        let result = collect_sessions(&dir, 20);
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].id, "20260101-120000-deadbeef");
    }

    #[test]
    fn test_multiple_sessions_sorted_desc() {
        let tmp = tempdir().unwrap();
        let dir = tmp.path().join("sessions");
        fs::create_dir_all(&dir).unwrap();
        write_session(&dir, "s1", "2026-01-01T10:00:00Z");
        write_session(&dir, "s2", "2026-01-01T12:00:00Z");
        write_session(&dir, "s3", "2026-01-01T11:00:00Z");
        let result = collect_sessions(&dir, 20);
        assert_eq!(result.len(), 3);
        assert_eq!(result[0].id, "s2"); // most recent
        assert_eq!(result[1].id, "s3");
        assert_eq!(result[2].id, "s1"); // oldest
    }

    #[test]
    fn test_limit_truncates() {
        let tmp = tempdir().unwrap();
        let dir = tmp.path().join("sessions");
        fs::create_dir_all(&dir).unwrap();
        for i in 0..5 {
            write_session(
                &dir,
                &format!("s{}", i),
                &format!("2026-01-01T1{}:00:00Z", i),
            );
        }
        let result = collect_sessions(&dir, 2);
        assert_eq!(result.len(), 2);
    }

    #[test]
    fn test_skips_dirs_without_metadata() {
        let tmp = tempdir().unwrap();
        let dir = tmp.path().join("sessions");
        fs::create_dir_all(dir.join("no-metadata")).unwrap();
        write_session(&dir, "has-meta", "2026-01-01T12:00:00Z");
        let result = collect_sessions(&dir, 20);
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].id, "has-meta");
    }

    #[test]
    fn test_skips_invalid_json() {
        let tmp = tempdir().unwrap();
        let dir = tmp.path().join("sessions");
        let bad_dir = dir.join("bad-json");
        fs::create_dir_all(&bad_dir).unwrap();
        fs::write(bad_dir.join("metadata.json"), "not valid json").unwrap();
        write_session(&dir, "good", "2026-01-01T12:00:00Z");
        let result = collect_sessions(&dir, 20);
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].id, "good");
    }

    #[test]
    fn test_skips_non_directories() {
        let tmp = tempdir().unwrap();
        let dir = tmp.path().join("sessions");
        fs::create_dir_all(&dir).unwrap();
        fs::write(dir.join("some-file.txt"), "not a dir").unwrap();
        write_session(&dir, "real-session", "2026-01-01T12:00:00Z");
        let result = collect_sessions(&dir, 20);
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].id, "real-session");
    }

    // ── create_session ──

    #[test]
    fn test_creates_session_dir() {
        let tmp = tempdir().unwrap();
        let dir = tmp.path().join("sessions");
        let info = create_session(&dir).unwrap();
        let session_dir = dir.join(&info.id);
        assert!(session_dir.exists(), "session dir should exist");
        assert!(
            session_dir.join("artifacts").exists(),
            "artifacts/ should exist"
        );
        assert!(
            session_dir.join("metadata.json").exists(),
            "metadata.json should exist"
        );
    }

    #[test]
    fn test_session_id_format() {
        let tmp = tempdir().unwrap();
        let dir = tmp.path().join("sessions");
        let info = create_session(&dir).unwrap();
        // ID should match YYYYMMDD-HHMMSS-hex
        let re = regex::Regex::new(r"^\d{8}-\d{6}-[0-9a-f]{8}$").unwrap();
        assert!(
            re.is_match(&info.id),
            "session ID '{}' doesn't match expected format",
            info.id
        );
    }

    #[test]
    fn test_metadata_json_valid() {
        let tmp = tempdir().unwrap();
        let dir = tmp.path().join("sessions");
        let info = create_session(&dir).unwrap();
        let meta_path = dir.join(&info.id).join("metadata.json");
        let content = fs::read_to_string(&meta_path).unwrap();
        let deserialized: SessionInfo = serde_json::from_str(&content).unwrap();
        assert_eq!(deserialized.id, info.id);
    }

    #[test]
    fn test_session_turn_count_zero() {
        let tmp = tempdir().unwrap();
        let dir = tmp.path().join("sessions");
        let info = create_session(&dir).unwrap();
        assert_eq!(info.turn_count, 0);
        assert!(info.last_objective.is_none());
    }

    // ── delete_session helpers ──

    #[test]
    fn test_delete_session_removes_dir() {
        let tmp = tempdir().unwrap();
        let dir = tmp.path().join("sessions");
        write_session(&dir, "to-delete", "2026-01-01T12:00:00Z");
        assert!(dir.join("to-delete").exists());
        fs::remove_dir_all(dir.join("to-delete")).unwrap();
        assert!(!dir.join("to-delete").exists());
        // Verify it's gone from collect_sessions too
        let sessions = collect_sessions(&dir, 20);
        assert!(sessions.is_empty());
    }

    #[test]
    fn test_delete_session_does_not_affect_others() {
        let tmp = tempdir().unwrap();
        let dir = tmp.path().join("sessions");
        write_session(&dir, "keep-me", "2026-01-01T12:00:00Z");
        write_session(&dir, "delete-me", "2026-01-01T13:00:00Z");
        fs::remove_dir_all(dir.join("delete-me")).unwrap();
        let sessions = collect_sessions(&dir, 20);
        assert_eq!(sessions.len(), 1);
        assert_eq!(sessions[0].id, "keep-me");
    }
}

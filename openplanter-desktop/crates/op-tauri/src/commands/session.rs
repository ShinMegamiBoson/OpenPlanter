use std::fs;
use std::path::PathBuf;
use tauri::State;
use crate::state::AppState;
use op_core::events::SessionInfo;

/// Get the sessions directory path from config.
async fn sessions_dir(state: &State<'_, AppState>) -> PathBuf {
    let cfg = state.config.lock().await;
    let ws = cfg.workspace.clone();
    let root = cfg.session_root_dir.clone();
    ws.join(root).join("sessions")
}

/// List recent sessions by scanning session directories.
#[tauri::command]
pub async fn list_sessions(
    limit: Option<u32>,
    state: State<'_, AppState>,
) -> Result<Vec<SessionInfo>, String> {
    let dir = sessions_dir(&state).await;
    if !dir.exists() {
        return Ok(vec![]);
    }

    let mut sessions: Vec<SessionInfo> = Vec::new();

    let entries = fs::read_dir(&dir).map_err(|e| e.to_string())?;
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

    // Sort by created_at descending
    sessions.sort_by(|a, b| b.created_at.cmp(&a.created_at));

    let cap = limit.unwrap_or(20) as usize;
    sessions.truncate(cap);

    Ok(sessions)
}

/// Open a session (create new or resume existing).
#[tauri::command]
pub async fn open_session(
    id: Option<String>,
    resume: bool,
    state: State<'_, AppState>,
) -> Result<SessionInfo, String> {
    let dir = sessions_dir(&state).await;
    let _ = fs::create_dir_all(&dir);

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

    // Generate new session ID: YYYYMMDD-HHMMSS-hex
    let now = chrono::Utc::now();
    let new_id = format!(
        "{}-{:08x}",
        now.format("%Y%m%d-%H%M%S"),
        rand_hex()
    );

    let session_dir = dir.join(&new_id);
    fs::create_dir_all(&session_dir).map_err(|e| e.to_string())?;
    fs::create_dir_all(session_dir.join("artifacts")).map_err(|e| e.to_string())?;

    let info = SessionInfo {
        id: new_id.clone(),
        created_at: now.to_rfc3339(),
        turn_count: 0,
        last_objective: None,
    };

    let json = serde_json::to_string_pretty(&info).map_err(|e| e.to_string())?;
    fs::write(session_dir.join("metadata.json"), json).map_err(|e| e.to_string())?;

    let mut session_lock = state.session_id.lock().await;
    *session_lock = Some(new_id);

    Ok(info)
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

use tauri::State;
use crate::state::AppState;
use op_core::events::SessionInfo;

/// List recent sessions.
#[tauri::command]
pub async fn list_sessions(
    limit: Option<u32>,
    _state: State<'_, AppState>,
) -> Result<Vec<SessionInfo>, String> {
    // Phase 5: scan session directories
    let _ = limit;
    Ok(vec![])
}

/// Open a session (create new or resume).
#[tauri::command]
pub async fn open_session(
    id: Option<String>,
    resume: bool,
    state: State<'_, AppState>,
) -> Result<SessionInfo, String> {
    // Phase 5: create/resume session
    let _ = (id, resume);
    let new_id = uuid::Uuid::new_v4().to_string();
    let mut session_id = state.session_id.lock().await;
    *session_id = Some(new_id.clone());
    Ok(SessionInfo {
        id: new_id,
        created_at: chrono::Utc::now().to_rfc3339(),
        turn_count: 0,
        last_objective: None,
    })
}

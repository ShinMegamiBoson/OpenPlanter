use tauri::State;
use crate::state::AppState;

/// Start solving an objective. Result streamed via events.
#[tauri::command]
pub async fn solve(
    objective: String,
    _state: State<'_, AppState>,
) -> Result<(), String> {
    // Phase 6: spawn tokio task, run engine, stream events
    let _ = objective;
    Ok(())
}

/// Cancel a running solve.
#[tauri::command]
pub async fn cancel(
    _state: State<'_, AppState>,
) -> Result<(), String> {
    // Phase 6: set cancellation token
    Ok(())
}

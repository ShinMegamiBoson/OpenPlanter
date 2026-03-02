use tauri::{AppHandle, Emitter, State};
use tokio_util::sync::CancellationToken;

use crate::bridge::{LoggingEmitter, TauriEmitter};
use crate::commands::session::sessions_dir;
use crate::state::AppState;
use op_core::session::replay::{ReplayEntry, ReplayLogger};

/// Start solving an objective. Result streamed via events.
#[tauri::command]
pub async fn solve(
    objective: String,
    session_id: String,
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<(), String> {
    // Create a fresh cancellation token for this solve run
    let token = CancellationToken::new();
    {
        let mut current = state.cancel_token.lock().await;
        *current = token.clone();
    }

    let cfg = state.config.lock().await.clone();
    let error_handle = app.clone();

    // Set up replay logging for this session
    let session_dir = sessions_dir(&state).await.join(&session_id);
    let mut replay = ReplayLogger::new(&session_dir);

    // Log the user message
    let user_entry = ReplayEntry {
        seq: 0,
        timestamp: String::new(),
        role: "user".into(),
        content: objective.clone(),
        tool_name: None,
        is_rendered: None,
        step_number: None,
        step_tokens_in: None,
        step_tokens_out: None,
        step_elapsed: None,
        step_model_preview: None,
        step_tool_calls: None,
    };
    if let Err(e) = replay.append(user_entry).await {
        eprintln!("[agent] failed to log user message: {e}");
    }

    // Update metadata: increment turn_count, set last_objective
    if let Err(e) =
        crate::commands::session::update_session_metadata(&session_dir, &objective).await
    {
        eprintln!("[agent] failed to update metadata: {e}");
    }

    let emitter = LoggingEmitter::new(TauriEmitter::new(app), replay);

    tokio::spawn(async move {
        let result = tokio::spawn(async move {
            op_core::engine::solve(&objective, &cfg, &emitter, token).await;
        })
        .await;

        // If the inner task panicked, emit an error so the frontend
        // doesn't get stuck in "running" state forever.
        if let Err(e) = result {
            let msg = format!("Internal error: {e}");
            eprintln!("[bridge] panic: {msg}");
            let _ = error_handle.emit(
                "agent:error",
                op_core::events::ErrorEvent {
                    message: msg,
                },
            );
        }
    });

    Ok(())
}

/// Cancel a running solve.
#[tauri::command]
pub async fn cancel(
    state: State<'_, AppState>,
) -> Result<(), String> {
    let token = state.cancel_token.lock().await;
    token.cancel();
    Ok(())
}

/// Debug logging from frontend (temporary).
#[tauri::command]
pub async fn debug_log(msg: String) -> Result<(), String> {
    eprintln!("[frontend] {msg}");
    Ok(())
}

use std::path::Path;

use tauri::{AppHandle, Emitter, State};
use tokio_util::sync::CancellationToken;

use crate::bridge::{LoggingEmitter, TauriEmitter};
use crate::commands::session::sessions_dir;
use crate::state::AppState;
use op_core::engine::context::load_or_migrate_investigation_state;
use op_core::engine::investigation_state::{
    build_question_reasoning_packet, has_reasoning_content,
};
use op_core::engine::{SolveEmitter, SolveInitialContext};
use op_core::session::replay::{ReplayEntry, ReplayLogger};
use op_core::workspace_init;

async fn build_solve_initial_context(
    session_dir: &Path,
    session_id: &str,
) -> (SolveInitialContext, Option<String>) {
    let mut initial_context = SolveInitialContext {
        session_id: Some(session_id.to_string()),
        session_dir: Some(session_dir.display().to_string()),
        question_reasoning_packet: None,
    };

    match load_or_migrate_investigation_state(session_dir).await {
        Ok(state) => {
            let packet = build_question_reasoning_packet(&state, 8, 6);
            if has_reasoning_content(&packet) {
                initial_context.question_reasoning_packet = Some(packet);
            }
            (initial_context, None)
        }
        Err(err) => (
            initial_context,
            Some(format!(
                "[solve] failed to load investigation state for reasoning packet; continuing without packet: {err}"
            )),
        ),
    }
}

/// Start solving an objective. Result streamed via events.
#[tauri::command]
pub async fn solve(
    objective: String,
    session_id: String,
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<(), String> {
    let cfg = state.config.lock().await.clone();
    let init_status = workspace_init::get_init_status(&cfg.workspace, &cfg.session_root_dir)
        .map_err(|e| e.to_string())?;
    if init_status.gate_state != "ready" {
        return Err("Workspace initialization is not complete. Run /init first.".to_string());
    }

    {
        let mut running = state.agent_running.lock().await;
        if *running {
            return Err("An agent task is already running.".to_string());
        }
        *running = true;
    }

    // Create a fresh cancellation token for this solve run
    let token = CancellationToken::new();
    {
        let mut current = state.cancel_token.lock().await;
        *current = token.clone();
    }
    let error_handle = app.clone();
    let running_flag = state.agent_running.clone();

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
    let cwd = std::env::current_dir()
        .map(|dir| dir.display().to_string())
        .unwrap_or_else(|_| "<unavailable>".to_string());
    emitter.emit_trace(&format!(
        "[solve] pid={} cwd={} workspace={} session={}",
        std::process::id(),
        cwd,
        cfg.workspace.display(),
        session_id
    ));
    emitter.emit_trace(&format!("[startup:info] {}", state.startup_trace()));
    let (initial_context, initial_context_warning) =
        build_solve_initial_context(&session_dir, &session_id).await;
    if let Some(warning) = initial_context_warning.as_deref() {
        emitter.emit_trace(warning);
    }

    tokio::spawn(async move {
        let result = tokio::spawn(async move {
            op_core::engine::solve_with_initial_context(
                &objective,
                &cfg,
                &emitter,
                token,
                Some(initial_context),
            )
            .await;
        })
        .await;

        {
            let mut running = running_flag.lock().await;
            *running = false;
        }

        // If the inner task panicked, emit an error so the frontend
        // doesn't get stuck in "running" state forever.
        if let Err(e) = result {
            let msg = format!("Internal error: {e}");
            eprintln!("[bridge] panic: {msg}");
            let _ = error_handle.emit("agent:error", op_core::events::ErrorEvent { message: msg });
        }
    });

    Ok(())
}

/// Cancel a running solve.
#[tauri::command]
pub async fn cancel(state: State<'_, AppState>) -> Result<(), String> {
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

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;
    use tokio::fs;

    #[tokio::test]
    async fn test_build_solve_initial_context_includes_packet_when_state_has_reasoning() {
        let tmp = tempdir().unwrap();
        fs::write(
            tmp.path().join("investigation_state.json"),
            r#"{
                "schema_version":"1.0.0",
                "session_id":"sid",
                "questions":{"q_1":{"id":"q_1","question_text":"Open question","status":"open","priority":"high","claim_ids":["cl_1"]}},
                "claims":{"cl_1":{"id":"cl_1","claim_text":"Needs support","status":"unresolved","evidence_ids":["ev_1"]}},
                "evidence":{"ev_1":{"id":"ev_1","evidence_type":"web_fetch","source_uri":"https://example.test","provenance_ids":["pv_1"]}}
            }"#,
        )
        .await
        .unwrap();

        let (context, warning) = build_solve_initial_context(tmp.path(), "sid").await;
        assert!(warning.is_none());
        let packet = context
            .question_reasoning_packet
            .expect("packet should be present");
        assert_eq!(packet["focus_question_ids"], serde_json::json!(["q_1"]));
        assert_eq!(
            packet["candidate_actions"][0]["id"],
            serde_json::json!("ca_q_q_1")
        );
        assert_eq!(context.session_id, Some("sid".to_string()));
        assert_eq!(context.session_dir, Some(tmp.path().display().to_string()));
    }

    #[tokio::test]
    async fn test_build_solve_initial_context_ignores_invalid_typed_state_without_warning() {
        let tmp = tempdir().unwrap();
        fs::write(tmp.path().join("investigation_state.json"), "{not-json")
            .await
            .unwrap();

        let (context, warning) = build_solve_initial_context(tmp.path(), "sid").await;
        assert!(warning.is_none());
        assert!(context.question_reasoning_packet.is_none());
        assert_eq!(context.session_id, Some("sid".to_string()));
        assert_eq!(context.session_dir, Some(tmp.path().display().to_string()));
    }
}

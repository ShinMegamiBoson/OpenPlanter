use std::path::PathBuf;
use std::process::Command;

use serde_json::Value;
use tauri::State;

use crate::state::AppState;
use op_core::events::SlashResult;

fn python_bin() -> String {
    std::env::var("OPENPLANTER_PYTHON")
        .ok()
        .filter(|s| !s.trim().is_empty())
        .unwrap_or_else(|| "python3".to_string())
}

fn repo_root() -> PathBuf {
    // When running `cargo tauri dev` the current directory is the repo root.
    // For built binaries, walk up from the executable until we find `agent`.
    if let Ok(mut d) = std::env::current_dir() {
        loop {
            if d.join("agent").is_dir() {
                return d;
            }
            if !d.pop() {
                break;
            }
        }
    }
    if let Ok(exe) = std::env::current_exe() {
        let mut d = exe
            .parent()
            .map(|p| p.to_path_buf())
            .unwrap_or_else(|| PathBuf::from("."));
        for _ in 0..4 {
            if d.join("agent").is_dir() {
                return d;
            }
            if !d.pop() {
                break;
            }
        }
    }
    PathBuf::from(".")
}

fn to_slash_result(value: Value) -> SlashResult {
    if value.get("ok").and_then(|v| v.as_bool()).unwrap_or(false) {
        let output = value
            .get("task")
            .or_else(|| value.get("tasks"))
            .or_else(|| value.get("trusted"))
            .map(|v| serde_json::to_string_pretty(v).unwrap_or_else(|_| v.to_string()))
            .unwrap_or_else(|| value.to_string());
        SlashResult {
            output,
            success: true,
        }
    } else {
        SlashResult {
            output: value
                .get("error")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown crowd error")
                .to_string(),
            success: false,
        }
    }
}

fn run_crowd_blocking(
    workspace: String,
    session_root: String,
    args: Vec<String>,
) -> Result<Value, String> {
    let wd = repo_root();
    let mut cmd = Command::new(python_bin());
    cmd.arg("-m")
        .arg("agent.crowd_cli")
        .arg("--workspace")
        .arg(&workspace)
        .env("OPENPLANTER_SESSION_DIR", &session_root)
        .current_dir(&wd)
        .args(&args);

    let output = cmd
        .output()
        .map_err(|e| format!("failed to run crowd cli: {e}"))?;
    if !output.stderr.is_empty() {
        let err = String::from_utf8_lossy(&output.stderr);
        if !err.trim().is_empty() {
            eprintln!("[crowd-cli stderr] {}", err);
        }
    }
    let stdout = String::from_utf8_lossy(&output.stdout);
    serde_json::from_str::<Value>(&stdout)
        .map_err(|e| format!("invalid JSON from crowd cli: {e} (stdout: {stdout})"))
}

/// Publish a crowd task from the desktop app.
#[tauri::command]
pub async fn crowd_publish(
    input: String,
    state: State<'_, AppState>,
) -> Result<SlashResult, String> {
    let cfg = state.config.lock().await;
    let workspace = cfg.workspace.display().to_string();
    let session_root = cfg.session_root_dir.clone();
    drop(cfg);

    let mut args = vec!["publish".to_string()];
    args.extend(input.split_whitespace().map(String::from));

    let output =
        tokio::task::spawn_blocking(move || run_crowd_blocking(workspace, session_root, args))
            .await
            .map_err(|e| format!("crowd cli task panicked: {e}"))?;

    Ok(to_slash_result(output?))
}

/// List crowd tasks.
#[tauri::command]
pub async fn crowd_list(
    status: Option<String>,
    tags: Option<Vec<String>>,
    state: State<'_, AppState>,
) -> Result<Value, String> {
    let cfg = state.config.lock().await;
    let workspace = cfg.workspace.display().to_string();
    let session_root = cfg.session_root_dir.clone();
    drop(cfg);

    let mut args = vec!["list".to_string()];
    if let Some(s) = status {
        args.push("--status".to_string());
        args.push(s);
    } else {
        args.push("--open".to_string());
    }
    if let Some(t) = tags {
        args.push("--tags".to_string());
        args.extend(t);
    }

    let output =
        tokio::task::spawn_blocking(move || run_crowd_blocking(workspace, session_root, args))
            .await
            .map_err(|e| format!("crowd cli task panicked: {e}"))?;

    let value = output?;
    if value.get("ok").and_then(|v| v.as_bool()).unwrap_or(false) {
        Ok(serde_json::json!({ "tasks": value.get("tasks").cloned().unwrap_or(Value::Array(vec![])) }))
    } else {
        Err(value
            .get("error")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown crowd error")
            .to_string())
    }
}

/// Claim a crowd task.
#[tauri::command]
pub async fn crowd_claim(hash: String, state: State<'_, AppState>) -> Result<SlashResult, String> {
    let cfg = state.config.lock().await;
    let workspace = cfg.workspace.display().to_string();
    let session_root = cfg.session_root_dir.clone();
    drop(cfg);

    let output = tokio::task::spawn_blocking(move || {
        run_crowd_blocking(workspace, session_root, vec!["claim".to_string(), hash])
    })
    .await
    .map_err(|e| format!("crowd cli task panicked: {e}"))?;

    Ok(to_slash_result(output?))
}

/// Cancel a crowd task.
#[tauri::command]
pub async fn crowd_cancel(hash: String, state: State<'_, AppState>) -> Result<SlashResult, String> {
    let cfg = state.config.lock().await;
    let workspace = cfg.workspace.display().to_string();
    let session_root = cfg.session_root_dir.clone();
    drop(cfg);

    let output = tokio::task::spawn_blocking(move || {
        run_crowd_blocking(workspace, session_root, vec!["cancel".to_string(), hash])
    })
    .await
    .map_err(|e| format!("crowd cli task panicked: {e}"))?;

    Ok(to_slash_result(output?))
}

/// Trust a worker public key.
#[tauri::command]
pub async fn crowd_trust(npub: String, state: State<'_, AppState>) -> Result<SlashResult, String> {
    let cfg = state.config.lock().await;
    let workspace = cfg.workspace.display().to_string();
    let session_root = cfg.session_root_dir.clone();
    drop(cfg);

    let output = tokio::task::spawn_blocking(move || {
        run_crowd_blocking(workspace, session_root, vec!["trust".to_string(), npub])
    })
    .await
    .map_err(|e| format!("crowd cli task panicked: {e}"))?;

    Ok(to_slash_result(output?))
}

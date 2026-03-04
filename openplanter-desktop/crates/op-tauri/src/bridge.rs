// Bridge between engine callbacks and Tauri events.
//
// TauriEmitter wraps an AppHandle and implements SolveEmitter so that
// the engine can stream events to the frontend without depending on Tauri.
//
// LoggingEmitter wraps any SolveEmitter + ReplayLogger to persist messages
// to replay.jsonl as they stream.

use std::sync::{Arc, Mutex};
use tauri::{AppHandle, Emitter};

use op_core::engine::SolveEmitter;
use op_core::events::{CompleteEvent, DeltaEvent, DeltaKind, ErrorEvent, StepEvent, TraceEvent};
use op_core::session::replay::{ReplayEntry, ReplayLogger, StepToolCallEntry};

pub struct TauriEmitter {
    handle: AppHandle,
}

impl TauriEmitter {
    pub fn new(handle: AppHandle) -> Self {
        Self { handle }
    }
}

impl SolveEmitter for TauriEmitter {
    fn emit_trace(&self, message: &str) {
        eprintln!("[bridge] trace: {message}");
        let _ = self.handle.emit(
            "agent:trace",
            TraceEvent {
                message: message.to_string(),
            },
        );
    }

    fn emit_delta(&self, event: DeltaEvent) {
        eprintln!("[bridge] delta: kind={:?} text={:?}", event.kind, event.text);
        let _ = self.handle.emit("agent:delta", event);
    }

    fn emit_step(&self, event: StepEvent) {
        eprintln!("[bridge] step: depth={} step={} is_final={}", event.depth, event.step, event.is_final);
        let _ = self.handle.emit("agent:step", event);
    }

    fn emit_complete(&self, result: &str) {
        eprintln!("[bridge] complete: {result}");
        let _ = self.handle.emit(
            "agent:complete",
            CompleteEvent {
                result: result.to_string(),
            },
        );
    }

    fn emit_error(&self, message: &str) {
        eprintln!("[bridge] error: {message}");
        let _ = self.handle.emit(
            "agent:error",
            ErrorEvent {
                message: message.to_string(),
            },
        );
    }
}

/// Wraps any SolveEmitter + ReplayLogger to persist events as they stream.
///
/// Collects streaming text and tool calls during a step, then logs
/// the full step summary and final assistant message to replay.jsonl.
pub struct LoggingEmitter<E: SolveEmitter> {
    inner: E,
    replay: Arc<tokio::sync::Mutex<ReplayLogger>>,
    /// Accumulated streaming text for the current step (std::sync for non-async ops).
    streaming_buf: Mutex<String>,
    /// Tool calls accumulated during the current step.
    step_tool_calls: Mutex<Vec<PendingToolCall>>,
    /// Name of the tool currently being generated.
    current_tool: Mutex<String>,
    /// Accumulated args JSON for the current tool.
    current_args_buf: Mutex<String>,
}

/// A tool call being accumulated during streaming.
struct PendingToolCall {
    name: String,
    key_arg: String,
    start_time: std::time::Instant,
}

/// Key argument names for tool call display (mirrors frontend KEY_ARGS).
fn extract_key_arg(tool_name: &str, args_json: &str) -> Option<String> {
    let key_name = match tool_name {
        "read_file" | "write_file" | "edit_file" | "apply_patch" | "hashline_edit" => "path",
        "list_files" => "directory",
        "run_shell" | "run_shell_bg" => "command",
        "kill_shell_bg" => "pid",
        "web_search" => "query",
        "fetch_url" => "url",
        _ => return None,
    };
    let pattern = format!("\"{}\"\\s*:\\s*\"([^\"]*)\"?", regex::escape(key_name));
    let re = regex::Regex::new(&pattern).ok()?;
    re.captures(args_json).map(|c| c[1].to_string())
}

impl<E: SolveEmitter> LoggingEmitter<E> {
    pub fn new(inner: E, replay: ReplayLogger) -> Self {
        Self {
            inner,
            replay: Arc::new(tokio::sync::Mutex::new(replay)),
            streaming_buf: Mutex::new(String::new()),
            step_tool_calls: Mutex::new(Vec::new()),
            current_tool: Mutex::new(String::new()),
            current_args_buf: Mutex::new(String::new()),
        }
    }
}

impl<E: SolveEmitter> SolveEmitter for LoggingEmitter<E> {
    fn emit_trace(&self, message: &str) {
        self.inner.emit_trace(message);
    }

    fn emit_delta(&self, event: DeltaEvent) {
        // Accumulate streaming data for step summary logging (sync — no I/O)
        match event.kind {
            DeltaKind::Text => {
                self.streaming_buf.lock().unwrap().push_str(&event.text);
            }
            DeltaKind::ToolCallStart => {
                let tool_name = event.text.clone();
                *self.current_tool.lock().unwrap() = tool_name.clone();
                *self.current_args_buf.lock().unwrap() = String::new();
                self.step_tool_calls.lock().unwrap().push(PendingToolCall {
                    name: tool_name,
                    key_arg: String::new(),
                    start_time: std::time::Instant::now(),
                });
            }
            DeltaKind::ToolCallArgs => {
                let mut buf = self.current_args_buf.lock().unwrap();
                buf.push_str(&event.text);
                let tool_name = self.current_tool.lock().unwrap().clone();
                if let Some(key_arg) = extract_key_arg(&tool_name, &buf) {
                    let mut calls = self.step_tool_calls.lock().unwrap();
                    if let Some(last) = calls.last_mut() {
                        last.key_arg = key_arg;
                    }
                }
            }
            DeltaKind::Thinking => {}
        }

        self.inner.emit_delta(event);
    }

    fn emit_step(&self, event: StepEvent) {
        // Collect accumulated data (sync)
        let model_preview = {
            let buf = self.streaming_buf.lock().unwrap();
            let trimmed = buf.trim().to_string();
            if trimmed.is_empty() { None } else { Some(trimmed) }
        };

        let step_tools: Vec<StepToolCallEntry> = {
            let calls = self.step_tool_calls.lock().unwrap();
            calls
                .iter()
                .map(|tc| StepToolCallEntry {
                    name: tc.name.clone(),
                    key_arg: tc.key_arg.clone(),
                    elapsed: tc.start_time.elapsed().as_millis() as u64,
                })
                .collect()
        };

        let entry = ReplayEntry {
            seq: 0,
            timestamp: String::new(),
            role: "step-summary".into(),
            content: String::new(),
            tool_name: None,
            is_rendered: None,
            step_number: Some(event.step),
            step_tokens_in: Some(event.tokens.input_tokens),
            step_tokens_out: Some(event.tokens.output_tokens),
            step_elapsed: Some(event.elapsed_ms),
            step_model_preview: model_preview,
            step_tool_calls: if step_tools.is_empty() {
                None
            } else {
                Some(step_tools)
            },
        };

        // Async file I/O — use block_in_place only for this
        let replay = self.replay.clone();
        tokio::task::block_in_place(|| {
            tokio::runtime::Handle::current().block_on(async {
                if let Err(e) = replay.lock().await.append(entry).await {
                    eprintln!("[bridge] failed to log step: {e}");
                }
            });
        });

        // Reset buffers for next step
        self.streaming_buf.lock().unwrap().clear();
        self.step_tool_calls.lock().unwrap().clear();

        self.inner.emit_step(event);
    }

    fn emit_complete(&self, result: &str) {
        let entry = ReplayEntry {
            seq: 0,
            timestamp: String::new(),
            role: "assistant".into(),
            content: result.to_string(),
            tool_name: None,
            is_rendered: Some(true),
            step_number: None,
            step_tokens_in: None,
            step_tokens_out: None,
            step_elapsed: None,
            step_model_preview: None,
            step_tool_calls: None,
        };

        // Async file I/O
        let replay = self.replay.clone();
        tokio::task::block_in_place(|| {
            tokio::runtime::Handle::current().block_on(async {
                if let Err(e) = replay.lock().await.append(entry).await {
                    eprintln!("[bridge] failed to log complete: {e}");
                }
            });
        });

        self.inner.emit_complete(result);
    }

    fn emit_error(&self, message: &str) {
        self.inner.emit_error(message);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use op_core::engine::demo_solve;
    use op_core::session::replay::ReplayLogger;
    use tempfile::tempdir;
    use tokio_util::sync::CancellationToken;

    /// No-op emitter for testing LoggingEmitter without Tauri.
    struct NullEmitter;

    impl SolveEmitter for NullEmitter {
        fn emit_trace(&self, _: &str) {}
        fn emit_delta(&self, _: DeltaEvent) {}
        fn emit_step(&self, _: StepEvent) {}
        fn emit_complete(&self, _: &str) {}
        fn emit_error(&self, _: &str) {}
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn test_logging_emitter_persists_replay() {
        let tmp = tempdir().unwrap();
        let replay = ReplayLogger::new(tmp.path());
        let emitter = LoggingEmitter::new(NullEmitter, replay);
        let token = CancellationToken::new();

        demo_solve("Test persistence", &emitter, token).await;

        let entries = ReplayLogger::read_all(tmp.path()).await.unwrap();
        assert!(
            entries.len() >= 2,
            "expected at least 2 replay entries (step-summary + assistant), got {}",
            entries.len()
        );

        let step = entries.iter().find(|e| e.role == "step-summary");
        assert!(step.is_some(), "expected a step-summary entry");
        let step = step.unwrap();
        assert_eq!(step.step_number, Some(1));
        assert!(step.step_tokens_in.is_some());
        assert!(step.step_model_preview.is_some());
        assert!(step.step_model_preview.as_ref().unwrap().contains("Test persistence"));

        let assistant = entries.iter().find(|e| e.role == "assistant");
        assert!(assistant.is_some(), "expected an assistant entry");
        assert!(assistant.unwrap().content.contains("Test persistence"));
        assert_eq!(assistant.unwrap().is_rendered, Some(true));
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn test_logging_emitter_cancel_no_crash() {
        let tmp = tempdir().unwrap();
        let replay = ReplayLogger::new(tmp.path());
        let emitter = LoggingEmitter::new(NullEmitter, replay);
        let token = CancellationToken::new();
        token.cancel();

        demo_solve("Cancel test", &emitter, token).await;

        let entries = ReplayLogger::read_all(tmp.path()).await.unwrap();
        assert!(entries.len() <= 2);
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn test_full_session_roundtrip() {
        let tmp = tempdir().unwrap();

        // 1. Log user message
        let mut replay = ReplayLogger::new(tmp.path());
        replay.append(ReplayEntry {
            seq: 0,
            timestamp: String::new(),
            role: "user".into(),
            content: "Roundtrip test".into(),
            tool_name: None,
            is_rendered: None,
            step_number: None,
            step_tokens_in: None,
            step_tokens_out: None,
            step_elapsed: None,
            step_model_preview: None,
            step_tool_calls: None,
        }).await.unwrap();

        // 2. Run demo_solve through LoggingEmitter
        let emitter = LoggingEmitter::new(NullEmitter, replay);
        let token = CancellationToken::new();
        demo_solve("Roundtrip test", &emitter, token).await;

        // 3. Read back full conversation
        let entries = ReplayLogger::read_all(tmp.path()).await.unwrap();
        assert!(entries.len() >= 3, "expected user + step-summary + assistant, got {}", entries.len());

        assert_eq!(entries[0].role, "user");
        assert_eq!(entries[0].content, "Roundtrip test");
        assert_eq!(entries[0].seq, 1);

        assert_eq!(entries[1].role, "step-summary");
        assert_eq!(entries[1].seq, 2);

        assert_eq!(entries[2].role, "assistant");
        assert_eq!(entries[2].seq, 3);
        assert!(entries[2].content.contains("Roundtrip test"));

        for (i, entry) in entries.iter().enumerate() {
            assert_eq!(entry.seq, (i + 1) as u64);
        }
    }
}

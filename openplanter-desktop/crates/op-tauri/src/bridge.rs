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
use op_core::events::{
    CompleteEvent, CompletionMeta, CuratorUpdateEvent, DeltaEvent, DeltaKind, ErrorEvent,
    LoopHealthEvent, LoopMetrics, LoopPhase, StepEvent, TraceEvent,
};
use op_core::session::replay::{ReplayEntry, ReplayLogger, StepToolCallEntry};

const MAX_STEP_MODEL_PREVIEW_CHARS: usize = 4 * 1024;
const MAX_TOOL_ARGS_CAPTURE_CHARS: usize = 16 * 1024;
const MAX_DELTA_LOG_CHARS: usize = 120;

fn preview_text(text: &str, max_chars: usize) -> String {
    if text.len() <= max_chars {
        return text.to_string();
    }

    let end = text.floor_char_boundary(max_chars);
    format!("{}...[truncated {} chars]", &text[..end], text.len() - end)
}

fn append_with_cap(buffer: &mut String, text: &str, max_chars: usize, truncated: &mut bool) {
    if *truncated {
        return;
    }
    if buffer.len() >= max_chars {
        *truncated = true;
        return;
    }

    let remaining = max_chars - buffer.len();
    let end = text.floor_char_boundary(text.len().min(remaining));
    buffer.push_str(&text[..end]);
    if end < text.len() {
        *truncated = true;
    }
}

fn format_model_preview(buffer: &str, truncated: bool) -> Option<String> {
    let trimmed = buffer.trim();
    if trimmed.is_empty() {
        None
    } else if truncated {
        Some(format!("{trimmed}\n...[truncated]"))
    } else {
        Some(trimmed.to_string())
    }
}

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
        match event.kind {
            DeltaKind::ToolCallArgs => eprintln!(
                "[bridge] delta: kind={:?} len={} preview={:?}",
                event.kind,
                event.text.len(),
                preview_text(&event.text, MAX_DELTA_LOG_CHARS)
            ),
            _ if event.text.len() > MAX_DELTA_LOG_CHARS => eprintln!(
                "[bridge] delta: kind={:?} len={} preview={:?}",
                event.kind,
                event.text.len(),
                preview_text(&event.text, MAX_DELTA_LOG_CHARS)
            ),
            _ => eprintln!(
                "[bridge] delta: kind={:?} text={:?}",
                event.kind, event.text
            ),
        }
        let _ = self.handle.emit("agent:delta", event);
    }

    fn emit_step(&self, event: StepEvent) {
        eprintln!(
            "[bridge] step: depth={} step={} is_final={}",
            event.depth, event.step, event.is_final
        );
        let _ = self.handle.emit("agent:step", event);
    }

    fn emit_complete(
        &self,
        result: &str,
        loop_metrics: Option<LoopMetrics>,
        completion: Option<CompletionMeta>,
    ) {
        eprintln!("[bridge] complete: {result}");
        let _ = self.handle.emit(
            "agent:complete",
            CompleteEvent {
                result: result.to_string(),
                loop_metrics,
                completion,
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

    fn emit_loop_health(
        &self,
        depth: u32,
        step: u32,
        phase: LoopPhase,
        metrics: LoopMetrics,
        is_final: bool,
    ) {
        let _ = self.handle.emit(
            "agent:loop-health",
            LoopHealthEvent {
                depth,
                step,
                phase,
                metrics,
                is_final,
            },
        );
    }

    fn emit_curator_update(&self, summary: &str, files_changed: u32) {
        eprintln!("[bridge] curator update: {summary} ({files_changed} files)");
        let _ = self.handle.emit(
            "agent:curator-update",
            CuratorUpdateEvent {
                summary: summary.to_string(),
                files_changed,
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
    /// Whether the current step preview was truncated.
    streaming_truncated: Mutex<bool>,
    /// Tool calls accumulated during the current step.
    step_tool_calls: Mutex<Vec<PendingToolCall>>,
    /// Name of the tool currently being generated.
    current_tool: Mutex<String>,
    /// Accumulated args JSON for the current tool.
    current_args_buf: Mutex<String>,
    /// Whether the current tool args buffer was truncated.
    current_args_truncated: Mutex<bool>,
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
            streaming_truncated: Mutex::new(false),
            step_tool_calls: Mutex::new(Vec::new()),
            current_tool: Mutex::new(String::new()),
            current_args_buf: Mutex::new(String::new()),
            current_args_truncated: Mutex::new(false),
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
                let mut truncated = self.streaming_truncated.lock().unwrap();
                append_with_cap(
                    &mut self.streaming_buf.lock().unwrap(),
                    &event.text,
                    MAX_STEP_MODEL_PREVIEW_CHARS,
                    &mut truncated,
                );
            }
            DeltaKind::ToolCallStart => {
                let tool_name = event.text.clone();
                *self.current_tool.lock().unwrap() = tool_name.clone();
                *self.current_args_buf.lock().unwrap() = String::new();
                *self.current_args_truncated.lock().unwrap() = false;
                self.step_tool_calls.lock().unwrap().push(PendingToolCall {
                    name: tool_name,
                    key_arg: String::new(),
                    start_time: std::time::Instant::now(),
                });
            }
            DeltaKind::ToolCallArgs => {
                let mut buf = self.current_args_buf.lock().unwrap();
                let mut truncated = self.current_args_truncated.lock().unwrap();
                append_with_cap(
                    &mut buf,
                    &event.text,
                    MAX_TOOL_ARGS_CAPTURE_CHARS,
                    &mut truncated,
                );
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
            format_model_preview(&buf, *self.streaming_truncated.lock().unwrap())
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
        *self.streaming_truncated.lock().unwrap() = false;
        self.step_tool_calls.lock().unwrap().clear();
        self.current_tool.lock().unwrap().clear();
        self.current_args_buf.lock().unwrap().clear();
        *self.current_args_truncated.lock().unwrap() = false;

        self.inner.emit_step(event);
    }

    fn emit_complete(
        &self,
        result: &str,
        loop_metrics: Option<LoopMetrics>,
        completion: Option<CompletionMeta>,
    ) {
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

        self.inner.emit_complete(result, loop_metrics, completion);
    }

    fn emit_error(&self, message: &str) {
        self.inner.emit_error(message);
    }

    fn emit_loop_health(
        &self,
        depth: u32,
        step: u32,
        phase: LoopPhase,
        metrics: LoopMetrics,
        is_final: bool,
    ) {
        self.inner
            .emit_loop_health(depth, step, phase, metrics, is_final);
    }

    fn emit_curator_update(&self, summary: &str, files_changed: u32) {
        // Log curator update to replay
        let entry = ReplayEntry {
            seq: 0,
            timestamp: String::new(),
            role: "curator".into(),
            content: summary.to_string(),
            tool_name: None,
            is_rendered: None,
            step_number: None,
            step_tokens_in: None,
            step_tokens_out: None,
            step_elapsed: None,
            step_model_preview: None,
            step_tool_calls: None,
        };

        let replay = self.replay.clone();
        tokio::task::block_in_place(|| {
            tokio::runtime::Handle::current().block_on(async {
                if let Err(e) = replay.lock().await.append(entry).await {
                    eprintln!("[bridge] failed to log curator update: {e}");
                }
            });
        });

        self.inner.emit_curator_update(summary, files_changed);
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
        fn emit_complete(&self, _: &str, _: Option<LoopMetrics>, _: Option<CompletionMeta>) {}
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
        assert!(
            step.step_model_preview
                .as_ref()
                .unwrap()
                .contains("Test persistence")
        );

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
        replay
            .append(ReplayEntry {
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
            })
            .await
            .unwrap();

        // 2. Run demo_solve through LoggingEmitter
        let emitter = LoggingEmitter::new(NullEmitter, replay);
        let token = CancellationToken::new();
        demo_solve("Roundtrip test", &emitter, token).await;

        // 3. Read back full conversation
        let entries = ReplayLogger::read_all(tmp.path()).await.unwrap();
        assert!(
            entries.len() >= 3,
            "expected user + step-summary + assistant, got {}",
            entries.len()
        );

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

    #[derive(Default)]
    struct CapturingEmitter {
        deltas: Arc<Mutex<Vec<DeltaEvent>>>,
    }

    impl SolveEmitter for CapturingEmitter {
        fn emit_trace(&self, _: &str) {}
        fn emit_delta(&self, event: DeltaEvent) {
            self.deltas.lock().unwrap().push(event);
        }
        fn emit_step(&self, _: StepEvent) {}
        fn emit_complete(&self, _: &str, _: Option<LoopMetrics>, _: Option<CompletionMeta>) {}
        fn emit_error(&self, _: &str) {}
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn test_logging_emitter_caps_model_preview_and_preserves_deltas() {
        let tmp = tempdir().unwrap();
        let replay = ReplayLogger::new(tmp.path());
        let inner = CapturingEmitter::default();
        let deltas = inner.deltas.clone();
        let emitter = LoggingEmitter::new(inner, replay);
        let big_text = "x".repeat(MAX_STEP_MODEL_PREVIEW_CHARS + 256);

        emitter.emit_delta(DeltaEvent {
            kind: DeltaKind::Text,
            text: big_text.clone(),
        });
        emitter.emit_step(StepEvent {
            depth: 0,
            step: 1,
            tool_name: None,
            tokens: Default::default(),
            elapsed_ms: 1,
            is_final: false,
            loop_phase: None,
            loop_metrics: None,
        });

        let entries = ReplayLogger::read_all(tmp.path()).await.unwrap();
        let step = entries
            .iter()
            .find(|entry| entry.role == "step-summary")
            .unwrap();
        let preview = step.step_model_preview.as_ref().unwrap();
        assert!(preview.contains("[truncated]"));
        assert!(preview.len() < big_text.len());

        let captured = deltas.lock().unwrap();
        assert_eq!(captured.len(), 1);
        assert_eq!(captured[0].text, big_text);
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn test_logging_emitter_caps_tool_args_buffer_and_keeps_key_arg() {
        let tmp = tempdir().unwrap();
        let replay = ReplayLogger::new(tmp.path());
        let inner = CapturingEmitter::default();
        let deltas = inner.deltas.clone();
        let emitter = LoggingEmitter::new(inner, replay);
        let filler = "x".repeat(MAX_TOOL_ARGS_CAPTURE_CHARS + 512);

        emitter.emit_delta(DeltaEvent {
            kind: DeltaKind::ToolCallStart,
            text: "read_file".to_string(),
        });
        emitter.emit_delta(DeltaEvent {
            kind: DeltaKind::ToolCallArgs,
            text: "{\"path\":\"foo.md\",\"other\":\"".to_string(),
        });
        emitter.emit_delta(DeltaEvent {
            kind: DeltaKind::ToolCallArgs,
            text: filler.clone(),
        });

        assert!(emitter.current_args_buf.lock().unwrap().len() <= MAX_TOOL_ARGS_CAPTURE_CHARS);
        assert!(*emitter.current_args_truncated.lock().unwrap());

        emitter.emit_step(StepEvent {
            depth: 0,
            step: 1,
            tool_name: Some("read_file".into()),
            tokens: Default::default(),
            elapsed_ms: 1,
            is_final: false,
            loop_phase: None,
            loop_metrics: None,
        });

        let entries = ReplayLogger::read_all(tmp.path()).await.unwrap();
        let step = entries
            .iter()
            .find(|entry| entry.role == "step-summary")
            .unwrap();
        let tool_calls = step.step_tool_calls.as_ref().unwrap();
        assert_eq!(tool_calls[0].key_arg, "foo.md");

        let captured = deltas.lock().unwrap();
        assert_eq!(captured.len(), 3);
        assert_eq!(captured[2].text, filler);
    }
}

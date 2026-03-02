// Bridge between engine callbacks and Tauri events.
//
// TauriEmitter wraps an AppHandle and implements SolveEmitter so that
// the engine can stream events to the frontend without depending on Tauri.
//
// LoggingEmitter wraps TauriEmitter + ReplayLogger to persist messages
// to replay.jsonl as they stream.

use std::sync::Arc;
use tauri::{AppHandle, Emitter};
use tokio::sync::Mutex;

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

/// Wraps a TauriEmitter + ReplayLogger to persist events as they stream.
///
/// Collects streaming text and tool calls during a step, then logs
/// the full step summary and final assistant message to replay.jsonl.
pub struct LoggingEmitter {
    inner: TauriEmitter,
    replay: Arc<Mutex<ReplayLogger>>,
    /// Accumulated streaming text for the current step.
    streaming_buf: Arc<Mutex<String>>,
    /// Tool calls accumulated during the current step.
    step_tool_calls: Arc<Mutex<Vec<PendingToolCall>>>,
    /// Name of the tool currently being generated.
    current_tool: Arc<Mutex<String>>,
    /// Accumulated args JSON for the current tool.
    current_args_buf: Arc<Mutex<String>>,
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

impl LoggingEmitter {
    pub fn new(inner: TauriEmitter, replay: ReplayLogger) -> Self {
        Self {
            inner,
            replay: Arc::new(Mutex::new(replay)),
            streaming_buf: Arc::new(Mutex::new(String::new())),
            step_tool_calls: Arc::new(Mutex::new(Vec::new())),
            current_tool: Arc::new(Mutex::new(String::new())),
            current_args_buf: Arc::new(Mutex::new(String::new())),
        }
    }
}

impl SolveEmitter for LoggingEmitter {
    fn emit_trace(&self, message: &str) {
        self.inner.emit_trace(message);
    }

    fn emit_delta(&self, event: DeltaEvent) {
        // Accumulate streaming data for step summary logging
        match event.kind {
            DeltaKind::Text => {
                let text = event.text.clone();
                let buf = self.streaming_buf.clone();
                tokio::task::block_in_place(|| {
                    let rt = tokio::runtime::Handle::current();
                    rt.block_on(async {
                        buf.lock().await.push_str(&text);
                    });
                });
            }
            DeltaKind::ToolCallStart => {
                let tool_name = event.text.clone();
                let tool_calls = self.step_tool_calls.clone();
                let current_tool = self.current_tool.clone();
                let args_buf = self.current_args_buf.clone();
                tokio::task::block_in_place(|| {
                    let rt = tokio::runtime::Handle::current();
                    rt.block_on(async {
                        *current_tool.lock().await = tool_name.clone();
                        *args_buf.lock().await = String::new();
                        tool_calls.lock().await.push(PendingToolCall {
                            name: tool_name,
                            key_arg: String::new(),
                            start_time: std::time::Instant::now(),
                        });
                    });
                });
            }
            DeltaKind::ToolCallArgs => {
                let text = event.text.clone();
                let tool_calls = self.step_tool_calls.clone();
                let current_tool = self.current_tool.clone();
                let args_buf = self.current_args_buf.clone();
                tokio::task::block_in_place(|| {
                    let rt = tokio::runtime::Handle::current();
                    rt.block_on(async {
                        let mut buf = args_buf.lock().await;
                        buf.push_str(&text);
                        let tool_name = current_tool.lock().await.clone();
                        if let Some(key_arg) = extract_key_arg(&tool_name, &buf) {
                            let mut calls = tool_calls.lock().await;
                            if let Some(last) = calls.last_mut() {
                                if last.key_arg.is_empty() {
                                    last.key_arg = key_arg;
                                }
                            }
                        }
                    });
                });
            }
            DeltaKind::Thinking => {
                // Don't accumulate thinking text
            }
        }

        self.inner.emit_delta(event);
    }

    fn emit_step(&self, event: StepEvent) {
        // Log step summary to replay
        let replay = self.replay.clone();
        let streaming_buf = self.streaming_buf.clone();
        let tool_calls = self.step_tool_calls.clone();
        let step_event = event.clone();

        tokio::task::block_in_place(|| {
            let rt = tokio::runtime::Handle::current();
            rt.block_on(async {
                let model_preview = {
                    let buf = streaming_buf.lock().await;
                    let trimmed = buf.trim().to_string();
                    if trimmed.is_empty() { None } else { Some(trimmed) }
                };

                let calls = tool_calls.lock().await;
                let step_tools: Vec<StepToolCallEntry> = calls
                    .iter()
                    .map(|tc| StepToolCallEntry {
                        name: tc.name.clone(),
                        key_arg: tc.key_arg.clone(),
                        elapsed: tc.start_time.elapsed().as_millis() as u64,
                    })
                    .collect();

                let entry = ReplayEntry {
                    seq: 0,
                    timestamp: String::new(),
                    role: "step-summary".into(),
                    content: String::new(),
                    tool_name: None,
                    is_rendered: None,
                    step_number: Some(step_event.step),
                    step_tokens_in: Some(step_event.tokens.input_tokens),
                    step_tokens_out: Some(step_event.tokens.output_tokens),
                    step_elapsed: Some(step_event.elapsed_ms),
                    step_model_preview: model_preview,
                    step_tool_calls: if step_tools.is_empty() {
                        None
                    } else {
                        Some(step_tools)
                    },
                };

                if let Err(e) = replay.lock().await.append(entry).await {
                    eprintln!("[bridge] failed to log step: {e}");
                }

                // Reset buffers for next step
                streaming_buf.lock().await.clear();
                tool_calls.lock().await.clear();
            });
        });

        self.inner.emit_step(event);
    }

    fn emit_complete(&self, result: &str) {
        // Log assistant message to replay
        let replay = self.replay.clone();
        let result_owned = result.to_string();

        tokio::task::block_in_place(|| {
            let rt = tokio::runtime::Handle::current();
            rt.block_on(async {
                let entry = ReplayEntry {
                    seq: 0,
                    timestamp: String::new(),
                    role: "assistant".into(),
                    content: result_owned,
                    tool_name: None,
                    is_rendered: Some(true),
                    step_number: None,
                    step_tokens_in: None,
                    step_tokens_out: None,
                    step_elapsed: None,
                    step_model_preview: None,
                    step_tool_calls: None,
                };

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

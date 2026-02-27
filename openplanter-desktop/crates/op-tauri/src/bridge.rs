// Bridge between engine callbacks and Tauri events.
//
// TauriEmitter wraps an AppHandle and implements SolveEmitter so that
// the engine can stream events to the frontend without depending on Tauri.

use tauri::{AppHandle, Emitter};

use op_core::engine::SolveEmitter;
use op_core::events::{CompleteEvent, DeltaEvent, ErrorEvent, StepEvent, TraceEvent};

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

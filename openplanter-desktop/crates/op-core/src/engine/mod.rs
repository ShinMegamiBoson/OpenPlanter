// Recursive language model engine.
//
// Provides the SolveEmitter trait, demo_solve, and a real solve flow
// with a multi-step agentic loop that executes tool calls.

pub mod context;
pub mod judge;

use tokio_util::sync::CancellationToken;

use crate::builder::build_model;
use crate::config::AgentConfig;
use crate::events::{DeltaEvent, DeltaKind, StepEvent, TokenUsage};
use crate::model::Message;
use crate::prompts::build_system_prompt;
use crate::tools::defs::build_tool_defs;
use crate::tools::WorkspaceTools;

// Abstraction for emitting solve events.
//
// Implemented by TauriEmitter (op-tauri) for real event emission
// and by TestEmitter (tests) for deterministic verification.
pub trait SolveEmitter: Send + Sync {
    fn emit_trace(&self, message: &str);
    fn emit_delta(&self, event: DeltaEvent);
    fn emit_step(&self, event: StepEvent);
    fn emit_complete(&self, result: &str);
    fn emit_error(&self, message: &str);
}

// Demo solve flow that echoes the objective with simulated streaming.
//
// This is a placeholder until the full engine is implemented in Phase 4.
// It emits the standard event sequence so the frontend can be developed
// and tested against a working backend.
pub async fn demo_solve(
    objective: &str,
    emitter: &dyn SolveEmitter,
    cancel: CancellationToken,
) {
    emitter.emit_trace(&format!("Solving: {objective}"));

    if cancel.is_cancelled() {
        emitter.emit_error("Cancelled");
        return;
    }

    // Simulate thinking
    emitter.emit_delta(DeltaEvent {
        kind: DeltaKind::Thinking,
        text: format!("Analyzing: {objective}"),
    });

    tokio::time::sleep(std::time::Duration::from_millis(300)).await;

    if cancel.is_cancelled() {
        emitter.emit_error("Cancelled");
        return;
    }

    // Simulate streaming text response
    let response = format!("Demo response for: {objective}");
    for chunk in response.as_bytes().chunks(20) {
        if cancel.is_cancelled() {
            emitter.emit_error("Cancelled");
            return;
        }
        let text = String::from_utf8_lossy(chunk).to_string();
        emitter.emit_delta(DeltaEvent {
            kind: DeltaKind::Text,
            text,
        });
        tokio::time::sleep(std::time::Duration::from_millis(50)).await;
    }

    // Emit step summary
    emitter.emit_step(StepEvent {
        depth: 0,
        step: 1,
        tool_name: None,
        tokens: TokenUsage {
            input_tokens: 100,
            output_tokens: 50,
        },
        elapsed_ms: 350,
        is_final: true,
    });

    emitter.emit_complete(&response);
}

/// Real solve flow with a multi-step agentic loop.
///
/// Calls the model with tool definitions. If the model returns tool calls,
/// executes them, appends results, and loops until the model returns a
/// final text answer or the step budget is exhausted.
///
/// Falls back to demo_solve when `config.demo` is true.
pub async fn solve(
    objective: &str,
    config: &AgentConfig,
    emitter: &dyn SolveEmitter,
    cancel: CancellationToken,
) {
    if config.demo {
        return demo_solve(objective, emitter, cancel).await;
    }

    // 1. Build model
    let model = match build_model(config) {
        Ok(m) => m,
        Err(e) => {
            emitter.emit_error(&e.to_string());
            return;
        }
    };

    let provider = model.provider_name().to_string();
    emitter.emit_trace(&format!(
        "Solving with {}/{}",
        provider,
        model.model_name()
    ));

    // 2. Build tools and messages
    let tool_defs = build_tool_defs(&provider);
    let mut tools = WorkspaceTools::new(config);

    let system_prompt = build_system_prompt(
        config.recursive,
        config.acceptance_criteria,
        config.demo,
    );
    let mut messages = vec![
        Message::System {
            content: system_prompt,
        },
        Message::User {
            content: objective.to_string(),
        },
    ];

    let max_steps = config.max_steps_per_call as usize;

    // 3. Agentic loop
    for step in 1..=max_steps {
        if cancel.is_cancelled() {
            emitter.emit_error("Cancelled");
            tools.cleanup();
            return;
        }

        let step_start = std::time::Instant::now();

        // Call model with streaming
        let turn = match model
            .chat_stream(&messages, &tool_defs, &|delta| emitter.emit_delta(delta), &cancel)
            .await
        {
            Ok(t) => t,
            Err(e) => {
                let msg = e.to_string();
                tools.cleanup();
                if msg == "Cancelled" {
                    emitter.emit_error("Cancelled");
                } else {
                    emitter.emit_error(&msg);
                }
                return;
            }
        };

        // Append assistant message to conversation
        let tool_calls_opt = if turn.tool_calls.is_empty() {
            None
        } else {
            Some(turn.tool_calls.clone())
        };
        messages.push(Message::Assistant {
            content: turn.text.clone(),
            tool_calls: tool_calls_opt,
        });

        // No tool calls → final answer
        if turn.tool_calls.is_empty() {
            let tool_name = None;
            emitter.emit_step(StepEvent {
                depth: 0,
                step: step as u32,
                tool_name,
                tokens: TokenUsage {
                    input_tokens: turn.input_tokens,
                    output_tokens: turn.output_tokens,
                },
                elapsed_ms: step_start.elapsed().as_millis() as u64,
                is_final: true,
            });
            emitter.emit_complete(&turn.text);
            tools.cleanup();
            return;
        }

        // Execute each tool call and collect results
        for tc in &turn.tool_calls {
            if cancel.is_cancelled() {
                emitter.emit_error("Cancelled");
                tools.cleanup();
                return;
            }

            emitter.emit_trace(&format!("Executing tool: {} ({})", tc.name, tc.id));
            let result = tools.execute(&tc.name, &tc.arguments).await;

            if result.is_error {
                emitter.emit_trace(&format!("Tool {} error: {}", tc.name, &result.content[..result.content.len().min(200)]));
            }

            messages.push(Message::Tool {
                tool_call_id: tc.id.clone(),
                content: result.content,
            });
        }

        // Emit step (non-final) AFTER tools execute so the frontend
        // can refresh the wiki graph with newly written files.
        let first_tool = turn.tool_calls.first().map(|tc| tc.name.clone());
        emitter.emit_step(StepEvent {
            depth: 0,
            step: step as u32,
            tool_name: first_tool,
            tokens: TokenUsage {
                input_tokens: turn.input_tokens,
                output_tokens: turn.output_tokens,
            },
            elapsed_ms: step_start.elapsed().as_millis() as u64,
            is_final: false,
        });

        // Budget warnings
        let remaining = max_steps - step;
        if remaining == max_steps / 2 {
            emitter.emit_trace(&format!(
                "Step budget: {remaining}/{max_steps} steps remaining (50%)"
            ));
        } else if remaining == max_steps / 4 {
            emitter.emit_trace(&format!(
                "Step budget: {remaining}/{max_steps} steps remaining (25%)"
            ));
        }
    }

    // Budget exhausted
    tools.cleanup();
    emitter.emit_error(&format!(
        "Step budget exhausted after {max_steps} steps. \
         The model did not produce a final answer within the allowed steps."
    ));
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Arc, Mutex};

    #[derive(Debug, Clone)]
    #[allow(dead_code)]
    enum RecordedEvent {
        Trace(String),
        Delta(DeltaEvent),
        Step(StepEvent),
        Complete(String),
        Error(String),
    }

    struct TestEmitter {
        events: Arc<Mutex<Vec<RecordedEvent>>>,
    }

    impl TestEmitter {
        fn new() -> Self {
            Self {
                events: Arc::new(Mutex::new(Vec::new())),
            }
        }

        fn events(&self) -> Vec<RecordedEvent> {
            self.events.lock().unwrap().clone()
        }
    }

    impl SolveEmitter for TestEmitter {
        fn emit_trace(&self, message: &str) {
            self.events
                .lock()
                .unwrap()
                .push(RecordedEvent::Trace(message.to_string()));
        }

        fn emit_delta(&self, event: DeltaEvent) {
            self.events
                .lock()
                .unwrap()
                .push(RecordedEvent::Delta(event));
        }

        fn emit_step(&self, event: StepEvent) {
            self.events
                .lock()
                .unwrap()
                .push(RecordedEvent::Step(event));
        }

        fn emit_complete(&self, result: &str) {
            self.events
                .lock()
                .unwrap()
                .push(RecordedEvent::Complete(result.to_string()));
        }

        fn emit_error(&self, message: &str) {
            self.events
                .lock()
                .unwrap()
                .push(RecordedEvent::Error(message.to_string()));
        }
    }

    #[tokio::test]
    async fn test_demo_solve_emits_complete_sequence() {
        let emitter = TestEmitter::new();
        let token = CancellationToken::new();

        demo_solve("Test objective", &emitter, token).await;

        let events = emitter.events();
        assert!(events.len() >= 4, "expected at least 4 events, got {}", events.len());

        // First event: trace
        assert!(matches!(&events[0], RecordedEvent::Trace(_)));

        // Second event: thinking delta
        assert!(
            matches!(&events[1], RecordedEvent::Delta(d) if matches!(d.kind, DeltaKind::Thinking))
        );

        // At least one text delta
        let has_text_delta = events
            .iter()
            .any(|e| matches!(e, RecordedEvent::Delta(d) if matches!(d.kind, DeltaKind::Text)));
        assert!(has_text_delta, "expected at least one text delta");

        // At least one step
        let has_step = events.iter().any(|e| matches!(e, RecordedEvent::Step(_)));
        assert!(has_step, "expected a step event");

        // Last event: complete
        assert!(
            matches!(events.last(), Some(RecordedEvent::Complete(_))),
            "expected last event to be Complete"
        );
    }

    #[tokio::test]
    async fn test_demo_solve_cancel() {
        let emitter = TestEmitter::new();
        let token = CancellationToken::new();
        token.cancel(); // Cancel before starting

        demo_solve("Test objective", &emitter, token).await;

        let events = emitter.events();

        let has_error = events
            .iter()
            .any(|e| matches!(e, RecordedEvent::Error(m) if m == "Cancelled"));
        assert!(has_error, "expected a Cancelled error event");

        let has_complete = events.iter().any(|e| matches!(e, RecordedEvent::Complete(_)));
        assert!(!has_complete, "should not have a Complete event when cancelled");
    }

    #[tokio::test]
    async fn test_demo_solve_echoes_objective() {
        let emitter = TestEmitter::new();
        let token = CancellationToken::new();

        demo_solve("Hello world", &emitter, token).await;

        let events = emitter.events();

        // Text deltas should contain the objective
        let text_content: String = events
            .iter()
            .filter_map(|e| match e {
                RecordedEvent::Delta(d) if matches!(d.kind, DeltaKind::Text) => {
                    Some(d.text.clone())
                }
                _ => None,
            })
            .collect();
        assert!(
            text_content.contains("Hello world"),
            "text deltas should contain objective, got: {text_content}"
        );

        // Complete event should contain the objective
        let complete_text = events
            .iter()
            .find_map(|e| match e {
                RecordedEvent::Complete(r) => Some(r.clone()),
                _ => None,
            })
            .expect("should have a Complete event");
        assert!(
            complete_text.contains("Hello world"),
            "complete result should contain objective, got: {complete_text}"
        );
    }

    #[tokio::test]
    async fn test_demo_solve_cancel_mid_flight() {
        let events = Arc::new(Mutex::new(Vec::new()));
        let emitter = TestEmitter {
            events: events.clone(),
        };
        let token = CancellationToken::new();
        let cancel_handle = token.clone();

        // Spawn demo_solve on a separate task, just like agent.rs does
        let task = tokio::spawn(async move {
            demo_solve("Mid-cancel test", &emitter, token).await;
        });

        // Wait for the trace event to be emitted, then cancel
        // This proves cancellation works mid-solve, not just pre-solve
        loop {
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
            let current = events.lock().unwrap().len();
            if current >= 2 {
                // At least trace + thinking delta emitted; cancel now
                cancel_handle.cancel();
                break;
            }
        }

        task.await.expect("task should not panic");

        let recorded = events.lock().unwrap().clone();

        // Should have an error with "Cancelled"
        let has_error = recorded
            .iter()
            .any(|e| matches!(e, RecordedEvent::Error(m) if m == "Cancelled"));
        assert!(has_error, "expected Cancelled error after mid-flight cancel");

        // Should NOT have a Complete event
        let has_complete = recorded
            .iter()
            .any(|e| matches!(e, RecordedEvent::Complete(_)));
        assert!(
            !has_complete,
            "should not have Complete after mid-flight cancel"
        );
    }

    #[tokio::test]
    async fn test_demo_solve_spawned_task_completes() {
        // Simulates the exact pattern used in agent.rs:
        // spawn demo_solve on a task, let it run to completion
        let events = Arc::new(Mutex::new(Vec::new()));
        let emitter = TestEmitter {
            events: events.clone(),
        };
        let token = CancellationToken::new();

        let task = tokio::spawn(async move {
            demo_solve("Spawned test", &emitter, token).await;
        });

        task.await.expect("spawned task should not panic");

        let recorded = events.lock().unwrap().clone();

        // Verify full sequence completed through the spawned task
        assert!(
            matches!(recorded.first(), Some(RecordedEvent::Trace(_))),
            "first event should be Trace"
        );
        assert!(
            matches!(recorded.last(), Some(RecordedEvent::Complete(_))),
            "last event should be Complete"
        );

        // Verify the complete event contains the objective
        let complete_text = recorded
            .iter()
            .find_map(|e| match e {
                RecordedEvent::Complete(r) => Some(r.clone()),
                _ => None,
            })
            .unwrap();
        assert!(complete_text.contains("Spawned test"));
    }
}

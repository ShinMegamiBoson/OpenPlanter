// Recursive language model engine.
//
// Provides the SolveEmitter trait, demo_solve, and a real solve flow
// with a multi-step agentic loop that executes tool calls.

pub mod context;
pub mod curator;
pub mod investigation_state;
pub mod judge;

use std::collections::HashSet;
use std::time::Duration;

use anyhow::anyhow;
use chrono::Utc;
use serde_json::{Map, Value};
use tokio_util::sync::CancellationToken;

use crate::builder::build_model;
use crate::config::AgentConfig;
use crate::events::{
    CompletionMeta, DeltaEvent, DeltaKind, LoopMetrics, LoopPhase, StepEvent, TokenUsage,
};
use crate::model::{BaseModel, Message, ModelTurn, RateLimitError};
use crate::prompts::build_system_prompt;
use crate::tools::WorkspaceTools;
use crate::tools::defs::build_tool_defs;

use self::curator::{
    CuratorCheckpoint, CuratorStateDelta, build_state_delta, run_curator_checkpoint,
};

#[derive(Debug, Clone, Default)]
pub struct SolveInitialContext {
    pub session_id: Option<String>,
    pub session_dir: Option<String>,
    pub question_reasoning_packet: Option<Value>,
}

fn take_curator_phase_checkpoint(
    pending_deltas: &mut Vec<CuratorStateDelta>,
    active_phase: &mut Option<LoopPhase>,
    next_phase: LoopPhase,
) -> Option<CuratorCheckpoint> {
    let checkpoint = match active_phase.as_ref() {
        Some(previous_phase) if previous_phase != &next_phase && !pending_deltas.is_empty() => {
            Some(CuratorCheckpoint {
                boundary: format!("phase_transition:{previous_phase:?}->{next_phase:?}"),
                deltas: std::mem::take(pending_deltas),
            })
        }
        _ => None,
    };

    *active_phase = Some(next_phase);
    checkpoint
}

fn take_pending_curator_checkpoint(
    pending_deltas: &mut Vec<CuratorStateDelta>,
    boundary: &str,
) -> Option<CuratorCheckpoint> {
    if pending_deltas.is_empty() {
        return None;
    }

    Some(CuratorCheckpoint {
        boundary: boundary.to_string(),
        deltas: std::mem::take(pending_deltas),
    })
}

async fn emit_curator_checkpoint(
    checkpoint: CuratorCheckpoint,
    config: &AgentConfig,
    cancel: &CancellationToken,
    emitter: &dyn SolveEmitter,
) {
    emitter.emit_trace(&format!(
        "[curator] synthesizing checkpoint at {} ({} deltas)",
        checkpoint.boundary,
        checkpoint.deltas.len()
    ));

    match run_curator_checkpoint(&checkpoint, config, cancel.clone()).await {
        Ok(result) if result.files_changed > 0 => {
            emitter.emit_trace(&format!(
                "[curator] wiki updated: {} ({} files)",
                result.summary, result.files_changed
            ));
            emitter.emit_curator_update(&result.summary, result.files_changed);
        }
        Ok(_) => {
            emitter.emit_trace(&format!(
                "[curator] no net wiki updates at {}",
                checkpoint.boundary
            ));
        }
        Err(err) => {
            emitter.emit_trace(&format!(
                "[curator] checkpoint {} error: {err}",
                checkpoint.boundary
            ));
        }
    }
}

async fn flush_pending_curator_checkpoint(
    pending_deltas: &mut Vec<CuratorStateDelta>,
    boundary: &str,
    config: &AgentConfig,
    cancel: &CancellationToken,
    emitter: &dyn SolveEmitter,
) {
    if let Some(checkpoint) = take_pending_curator_checkpoint(pending_deltas, boundary) {
        emit_curator_checkpoint(checkpoint, config, cancel, emitter).await;
    }
}

// Abstraction for emitting solve events.
//
// Implemented by TauriEmitter (op-tauri) for real event emission
// and by TestEmitter (tests) for deterministic verification.
pub trait SolveEmitter: Send + Sync {
    fn emit_trace(&self, message: &str);
    fn emit_delta(&self, event: DeltaEvent);
    fn emit_step(&self, event: StepEvent);
    fn emit_complete(
        &self,
        result: &str,
        loop_metrics: Option<LoopMetrics>,
        completion: Option<CompletionMeta>,
    );
    fn emit_error(&self, message: &str);
    fn emit_loop_health(
        &self,
        _depth: u32,
        _step: u32,
        _phase: LoopPhase,
        _metrics: LoopMetrics,
        _is_final: bool,
    ) {
    }
    /// Called when a checkpointed curator finishes updating wiki files.
    /// Default no-op — override in TauriEmitter/LoggingEmitter.
    fn emit_curator_update(&self, _summary: &str, _files_changed: u32) {}
}

// Demo solve flow that echoes the objective with simulated streaming.
//
// This is a placeholder until the full engine is implemented in Phase 4.
// It emits the standard event sequence so the frontend can be developed
// and tested against a working backend.
pub async fn demo_solve(objective: &str, emitter: &dyn SolveEmitter, cancel: CancellationToken) {
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

    let loop_metrics = LoopMetrics {
        steps: 1,
        model_turns: 1,
        tool_calls: 0,
        investigate_steps: 0,
        build_steps: 0,
        iterate_steps: 0,
        finalize_steps: 1,
        recon_streak: 0,
        max_recon_streak: 0,
        guardrail_warnings: 0,
        final_rejections: 0,
        extensions_granted: 0,
        extension_eligible_checks: 0,
        extension_denials_no_progress: 0,
        extension_denials_cap: 0,
        termination_reason: "success".into(),
    };
    emitter.emit_loop_health(0, 1, LoopPhase::Finalize, loop_metrics.clone(), true);

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
        loop_phase: Some(LoopPhase::Finalize),
        loop_metrics: Some(loop_metrics.clone()),
    });

    emitter.emit_complete(&response, Some(loop_metrics), None);
}

/// Rough token estimate: ~4 chars per token.
fn estimate_tokens(messages: &[Message]) -> usize {
    messages
        .iter()
        .map(|m| match m {
            Message::System { content } | Message::User { content } => content.len(),
            Message::Assistant {
                content,
                tool_calls,
            } => {
                content.len()
                    + tool_calls
                        .as_ref()
                        .map(|tcs| {
                            tcs.iter()
                                .map(|tc| tc.arguments.len() + tc.name.len())
                                .sum()
                        })
                        .unwrap_or(0)
            }
            Message::Tool { content, .. } => content.len(),
        })
        .sum::<usize>()
        / 4
}

fn safe_prefix(text: &str, max_chars: usize) -> &str {
    let end = text.floor_char_boundary(text.len().min(max_chars));
    &text[..end]
}

fn build_initial_user_message(
    objective: &str,
    config: &AgentConfig,
    initial_context: Option<&SolveInitialContext>,
) -> Result<String, serde_json::Error> {
    let Some(initial_context) = initial_context else {
        return Ok(objective.to_string());
    };

    let mut payload = Map::new();
    payload.insert(
        "timestamp".to_string(),
        Value::String(Utc::now().to_rfc3339()),
    );
    payload.insert(
        "objective".to_string(),
        Value::String(objective.to_string()),
    );
    payload.insert(
        "max_steps_per_call".to_string(),
        Value::from(config.max_steps_per_call),
    );
    payload.insert(
        "workspace".to_string(),
        Value::String(config.workspace.display().to_string()),
    );
    if let Some(session_id) = initial_context
        .session_id
        .as_ref()
        .filter(|value| !value.trim().is_empty())
    {
        payload.insert("session_id".to_string(), Value::String(session_id.clone()));
    }
    if let Some(session_dir) = initial_context
        .session_dir
        .as_ref()
        .filter(|value| !value.trim().is_empty())
    {
        payload.insert(
            "session_dir".to_string(),
            Value::String(session_dir.clone()),
        );
    }
    if let Some(packet) = initial_context.question_reasoning_packet.clone() {
        payload.insert("question_reasoning_packet".to_string(), packet);
    }

    serde_json::to_string(&payload)
}

/// Compact conversation context when it grows too large.
///
/// Keeps the system prompt, user objective, and the most recent messages
/// intact. Truncates older Tool result content to a short placeholder.
fn compact_messages(messages: &mut Vec<Message>, max_tokens: usize) {
    if estimate_tokens(messages) <= max_tokens {
        return;
    }

    // Keep the first 2 messages (System + User) and the last `keep_recent`
    // messages intact. Truncate Tool content in between.
    let keep_recent = 10; // Keep last ~10 messages (a few steps worth)
    let protected_tail = messages.len().saturating_sub(keep_recent);

    for i in 2..protected_tail {
        if let Message::Tool { content, .. } = &mut messages[i] {
            if content.len() > 200 {
                let preview = safe_prefix(content, 150);
                *content = format!("{preview}\n...[truncated — older tool result]");
            }
        }
    }
}

fn compute_rate_limit_delay_sec(
    config: &AgentConfig,
    retry_count: usize,
    err: &RateLimitError,
) -> f64 {
    let retry_after_cap = config.rate_limit_retry_after_cap_sec.max(0.0);
    let backoff_max = config.rate_limit_backoff_max_sec.max(0.0);
    let delay = err
        .retry_after_sec
        .map(|value| value.max(0.0).min(retry_after_cap))
        .unwrap_or_else(|| {
            let base = config.rate_limit_backoff_base_sec.max(0.0);
            base * 2_f64.powi((retry_count.saturating_sub(1)) as i32)
        });
    delay.min(backoff_max)
}

async fn chat_stream_with_rate_limit_retries(
    model: &dyn BaseModel,
    messages: &[Message],
    tool_defs: &[serde_json::Value],
    on_delta: &(dyn Fn(DeltaEvent) + Send + Sync),
    cancel: &CancellationToken,
    config: &AgentConfig,
    emitter: &dyn SolveEmitter,
    step: usize,
) -> anyhow::Result<ModelTurn> {
    let max_retries = config.rate_limit_max_retries.max(0) as usize;
    let mut retries = 0usize;

    loop {
        if cancel.is_cancelled() {
            return Err(anyhow!("Cancelled"));
        }

        match model
            .chat_stream(messages, tool_defs, on_delta, cancel)
            .await
        {
            Ok(turn) => return Ok(turn),
            Err(err) => {
                if let Some(rate_limit) = err.downcast_ref::<RateLimitError>() {
                    if retries >= max_retries {
                        return Err(err);
                    }
                    retries += 1;
                    let delay_sec = compute_rate_limit_delay_sec(config, retries, rate_limit);
                    let provider_code = rate_limit
                        .provider_code
                        .as_deref()
                        .map(|code| format!(" ({code})"))
                        .unwrap_or_default();
                    emitter.emit_trace(&format!(
                        "[d0/s{step}] rate limited{provider_code}. Sleeping {delay_sec:.1}s before retry {retries}/{max_retries}..."
                    ));
                    if delay_sec > 0.0 {
                        tokio::select! {
                            _ = cancel.cancelled() => return Err(anyhow!("Cancelled")),
                            _ = tokio::time::sleep(Duration::from_secs_f64(delay_sec)) => {}
                        }
                    }
                    continue;
                }
                return Err(err);
            }
        }
    }
}

fn objective_allows_meta_final(objective: &str) -> bool {
    objective
        .split(|c: char| !c.is_ascii_alphanumeric())
        .filter(|token| !token.is_empty())
        .any(|token| {
            matches!(
                token.to_ascii_lowercase().as_str(),
                "plan"
                    | "planning"
                    | "approach"
                    | "strategy"
                    | "outline"
                    | "spec"
                    | "specification"
                    | "design"
                    | "roadmap"
                    | "proposal"
                    | "review"
                    | "audit"
                    | "analysis"
                    | "analyze"
                    | "brainstorm"
            )
        })
}

fn is_meta_final_text(text: &str, objective: &str) -> bool {
    let stripped = text.trim();
    if stripped.is_empty() {
        return true;
    }
    let lower = stripped.to_ascii_lowercase();
    let weak_structural_meta = [
        "here is my plan",
        "here's my plan",
        "here is the plan",
        "here's the plan",
        "here is my approach",
        "here's my approach",
        "here is the approach",
        "here's the approach",
        "here is my analysis",
        "here's my analysis",
        "here is the analysis",
        "here's the analysis",
    ];
    let padded = format!(" {lower} ");
    let strong_process_meta = [
        " i will ",
        " i can ",
        " i should ",
        " i need to ",
        " i want to ",
        " i am going to ",
        " plan to ",
        " let me ",
        " next, i will ",
        " next i will ",
        " i should start by ",
    ];
    if strong_process_meta
        .iter()
        .any(|needle| padded.contains(needle))
    {
        return true;
    }
    if weak_structural_meta.iter().any(|p| lower.starts_with(p)) {
        return !objective_allows_meta_final(objective);
    }
    false
}

fn is_recon_tool(name: &str) -> bool {
    matches!(
        name,
        "list_files"
            | "search_files"
            | "repo_map"
            | "web_search"
            | "fetch_url"
            | "read_file"
            | "read_image"
            | "audio_transcribe"
            | "list_artifacts"
            | "read_artifact"
    )
}

fn is_artifact_tool(name: &str) -> bool {
    matches!(
        name,
        "write_file" | "apply_patch" | "edit_file" | "hashline_edit"
    )
}

fn classify_loop_phase(tool_calls: &[crate::model::ToolCall], is_final: bool) -> LoopPhase {
    if is_final {
        return LoopPhase::Finalize;
    }
    if tool_calls.is_empty() {
        return LoopPhase::Iterate;
    }
    let has_recon = tool_calls.iter().any(|tc| is_recon_tool(&tc.name));
    let has_artifact = tool_calls.iter().any(|tc| is_artifact_tool(&tc.name));
    if has_artifact {
        LoopPhase::Build
    } else if has_recon && tool_calls.iter().all(|tc| is_recon_tool(&tc.name)) {
        LoopPhase::Investigate
    } else {
        LoopPhase::Iterate
    }
}

fn increment_phase(metrics: &mut LoopMetrics, phase: &LoopPhase) {
    match phase {
        LoopPhase::Investigate => metrics.investigate_steps += 1,
        LoopPhase::Build => metrics.build_steps += 1,
        LoopPhase::Iterate => metrics.iterate_steps += 1,
        LoopPhase::Finalize => metrics.finalize_steps += 1,
    }
}

fn should_emit_recon_guardrail(recon_streak: u32, last_guardrail_streak: u32) -> bool {
    recon_streak >= 3 && last_guardrail_streak == 0
}

const BUDGET_EXTENSION_WINDOW: usize = 12;
const MIN_MEANINGFUL_RESULT_CHARS: usize = 24;
const MIN_EXTENSION_PROGRESS_SIGNALS: usize = 2;

#[derive(Debug, Clone)]
struct StepProgressRecord {
    phase: LoopPhase,
    step_signature: String,
    tool_count: usize,
    failed_tool_step: bool,
    successful_action_signatures: HashSet<String>,
    state_delta_signatures: HashSet<String>,
    completed_previews: Vec<String>,
}

fn normalize_progress_fragment(text: &str, max_len: usize) -> String {
    let mut normalized = text.split_whitespace().collect::<Vec<_>>().join(" ");
    normalized = normalized.to_lowercase();
    while normalized.starts_with('[') {
        if let Some(idx) = normalized.find(']') {
            normalized = normalized[idx + 1..].trim_start().to_string();
        } else {
            break;
        }
    }
    if normalized.len() > max_len {
        normalized = safe_prefix(&normalized, max_len).to_string();
    }
    normalized
}

fn summarize_observation(text: &str, max_len: usize) -> String {
    let first = text.lines().next().unwrap_or("").trim();
    if first.len() > max_len {
        format!("{}...", safe_prefix(first, max_len.saturating_sub(3)))
    } else {
        first.to_string()
    }
}

fn is_non_progress_tool(name: &str) -> bool {
    is_recon_tool(name) || name == "think"
}

fn action_signature(name: &str, args: &str) -> String {
    format!("{}|{}", name, normalize_progress_fragment(args, 160))
}

fn build_step_progress_record(
    tool_calls: &[crate::model::ToolCall],
    observations: &[(String, String, String, String, bool)],
    phase: LoopPhase,
) -> StepProgressRecord {
    let tool_names: Vec<&str> = tool_calls.iter().map(|tc| tc.name.as_str()).collect();
    let has_artifact = tool_names.iter().any(|name| is_artifact_tool(name));
    let has_error = observations.iter().any(|(_, _, _, _, is_error)| *is_error);
    let mut record = StepProgressRecord {
        phase,
        step_signature: format!(
            "{}|artifact={}|error={}",
            tool_names.join(","),
            if has_artifact { 1 } else { 0 },
            if has_error { 1 } else { 0 }
        ),
        tool_count: tool_calls.len(),
        failed_tool_step: has_error,
        successful_action_signatures: HashSet::new(),
        state_delta_signatures: HashSet::new(),
        completed_previews: Vec::new(),
    };
    for (_, name, args, content, is_error) in observations {
        if *is_error || is_non_progress_tool(name) {
            continue;
        }
        let normalized = normalize_progress_fragment(content, 120);
        if normalized.len() < MIN_MEANINGFUL_RESULT_CHARS {
            continue;
        }
        record
            .successful_action_signatures
            .insert(action_signature(name, args));
        record
            .state_delta_signatures
            .insert(format!("{}|{}", name, normalized));
        let preview = summarize_observation(content, 120);
        if !preview.is_empty() && !record.completed_previews.contains(&preview) {
            record.completed_previews.push(preview);
        }
    }
    record
}

fn evaluate_budget_extension(
    records: &[StepProgressRecord],
    recon_streak: u32,
) -> (bool, Map<String, Value>) {
    let start = records.len().saturating_sub(BUDGET_EXTENSION_WINDOW);
    let window = &records[start..];

    let tool_steps = window.iter().filter(|record| record.tool_count > 0).count();
    let failed_steps = window.iter().filter(|record| record.failed_tool_step).count();
    let failure_ratio = if tool_steps == 0 {
        0.0
    } else {
        failed_steps as f64 / tool_steps as f64
    };

    let mut repeated_signature_streak = 1usize;
    let mut current_streak = 1usize;
    let mut previous_signature: Option<&str> = None;
    for record in window {
        match previous_signature {
            Some(previous) if previous == record.step_signature => {
                current_streak += 1;
            }
            _ => {
                current_streak = 1;
                previous_signature = Some(record.step_signature.as_str());
            }
        }
        repeated_signature_streak = repeated_signature_streak.max(current_streak);
    }

    let mut prior_action_signatures = HashSet::new();
    for record in &records[..start] {
        prior_action_signatures.extend(record.successful_action_signatures.iter().cloned());
    }

    let mut recent_action_signatures = HashSet::new();
    let mut recent_state_delta_signatures = HashSet::new();
    let mut has_build_or_finalize = false;
    for record in window {
        recent_action_signatures.extend(record.successful_action_signatures.iter().cloned());
        recent_state_delta_signatures.extend(record.state_delta_signatures.iter().cloned());
        has_build_or_finalize |= matches!(record.phase, LoopPhase::Build | LoopPhase::Finalize);
    }

    let novel_action_count = recent_action_signatures
        .difference(&prior_action_signatures)
        .count();
    let state_delta_count = recent_state_delta_signatures.len();
    let positive_signals = usize::from(novel_action_count >= 2)
        + usize::from(state_delta_count >= 2)
        + usize::from(has_build_or_finalize);

    let mut blockers = Vec::new();
    if repeated_signature_streak >= 3 {
        blockers.push("repeated_signatures");
    }
    if failure_ratio > 0.6 {
        blockers.push("high_failure_ratio");
    }
    if recon_streak >= 4 {
        blockers.push("recon_streak");
    }

    let mut payload = Map::new();
    payload.insert("window_size".into(), Value::from(window.len() as u64));
    payload.insert(
        "repeated_signature_streak".into(),
        Value::from(repeated_signature_streak as u64),
    );
    payload.insert("failure_ratio".into(), Value::from(failure_ratio));
    payload.insert("novel_action_count".into(), Value::from(novel_action_count as u64));
    payload.insert("state_delta_count".into(), Value::from(state_delta_count as u64));
    payload.insert("has_build_or_finalize".into(), Value::from(has_build_or_finalize));
    payload.insert("positive_signals".into(), Value::from(positive_signals as u64));
    payload.insert(
        "blockers".into(),
        Value::Array(
            blockers
                .iter()
                .map(|blocker| Value::from((*blocker).to_string()))
                .collect(),
        ),
    );

    (
        blockers.is_empty() && positive_signals >= MIN_EXTENSION_PROGRESS_SIGNALS,
        payload,
    )
}

fn build_partial_completion_text(
    objective: &str,
    loop_metrics: &LoopMetrics,
    records: &[StepProgressRecord],
) -> String {
    let mut completed_previews = Vec::new();
    for record in records.iter().rev().take(BUDGET_EXTENSION_WINDOW) {
        for preview in &record.completed_previews {
            if !completed_previews.contains(preview) {
                completed_previews.push(preview.clone());
            }
            if completed_previews.len() >= 3 {
                break;
            }
        }
        if completed_previews.len() >= 3 {
            break;
        }
    }

    let completed_block = if completed_previews.is_empty() {
        "- The run gathered additional context but did not converge on a final artifact before the bounded limit.".to_string()
    } else {
        completed_previews
            .iter()
            .map(|item| format!("- {item}"))
            .collect::<Vec<_>>()
            .join("\n")
    };

    let mut next_actions = Vec::new();
    if loop_metrics.termination_reason == "budget_no_progress" {
        next_actions.push(
            "Stop repeating the stalled loop and resume with a narrower next slice or a different tactic."
                .to_string(),
        );
    }
    if loop_metrics.termination_reason == "budget_cap" {
        next_actions.push(
            "Resume from the saved state and focus on finishing the deliverable instead of reopening the full search space."
                .to_string(),
        );
    }
    next_actions.push(format!("Continue the objective with the strongest completed lead: {objective}"));
    next_actions.push(
        "Turn the completed work below into a concrete artifact or summary before doing more exploration."
            .to_string(),
    );

    format!(
        "Partial completion for objective: {objective}\nStopped after {} steps with {} budget extension(s). Termination reason: {}.\n\nCompleted work:\n{}\n\nRemaining work:\n- Finish the deliverable using the completed work below and avoid repeating the stalled loop.\n\nSuggested next actions:\n{}",
        loop_metrics.steps,
        loop_metrics.extensions_granted,
        loop_metrics.termination_reason,
        completed_block,
        next_actions
            .iter()
            .take(4)
            .map(|item| format!("- {item}"))
            .collect::<Vec<_>>()
            .join("\n")
    )
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
    solve_with_initial_context(objective, config, emitter, cancel, None).await;
}

/// Real solve flow with optional initial structured context.
pub async fn solve_with_initial_context(
    objective: &str,
    config: &AgentConfig,
    emitter: &dyn SolveEmitter,
    cancel: CancellationToken,
    initial_context: Option<SolveInitialContext>,
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
    emitter.emit_trace(&format!("Solving with {}/{}", provider, model.model_name()));

    // 2. Build tools and messages
    let tool_defs = build_tool_defs(&provider);
    let mut tools = WorkspaceTools::new(config);

    let system_prompt =
        build_system_prompt(config.recursive, config.acceptance_criteria, config.demo);
    let initial_user_message = match build_initial_user_message(
        objective,
        config,
        initial_context.as_ref(),
    ) {
        Ok(message) => message,
        Err(err) => {
            emitter.emit_trace(&format!(
                "[solve] failed to serialize initial context; falling back to plain objective: {err}"
            ));
            objective.to_string()
        }
    };
    let mut messages = vec![
        Message::System {
            content: system_prompt,
        },
        Message::User {
            content: initial_user_message,
        },
    ];

    let mut loop_metrics = LoopMetrics::default();
    let mut last_guardrail_streak = 0u32;
    let mut active_curator_phase: Option<LoopPhase> = None;
    let mut pending_curator_deltas: Vec<CuratorStateDelta> = Vec::new();
    let mut step_records: Vec<StepProgressRecord> = Vec::new();
    let mut active_step_budget = config.max_steps_per_call.max(1) as usize;
    let max_total_steps = active_step_budget
        + if config.budget_extension_enabled {
            (config.budget_extension_block_steps.max(1) * config.budget_extension_max_blocks.max(0))
                as usize
        } else {
            0
        };

    // 4. Agentic loop
    for step in 1..=max_total_steps {
        if cancel.is_cancelled() {
            tools.cleanup();
            loop_metrics.termination_reason = "cancelled".into();
            flush_pending_curator_checkpoint(
                &mut pending_curator_deltas,
                "cancelled",
                config,
                &cancel,
                emitter,
            )
            .await;
            emitter.emit_error("Cancelled");
            return;
        }

        let step_start = std::time::Instant::now();

        // Compact context if it's grown too large (~100k token budget)
        compact_messages(&mut messages, 100_000);

        // Call model with streaming
        let turn = match chat_stream_with_rate_limit_retries(
            model.as_ref(),
            &messages,
            &tool_defs,
            &|delta| emitter.emit_delta(delta),
            &cancel,
            config,
            emitter,
            step,
        )
        .await
        {
            Ok(t) => t,
            Err(e) => {
                let msg = e.to_string();
                tools.cleanup();
                loop_metrics.termination_reason = if msg == "Cancelled" {
                    "cancelled".into()
                } else {
                    "model_error".into()
                };
                flush_pending_curator_checkpoint(
                    &mut pending_curator_deltas,
                    if msg == "Cancelled" {
                        "cancelled"
                    } else {
                        "model_error"
                    },
                    config,
                    &cancel,
                    emitter,
                )
                .await;
                if msg == "Cancelled" {
                    emitter.emit_error("Cancelled");
                } else {
                    emitter.emit_error(&msg);
                }
                return;
            }
        };

        loop_metrics.steps = step as u32;
        loop_metrics.model_turns += 1;

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

        // No tool calls → final answer (unless rejected by governance)
        if turn.tool_calls.is_empty() {
            if turn.text.trim().is_empty() {
                emitter.emit_trace(&format!(
                    "[d0/s{step}] empty model response, requesting tool use or concrete final answer"
                ));
                messages.push(Message::User {
                    content: "No tool calls and no final answer were returned. Continue solving: use tools if needed or return the concrete final deliverable.".to_string(),
                });
                continue;
            }
            if is_meta_final_text(&turn.text, objective) {
                loop_metrics.final_rejections += 1;
                emitter.emit_trace(&format!(
                    "[d0/s{step}] rejected meta final answer; requesting concrete deliverable"
                ));
                messages.push(Message::User {
                    content: "Your previous response was process/meta commentary rather than a concrete final answer. Continue solving: use tools if needed and return a direct final deliverable.".to_string(),
                });
                continue;
            }
            let phase = LoopPhase::Finalize;
            increment_phase(&mut loop_metrics, &phase);
            loop_metrics.termination_reason = "success".into();
            emitter.emit_loop_health(0, step as u32, phase.clone(), loop_metrics.clone(), true);
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
                loop_phase: Some(phase),
                loop_metrics: Some(loop_metrics.clone()),
            });
            flush_pending_curator_checkpoint(
                &mut pending_curator_deltas,
                "finalize",
                config,
                &cancel,
                emitter,
            )
            .await;
            emitter.emit_complete(&turn.text, Some(loop_metrics.clone()), None);
            tools.cleanup();
            return;
        }

        loop_metrics.tool_calls += turn.tool_calls.len() as u32;

        // Execute each tool call and collect results
        let mut tool_observations: Vec<(String, String, String, String, bool)> = Vec::new();
        for tc in &turn.tool_calls {
            if cancel.is_cancelled() {
                tools.cleanup();
                flush_pending_curator_checkpoint(
                    &mut pending_curator_deltas,
                    "cancelled",
                    config,
                    &cancel,
                    emitter,
                )
                .await;
                emitter.emit_error("Cancelled");
                return;
            }

            emitter.emit_trace(&format!("Executing tool: {} ({})", tc.name, tc.id));
            let result = tools.execute(&tc.name, &tc.arguments).await;
            let result_content = result.content;
            let result_is_error = result.is_error;

            if result_is_error {
                emitter.emit_trace(&format!(
                    "Tool {} error: {}",
                    tc.name,
                    safe_prefix(&result_content, 200)
                ));
            }

            messages.push(Message::Tool {
                tool_call_id: tc.id.clone(),
                content: result_content.clone(),
            });
            tool_observations.push((
                tc.id.clone(),
                tc.name.clone(),
                tc.arguments.clone(),
                result_content,
                result_is_error,
            ));
        }

        let phase = classify_loop_phase(&turn.tool_calls, false);
        if let Some(checkpoint) = take_curator_phase_checkpoint(
            &mut pending_curator_deltas,
            &mut active_curator_phase,
            phase.clone(),
        ) {
            emit_curator_checkpoint(checkpoint, config, &cancel, emitter).await;
        }

        if let Some(delta) =
            build_state_delta(step as u32, phase.clone(), objective, &tool_observations)
        {
            pending_curator_deltas.push(delta);
        }
        if matches!(phase, LoopPhase::Investigate) {
            loop_metrics.recon_streak += 1;
        } else {
            loop_metrics.recon_streak = 0;
            last_guardrail_streak = 0;
        }
        loop_metrics.max_recon_streak =
            loop_metrics.max_recon_streak.max(loop_metrics.recon_streak);
        increment_phase(&mut loop_metrics, &phase);
        if matches!(phase, LoopPhase::Investigate)
            && should_emit_recon_guardrail(loop_metrics.recon_streak, last_guardrail_streak)
        {
            loop_metrics.guardrail_warnings += 1;
            last_guardrail_streak = loop_metrics.recon_streak;
            emitter.emit_trace(&format!(
                "[d0/s{step}] soft guardrail: multiple consecutive recon steps without artifacts; nudging toward implementation"
            ));
            messages.push(Message::User {
                content: "Soft guardrail: you've spent multiple consecutive steps in read/list/search mode without producing artifacts. Move to implementation now: edit files, run targeted validation, and return concrete outputs.".to_string(),
            });
        }
        step_records.push(build_step_progress_record(
            &turn.tool_calls,
            &tool_observations,
            phase.clone(),
        ));
        emitter.emit_loop_health(0, step as u32, phase.clone(), loop_metrics.clone(), false);

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
            loop_phase: Some(phase),
            loop_metrics: Some(loop_metrics.clone()),
        });

        // Budget warnings
        let remaining = active_step_budget.saturating_sub(step);
        if remaining == active_step_budget / 2 {
            emitter.emit_trace(&format!(
                "Step budget: {remaining}/{active_step_budget} steps remaining (50%)"
            ));
        } else if remaining == active_step_budget / 4 {
            emitter.emit_trace(&format!(
                "Step budget: {remaining}/{active_step_budget} steps remaining (25%)"
            ));
        }

        if step >= active_step_budget {
            let (eligible, evaluation) =
                evaluate_budget_extension(&step_records, loop_metrics.recon_streak);
            loop_metrics.extension_eligible_checks += 1;
            emitter.emit_trace(&format!(
                "[d0/s{step}] budget boundary reached: eligible={} evaluation={}",
                eligible,
                Value::Object(evaluation.clone())
            ));
            let can_extend = config.budget_extension_enabled
                && loop_metrics.extensions_granted < config.budget_extension_max_blocks as u32
                && eligible;
            if can_extend {
                loop_metrics.extensions_granted += 1;
                active_step_budget += config.budget_extension_block_steps.max(1) as usize;
                messages.push(Message::User {
                    content: "Progress-based budget extension granted. You have a small number of extra steps. Finish the deliverable now and avoid repeating the same loop.".to_string(),
                });
                continue;
            }

            if loop_metrics.extensions_granted >= config.budget_extension_max_blocks as u32 {
                loop_metrics.extension_denials_cap += 1;
                loop_metrics.termination_reason = "budget_cap".into();
            } else {
                loop_metrics.extension_denials_no_progress += 1;
                loop_metrics.termination_reason = "budget_no_progress".into();
            }

            tools.cleanup();
            flush_pending_curator_checkpoint(
                &mut pending_curator_deltas,
                "budget_exhausted",
                config,
                &cancel,
                emitter,
            )
            .await;
            emitter.emit_complete(
                &build_partial_completion_text(objective, &loop_metrics, &step_records),
                Some(loop_metrics.clone()),
                Some(CompletionMeta {
                    kind: "partial".into(),
                    reason: loop_metrics.termination_reason.clone(),
                    steps_used: loop_metrics.steps,
                    max_steps: active_step_budget as u32,
                    extensions_granted: loop_metrics.extensions_granted,
                    extension_block_steps: config.budget_extension_block_steps.max(1) as u32,
                    extension_max_blocks: config.budget_extension_max_blocks.max(0) as u32,
                }),
            );
            return;
        }
    }

    // Budget exhausted
    tools.cleanup();
    loop_metrics.termination_reason = "budget_cap".into();
    flush_pending_curator_checkpoint(
        &mut pending_curator_deltas,
        "budget_exhausted",
        config,
        &cancel,
        emitter,
    )
    .await;
    emitter.emit_complete(
        &build_partial_completion_text(objective, &loop_metrics, &step_records),
        Some(loop_metrics.clone()),
        Some(CompletionMeta {
            kind: "partial".into(),
            reason: loop_metrics.termination_reason.clone(),
            steps_used: loop_metrics.steps,
            max_steps: active_step_budget as u32,
            extensions_granted: loop_metrics.extensions_granted,
            extension_block_steps: config.budget_extension_block_steps.max(1) as u32,
            extension_max_blocks: config.budget_extension_max_blocks.max(0) as u32,
        }),
    );
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Arc, Mutex};

    fn tool_call(name: &str) -> crate::model::ToolCall {
        crate::model::ToolCall {
            id: format!("call-{name}"),
            name: name.to_string(),
            arguments: "{}".to_string(),
        }
    }

    fn progress_record(
        phase: LoopPhase,
        step_signature: &str,
        action_sigs: &[&str],
        delta_sigs: &[&str],
        previews: &[&str],
        failed_tool_step: bool,
    ) -> StepProgressRecord {
        StepProgressRecord {
            phase,
            step_signature: step_signature.to_string(),
            tool_count: 1,
            failed_tool_step,
            successful_action_signatures: action_sigs.iter().map(|s| (*s).to_string()).collect(),
            state_delta_signatures: delta_sigs.iter().map(|s| (*s).to_string()).collect(),
            completed_previews: previews.iter().map(|s| (*s).to_string()).collect(),
        }
    }

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
            self.events.lock().unwrap().push(RecordedEvent::Step(event));
        }

        fn emit_complete(
            &self,
            result: &str,
            _loop_metrics: Option<LoopMetrics>,
            _completion: Option<CompletionMeta>,
        ) {
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
        assert!(
            events.len() >= 4,
            "expected at least 4 events, got {}",
            events.len()
        );

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

        let has_complete = events
            .iter()
            .any(|e| matches!(e, RecordedEvent::Complete(_)));
        assert!(
            !has_complete,
            "should not have a Complete event when cancelled"
        );
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
        assert!(
            has_error,
            "expected Cancelled error after mid-flight cancel"
        );

        // Should NOT have a Complete event
        let has_complete = recorded
            .iter()
            .any(|e| matches!(e, RecordedEvent::Complete(_)));
        assert!(
            !has_complete,
            "should not have Complete after mid-flight cancel"
        );
    }

    #[test]
    fn test_evaluate_budget_extension_grants_on_real_progress() {
        let records = vec![
            progress_record(
                LoopPhase::Build,
                "write_file|artifact=1|error=0",
                &["write_file|{\"path\":\"a.txt\"}"],
                &["write_file|wrote a.txt"],
                &["Wrote a.txt"],
                false,
            ),
            progress_record(
                LoopPhase::Build,
                "write_file|artifact=1|error=0",
                &["write_file|{\"path\":\"b.txt\"}"],
                &["write_file|wrote b.txt"],
                &["Wrote b.txt"],
                false,
            ),
        ];

        let (eligible, payload) = evaluate_budget_extension(&records, 0);
        assert!(eligible, "expected progress window to earn an extension");
        assert_eq!(payload.get("novel_action_count"), Some(&Value::from(2u64)));
        assert_eq!(payload.get("state_delta_count"), Some(&Value::from(2u64)));
        assert_eq!(
            payload.get("blockers"),
            Some(&Value::Array(Vec::new()))
        );
    }

    #[test]
    fn test_evaluate_budget_extension_blocks_repeated_signatures() {
        let records = vec![
            progress_record(
                LoopPhase::Investigate,
                "run_shell|artifact=0|error=0",
                &["run_shell|{\"command\":\"echo a\"}"],
                &["run_shell|echo a"],
                &["echo a"],
                false,
            ),
            progress_record(
                LoopPhase::Investigate,
                "run_shell|artifact=0|error=0",
                &["run_shell|{\"command\":\"echo b\"}"],
                &["run_shell|echo b"],
                &["echo b"],
                false,
            ),
            progress_record(
                LoopPhase::Investigate,
                "run_shell|artifact=0|error=0",
                &["run_shell|{\"command\":\"echo c\"}"],
                &["run_shell|echo c"],
                &["echo c"],
                false,
            ),
        ];

        let (eligible, payload) = evaluate_budget_extension(&records, 0);
        assert!(!eligible, "repeated signatures should block extension");
        let blockers = payload
            .get("blockers")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        assert!(blockers.contains(&Value::from("repeated_signatures")));
    }

    #[test]
    fn test_normalize_progress_fragment_truncates_on_utf8_boundary() {
        let normalized =
            normalize_progress_fragment("[Step 1/100] [Context 10/20] 日本語テスト", 7);

        assert_eq!(normalized, "日本");
        assert!(normalized.len() <= 7);
    }

    #[test]
    fn test_summarize_observation_truncates_on_utf8_boundary() {
        let summary = summarize_observation("abc日本語の長い説明\nsecond line", 8);

        assert_eq!(summary, "abc...");
        assert!(summary.ends_with("..."));
    }

    #[test]
    fn test_summarize_observation_small_limit_still_returns_ellipsis() {
        let summary = summarize_observation("日本語の長い説明", 2);

        assert_eq!(summary, "...");
    }

    #[test]
    fn test_build_partial_completion_text_mentions_budget_reason_and_preview() {
        let records = vec![progress_record(
            LoopPhase::Build,
            "write_file|artifact=1|error=0",
            &["write_file|{\"path\":\"artifact.txt\"}"],
            &["write_file|wrote artifact"],
            &["Wrote 8 chars to artifact.txt"],
            false,
        )];
        let loop_metrics = LoopMetrics {
            steps: 4,
            model_turns: 4,
            tool_calls: 2,
            investigate_steps: 0,
            build_steps: 1,
            iterate_steps: 0,
            finalize_steps: 0,
            recon_streak: 0,
            max_recon_streak: 0,
            guardrail_warnings: 0,
            final_rejections: 0,
            extensions_granted: 1,
            extension_eligible_checks: 2,
            extension_denials_no_progress: 0,
            extension_denials_cap: 1,
            termination_reason: "budget_cap".into(),
        };

        let text = build_partial_completion_text(
            "finish the artifact",
            &loop_metrics,
            &records,
        );

        assert!(text.contains("Partial completion for objective: finish the artifact"));
        assert!(text.contains("Termination reason: budget_cap"));
        assert!(text.contains("Wrote 8 chars to artifact.txt"));
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

    #[test]
    fn test_take_curator_phase_checkpoint_flushes_previous_phase_only() {
        let mut pending = vec![CuratorStateDelta {
            step: 1,
            phase: LoopPhase::Investigate,
            objective: "Investigate sources".to_string(),
            observations: vec![crate::engine::curator::CuratorToolObservation {
                tool_call_id: "call-1".to_string(),
                tool_name: "read_file".to_string(),
                arguments_json: "{}".to_string(),
                output_excerpt: "source details".to_string(),
                is_error: false,
            }],
        }];
        let mut active_phase = Some(LoopPhase::Investigate);

        let checkpoint =
            take_curator_phase_checkpoint(&mut pending, &mut active_phase, LoopPhase::Build)
                .expect("phase transition should flush checkpoint");

        assert_eq!(checkpoint.boundary, "phase_transition:Investigate->Build");
        assert_eq!(checkpoint.deltas.len(), 1);
        assert_eq!(checkpoint.deltas[0].phase, LoopPhase::Investigate);
        assert!(pending.is_empty());
        assert_eq!(active_phase, Some(LoopPhase::Build));
    }

    #[test]
    fn test_take_curator_phase_checkpoint_initializes_without_flush() {
        let mut pending = Vec::new();
        let mut active_phase = None;

        let checkpoint =
            take_curator_phase_checkpoint(&mut pending, &mut active_phase, LoopPhase::Investigate);

        assert!(checkpoint.is_none());
        assert_eq!(active_phase, Some(LoopPhase::Investigate));
    }

    #[test]
    fn test_take_pending_curator_checkpoint_returns_none_when_empty() {
        let mut pending = Vec::new();
        assert!(take_pending_curator_checkpoint(&mut pending, "finalize").is_none());
    }

    #[test]
    fn test_estimate_tokens() {
        let messages = vec![
            Message::System {
                content: "System prompt".into(),
            }, // 13 chars
            Message::User {
                content: "Hello".into(),
            }, // 5 chars
            Message::Tool {
                tool_call_id: "t1".into(),
                content: "x".repeat(4000),
            },
        ];
        let tokens = estimate_tokens(&messages);
        // (13 + 5 + 4000) / 4 = 1004
        assert_eq!(tokens, 1004);
    }

    #[test]
    fn test_build_initial_user_message_preserves_plain_objective_without_context() {
        let config = AgentConfig::default();
        let message = build_initial_user_message("just objective", &config, None).unwrap();
        assert_eq!(message, "just objective");
    }

    #[test]
    fn test_build_initial_user_message_includes_context_payload() {
        let config = AgentConfig::default();
        let message = build_initial_user_message(
            "investigate",
            &config,
            Some(&SolveInitialContext {
                session_id: Some("session-1".to_string()),
                session_dir: Some("/tmp/session-1".to_string()),
                question_reasoning_packet: Some(serde_json::json!({
                    "reasoning_mode": "question_centric",
                    "focus_question_ids": ["q_1"],
                    "candidate_actions": [{
                        "id": "ca_q_q_1",
                        "action_type": "verify_claim",
                        "status": "proposed",
                    }],
                    "findings": {
                        "supported": [],
                        "contested": [],
                        "unresolved": [],
                    },
                    "contradictions": [],
                    "evidence_index": {},
                })),
            }),
        )
        .unwrap();

        let parsed: Value = serde_json::from_str(&message).unwrap();
        assert_eq!(
            parsed["objective"],
            Value::String("investigate".to_string())
        );
        assert_eq!(parsed["session_id"], Value::String("session-1".to_string()));
        assert_eq!(
            parsed["session_dir"],
            Value::String("/tmp/session-1".to_string())
        );
        assert_eq!(
            parsed["question_reasoning_packet"]["focus_question_ids"],
            serde_json::json!(["q_1"])
        );
        assert_eq!(
            parsed["question_reasoning_packet"]["candidate_actions"][0]["id"],
            serde_json::json!("ca_q_q_1")
        );
        assert!(parsed.get("timestamp").is_some());
        assert_eq!(
            parsed["max_steps_per_call"],
            Value::from(config.max_steps_per_call)
        );
    }

    #[test]
    fn test_build_initial_user_message_omits_packet_when_empty() {
        let config = AgentConfig::default();
        let message = build_initial_user_message(
            "investigate",
            &config,
            Some(&SolveInitialContext {
                session_id: Some("session-1".to_string()),
                session_dir: Some("/tmp/session-1".to_string()),
                question_reasoning_packet: None,
            }),
        )
        .unwrap();

        let parsed: Value = serde_json::from_str(&message).unwrap();
        assert!(parsed.get("question_reasoning_packet").is_none());
        assert_eq!(
            parsed["objective"],
            Value::String("investigate".to_string())
        );
    }

    #[test]
    fn test_compact_messages_no_op_when_under_limit() {
        let mut messages = vec![
            Message::System {
                content: "System".into(),
            },
            Message::User {
                content: "Hello".into(),
            },
            Message::Tool {
                tool_call_id: "t1".into(),
                content: "Short result".into(),
            },
        ];
        compact_messages(&mut messages, 100_000);
        // Should be unchanged
        if let Message::Tool { content, .. } = &messages[2] {
            assert_eq!(content, "Short result");
        }
    }

    #[test]
    fn test_compact_messages_truncates_old_tool_results() {
        let big_result = "x".repeat(8000);
        let mut messages = vec![
            Message::System {
                content: "System".into(),
            },
            Message::User {
                content: "Hello".into(),
            },
        ];

        // Add 15 old steps (assistant + tool pairs) to exceed keep_recent
        for i in 0..15 {
            messages.push(Message::Assistant {
                content: format!("step{i}"),
                tool_calls: None,
            });
            messages.push(Message::Tool {
                tool_call_id: format!("t{i}"),
                content: big_result.clone(),
            });
        }

        // Total: ~(6 + 5 + 15*(5+8000)) / 4 ≈ 30_000 tokens
        // Set limit below that to trigger compaction
        compact_messages(&mut messages, 10_000);

        // Old tool result (index 3, early in the list) should be truncated
        if let Message::Tool { content, .. } = &messages[3] {
            assert!(
                content.len() < 300,
                "old tool result should be truncated, got {} chars",
                content.len()
            );
            assert!(content.contains("truncated"));
        }

        // Recent tool result (last one) should be intact
        let last_tool = messages
            .iter()
            .rev()
            .find(|m| matches!(m, Message::Tool { .. }))
            .unwrap();
        if let Message::Tool { content, .. } = last_tool {
            assert_eq!(content.len(), 8000, "recent tool result should be intact");
        }
    }

    #[test]
    fn test_is_meta_final_text_rejects_empty_and_strong_process_meta() {
        assert!(is_meta_final_text("", "Answer the question directly"));
        assert!(is_meta_final_text(
            "I should start by checking the workspace layout.",
            "Answer the question directly"
        ));
        assert!(!is_meta_final_text(
            "Completed the fix and updated the failing test.",
            "Answer the question directly"
        ));
    }

    #[test]
    fn test_is_meta_final_text_respects_objective_policy_for_structural_meta() {
        assert!(is_meta_final_text(
            "Here is my plan for finishing the task.",
            "Answer the question directly"
        ));
        assert!(!is_meta_final_text(
            "Here is my plan for finishing the task.",
            "Write a plan for finishing the task"
        ));
        assert!(is_meta_final_text(
            "Here is my plan: I will inspect files and then implement.",
            "Write a plan for finishing the task"
        ));
    }

    #[test]
    fn test_classify_loop_phase_recon_only_is_investigate() {
        let phase = classify_loop_phase(&[tool_call("read_file"), tool_call("list_files")], false);
        assert_eq!(phase, LoopPhase::Investigate);
    }

    #[test]
    fn test_classify_loop_phase_artifact_tools_are_build() {
        let phase = classify_loop_phase(&[tool_call("read_file"), tool_call("write_file")], false);
        assert_eq!(phase, LoopPhase::Build);
    }

    #[test]
    fn test_classify_loop_phase_mixed_recon_and_non_recon_is_iterate() {
        let phase = classify_loop_phase(&[tool_call("read_file"), tool_call("run_shell")], false);
        assert_eq!(phase, LoopPhase::Iterate);
    }

    #[test]
    fn test_should_emit_recon_guardrail_once_per_episode() {
        let mut last_guardrail_streak = 0;

        assert!(!should_emit_recon_guardrail(1, last_guardrail_streak));
        assert!(!should_emit_recon_guardrail(2, last_guardrail_streak));
        assert!(should_emit_recon_guardrail(3, last_guardrail_streak));

        last_guardrail_streak = 3;
        assert!(!should_emit_recon_guardrail(4, last_guardrail_streak));
        assert!(!should_emit_recon_guardrail(5, last_guardrail_streak));

        last_guardrail_streak = 0;
        assert!(!should_emit_recon_guardrail(1, last_guardrail_streak));
        assert!(!should_emit_recon_guardrail(2, last_guardrail_streak));
        assert!(should_emit_recon_guardrail(3, last_guardrail_streak));
    }
}

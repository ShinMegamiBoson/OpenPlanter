from __future__ import annotations

import json
import random
import re
import time
import threading
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import AgentConfig
from .model import BaseModel, ImageData, ModelError, ModelTurn, RateLimitError, ToolCall, ToolResult
from .prompts import build_system_prompt
from .replay_log import ReplayLogger
from .tool_defs import get_tool_definitions
from .tools import WorkspaceTools

EventCallback = Callable[[str], None]
StepCallback = Callable[[dict[str, Any]], None]
ContentDeltaCallback = Callable[[str, str], None]


_RECON_TOOL_NAMES = {
    "list_files",
    "search_files",
    "repo_map",
    "web_search",
    "fetch_url",
    "read_file",
    "read_image",
    "audio_transcribe",
    "list_artifacts",
    "read_artifact",
}
_ARTIFACT_TOOL_NAMES = {
    "write_file",
    "apply_patch",
    "edit_file",
    "hashline_edit",
}
_WEAK_STRUCTURAL_META_PATTERNS = (
    re.compile(r"^\s*(here(?:'s| is)\s+(?:my|the)\s+(?:plan|approach|analysis))\b", re.I),
)
_STRONG_PROCESS_META_PATTERNS = (
    re.compile(r"\b(i\s+(?:will|can|should|need to|want to|am going to|plan to))\b", re.I),
    re.compile(r"\b(let me|next,?\s+i\s+will|i\s+should\s+start\s+by)\b", re.I),
)
_META_DELIVERABLE_OBJECTIVE_PATTERN = re.compile(
    r"\b(plan(?:ning)?|approach|strategy|outline|spec(?:ification)?|design|roadmap|proposal|review|audit|analysis|analyze|brainstorm)\b",
    re.I,
)


def _summarize_args(args: dict[str, Any], max_len: int = 120) -> str:
    """One-line summary of tool call arguments."""
    parts: list[str] = []
    for k, v in args.items():
        s = str(v)
        if len(s) > 60:
            s = s[:57] + "..."
        parts.append(f"{k}={s}")
    joined = ", ".join(parts)
    if len(joined) > max_len:
        joined = joined[:max_len - 3] + "..."
    return joined


def _summarize_observation(text: str, max_len: int = 200) -> str:
    """First line or truncated preview of an observation."""
    first = text.split("\n", 1)[0].strip()
    if len(first) > max_len:
        first = first[:max_len - 3] + "..."
    lines = text.count("\n") + 1
    chars = len(text)
    if lines > 1:
        return f"{first} ({lines} lines, {chars} chars)"
    return first


# Legacy alias for tests and external code that reference SYSTEM_PROMPT directly.
SYSTEM_PROMPT = build_system_prompt(recursive=True)

# Context window sizes (tokens) for condensation heuristic.
_MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-opus-4-6": 200_000,
    "claude-sonnet-4-5-20250929": 200_000,
    "claude-haiku-4-5-20251001": 200_000,
    "gpt-4o": 128_000,
    "gpt-4.1": 1_000_000,
    "gpt-5-turbo-16k": 16_000,
}
_DEFAULT_CONTEXT_WINDOW = 128_000
_CONDENSATION_THRESHOLD = 0.75
_BUDGET_EXTENSION_WINDOW = 12
_MIN_EXTENSION_PROGRESS_SIGNALS = 2
_MIN_MEANINGFUL_RESULT_CHARS = 24
_NON_PROGRESS_TOOL_NAMES = _RECON_TOOL_NAMES | {"think"}


def _model_tier(model_name: str, reasoning_effort: str | None = None) -> int:
    """Determine capability tier for a model.  Lower number = higher capability.

    Anthropic chain (by model name):
      opus → 1, sonnet → 2, haiku → 3
    OpenAI codex chain (by reasoning effort):
      xhigh → 1, high → 2, medium → 3, low → 4
    Unknown → 2
    """
    lower = model_name.lower()
    if "opus" in lower:
        return 1
    if "sonnet" in lower:
        return 2
    if "haiku" in lower:
        return 3
    if lower.startswith("gpt-5") and "codex" in lower:
        effort = (reasoning_effort or "").lower()
        return {"xhigh": 1, "high": 2, "medium": 3, "low": 4}.get(effort, 2)
    return 2


def _lowest_tier_model(model_name: str) -> tuple[str, str | None]:
    """Return (model_name, reasoning_effort) for the lowest-tier executor.

    Anthropic models → haiku.  Unknown → no downgrade (return same name).
    """
    lower = model_name.lower()
    if "claude" in lower:
        return ("claude-haiku-4-5-20251001", None)
    return (model_name, None)


ModelFactory = Callable[[str, str | None], "BaseModel"]


@dataclass
class ExternalContext:
    observations: list[str] = field(default_factory=list)

    def add(self, text: str) -> None:
        self.observations.append(text)

    def summary(self, max_items: int = 12, max_chars: int = 8000) -> str:
        if not self.observations:
            return "(empty)"
        if max_items <= 0:
            return "(empty)"
        recent = self.observations[-max_items:]
        joined = "\n\n".join(recent)
        if len(joined) <= max_chars:
            return joined
        return f"{joined[:max_chars]}\n...[truncated external context]..."


@dataclass
class TurnSummary:
    """Compact, serializable summary for a completed top-level turn."""

    turn_number: int
    objective: str
    result_preview: str
    timestamp: str
    steps_used: int = 0
    replay_seq_start: int = 0

    def to_dict(self) -> dict[str, int | str]:
        return {
            "turn_number": self.turn_number,
            "objective": self.objective,
            "result_preview": self.result_preview,
            "timestamp": self.timestamp,
            "steps_used": self.steps_used,
            "replay_seq_start": self.replay_seq_start,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "TurnSummary":
        return cls(
            turn_number=int(payload["turn_number"]),
            objective=str(payload.get("objective", "")),
            result_preview=str(payload.get("result_preview", "")),
            timestamp=str(payload.get("timestamp", "")),
            steps_used=int(payload.get("steps_used", 0) or 0),
            replay_seq_start=int(payload.get("replay_seq_start", 0) or 0),
        )


@dataclass
class StepProgressRecord:
    step: int
    phase: str
    step_signature: str
    tool_count: int
    failed_tool_step: bool
    successful_action_signatures: set[str] = field(default_factory=set)
    state_delta_signatures: set[str] = field(default_factory=set)
    completed_previews: list[str] = field(default_factory=list)


def _normalize_progress_fragment(text: str, max_len: int = 120) -> str:
    collapsed = re.sub(r"\s+", " ", text.strip().lower())
    collapsed = re.sub(r"^(?:\[[^\]]+\]\s*)+", "", collapsed)
    if len(collapsed) > max_len:
        collapsed = collapsed[: max_len - 3] + "..."
    return collapsed


def _action_signature(name: str, args: dict[str, Any]) -> str:
    payload = json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    payload = payload[:160]
    return f"{name}|{payload}"


def _looks_like_failed_tool_result(name: str, result: ToolResult) -> bool:
    if result.is_error:
        return True
    content = result.content.strip()
    normalized = _normalize_progress_fragment(content, max_len=200)
    exit_match = re.search(r"\[exit_code=(-?\d+)\]", content)
    if exit_match:
        try:
            if int(exit_match.group(1)) != 0:
                return True
        except ValueError:
            pass
    failure_prefixes = (
        "file not found:",
        "path is a directory, not a file:",
        "failed to ",
        "blocked:",
        "blocked by policy:",
        "unsupported image format:",
        "image too large:",
        "max recursion depth reached;",
        "cannot delegate to higher-tier model",
        "task cancelled.",
        "tool ",
    )
    if normalized.startswith(failure_prefixes):
        return True
    if normalized.startswith("search_files requires ") or normalized.startswith("read_file requires "):
        return True
    if normalized.startswith("run_shell requires ") or normalized.startswith("apply_patch requires "):
        return True
    return " crashed:" in normalized


def _build_step_progress_record(
    step: int,
    phase: str,
    tool_calls: list[ToolCall],
    results: list[ToolResult],
) -> StepProgressRecord:
    tool_names = [tc.name for tc in tool_calls]
    has_artifact = any(name in _ARTIFACT_TOOL_NAMES for name in tool_names)
    failed_results = [
        _looks_like_failed_tool_result(tool_call.name, result)
        for tool_call, result in zip(tool_calls, results)
    ]
    has_error = any(failed_results)
    record = StepProgressRecord(
        step=step,
        phase=phase,
        step_signature=f"{','.join(sorted(tool_names))}|artifact={int(has_artifact)}|error={int(has_error)}",
        tool_count=len(tool_calls),
        failed_tool_step=has_error,
    )
    for tool_call, result, failed_result in zip(tool_calls, results, failed_results):
        if failed_result or tool_call.name in _NON_PROGRESS_TOOL_NAMES:
            continue
        normalized_result = _normalize_progress_fragment(result.content)
        if len(normalized_result) < _MIN_MEANINGFUL_RESULT_CHARS:
            continue
        record.successful_action_signatures.add(_action_signature(tool_call.name, tool_call.arguments))
        record.state_delta_signatures.add(f"{tool_call.name}|{normalized_result}")
        preview = _summarize_observation(result.content)
        if preview not in record.completed_previews:
            record.completed_previews.append(preview)
    return record


def _evaluate_budget_extension(
    records: list[StepProgressRecord],
    *,
    recon_streak: int,
) -> dict[str, Any]:
    window = records[-_BUDGET_EXTENSION_WINDOW:]
    tool_steps = sum(1 for record in window if record.tool_count > 0)
    failed_steps = sum(1 for record in window if record.failed_tool_step)
    failure_ratio = (failed_steps / tool_steps) if tool_steps else 0.0

    repeated_signature_streak = 1
    current_streak = 1
    previous_signature: str | None = None
    for record in window:
        if previous_signature is not None and record.step_signature == previous_signature:
            current_streak += 1
        else:
            current_streak = 1
            previous_signature = record.step_signature
        repeated_signature_streak = max(repeated_signature_streak, current_streak)

    prior_action_signatures: set[str] = set()
    for record in records[: max(0, len(records) - len(window))]:
        prior_action_signatures.update(record.successful_action_signatures)

    recent_action_signatures: set[str] = set()
    recent_state_delta_signatures: set[str] = set()
    has_build_or_finalize = False
    for record in window:
        recent_action_signatures.update(record.successful_action_signatures)
        recent_state_delta_signatures.update(record.state_delta_signatures)
        has_build_or_finalize = has_build_or_finalize or record.phase in {"build", "finalize"}

    novel_action_signatures = recent_action_signatures - prior_action_signatures
    positive_signals = 0
    if len(novel_action_signatures) >= 2:
        positive_signals += 1
    if len(recent_state_delta_signatures) >= 2:
        positive_signals += 1
    if has_build_or_finalize:
        positive_signals += 1

    blockers: list[str] = []
    if repeated_signature_streak >= 3:
        blockers.append("repeated_signatures")
    if failure_ratio > 0.6:
        blockers.append("high_failure_ratio")
    if recon_streak >= 4:
        blockers.append("recon_streak")

    return {
        "eligible": not blockers and positive_signals >= _MIN_EXTENSION_PROGRESS_SIGNALS,
        "window_size": len(window),
        "repeated_signature_streak": repeated_signature_streak,
        "failure_ratio": failure_ratio,
        "novel_action_count": len(novel_action_signatures),
        "state_delta_count": len(recent_state_delta_signatures),
        "has_build_or_finalize": has_build_or_finalize,
        "positive_signals": positive_signals,
        "blockers": blockers,
    }


def _suggest_next_actions(
    objective: str,
    evaluation: dict[str, Any],
    recent_previews: list[str],
) -> list[str]:
    actions: list[str] = []
    blockers = set(evaluation.get("blockers", []))
    if "repeated_signatures" in blockers:
        actions.append("Stop retrying the same command pattern and switch to a different source or tactic.")
    if "high_failure_ratio" in blockers:
        actions.append("Triage the failing tool calls first so the next run is not dominated by avoidable errors.")
    if "recon_streak" in blockers:
        actions.append("Move from exploration into artifact-building or synthesis before doing more reconnaissance.")
    if recent_previews:
        actions.append("Turn the completed findings below into a concrete artifact or summary before resuming deeper work.")
    actions.append(f"Resume the objective with a narrower next slice: {objective}")
    return actions[:4]


def _render_partial_completion(
    objective: str,
    loop_metrics: dict[str, Any],
    evaluation: dict[str, Any],
    records: list[StepProgressRecord],
) -> str:
    recent_previews: list[str] = []
    for record in reversed(records[-_BUDGET_EXTENSION_WINDOW:]):
        for preview in record.completed_previews:
            if preview not in recent_previews:
                recent_previews.append(preview)
            if len(recent_previews) >= 3:
                break
        if len(recent_previews) >= 3:
            break
    next_actions = _suggest_next_actions(objective, evaluation, recent_previews)
    completed = recent_previews or ["The run gathered additional context but did not converge on a final artifact before the bounded limit."]
    remaining = (
        "Finish the deliverable using the completed work below and avoid repeating the stalled loop."
        if recent_previews
        else "Finish the deliverable with a narrower plan or a different tactic."
    )
    reason = str(loop_metrics.get("termination_reason", "budget_no_progress"))
    header = (
        f"Partial completion for objective: {objective}\n"
        f"Stopped after {int(loop_metrics.get('steps', 0))} steps "
        f"with {int(loop_metrics.get('extensions_granted', 0))} budget extension(s). "
        f"Termination reason: {reason}."
    )
    completed_block = "\n".join(f"- {item}" for item in completed)
    next_actions_block = "\n".join(f"- {item}" for item in next_actions)
    return (
        f"{header}\n\n"
        "Completed work:\n"
        f"{completed_block}\n\n"
        "Remaining work:\n"
        f"- {remaining}\n\n"
        "Suggested next actions:\n"
        f"{next_actions_block}"
    )


@dataclass
class RLMEngine:
    model: BaseModel
    tools: WorkspaceTools
    config: AgentConfig
    system_prompt: str = ""
    session_tokens: dict[str, dict[str, int]] = field(default_factory=dict)
    model_factory: ModelFactory | None = None
    _model_cache: dict[tuple[str, str | None], BaseModel] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    session_dir: Path | None = None
    session_id: str | None = None
    _shell_command_counts: dict[tuple[int, str], int] = field(default_factory=dict)
    _cancel: threading.Event = field(default_factory=threading.Event)
    _pending_image: threading.local = field(default_factory=threading.local)
    last_loop_metrics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.system_prompt:
            self.system_prompt = build_system_prompt(
                self.config.recursive,
                acceptance_criteria=self.config.acceptance_criteria,
                demo=self.config.demo,
            )
        ac = self.config.acceptance_criteria
        tool_defs = get_tool_definitions(include_subtask=self.config.recursive, include_acceptance_criteria=ac)
        if hasattr(self.model, "tool_defs"):
            self.model.tool_defs = tool_defs

    def cancel(self) -> None:
        """Signal the engine to stop after the current model call or tool."""
        self._cancel.set()

    def solve(self, objective: str, on_event: EventCallback | None = None) -> str:
        result, _ = self.solve_with_context(objective=objective, on_event=on_event)
        return result

    def solve_with_context(
        self,
        objective: str,
        context: ExternalContext | None = None,
        on_event: EventCallback | None = None,
        on_step: StepCallback | None = None,
        on_content_delta: ContentDeltaCallback | None = None,
        replay_logger: ReplayLogger | None = None,
        turn_history: list[TurnSummary] | None = None,
        question_reasoning_packet: dict[str, Any] | None = None,
    ) -> tuple[str, ExternalContext]:
        if not objective.strip():
            return "No objective provided.", context or ExternalContext()
        self._cancel.clear()
        with self._lock:
            self._shell_command_counts.clear()
        active_context = context if context is not None else ExternalContext()
        deadline = (time.monotonic() + self.config.max_solve_seconds) if self.config.max_solve_seconds > 0 else 0
        try:
            result = self._solve_recursive(
                objective=objective.strip(),
                depth=0,
                context=active_context,
                on_event=on_event,
                on_step=on_step,
                on_content_delta=on_content_delta,
                deadline=deadline,
                replay_logger=replay_logger,
                turn_history=turn_history,
                question_reasoning_packet=question_reasoning_packet,
            )
        finally:
            cleanup = getattr(self.tools, "cleanup_bg_jobs", None)
            if cleanup:
                cleanup()
        return result, active_context

    def _emit(self, msg: str, on_event: EventCallback | None) -> None:
        if on_event:
            try:
                on_event(msg)
            except Exception:
                pass

    def _clip_observation(self, text: str) -> str:
        return text if len(text) <= self.config.max_observation_chars else (
            f"{text[:self.config.max_observation_chars]}"
            f"\n...[truncated {len(text) - self.config.max_observation_chars} chars]..."
        )

    def _runtime_policy_check(self, name: str, args: dict[str, Any], depth: int) -> str | None:
        if name != "run_shell":
            return None
        command = str(args.get("command", "")).strip()
        if not command:
            return None
        key = (depth, command)
        with self._lock:
            count = self._shell_command_counts.get(key, 0) + 1
            self._shell_command_counts[key] = count
        if count <= 2:
            return None
        return (
            "Blocked by runtime policy: identical run_shell command repeated more than twice "
            "at the same depth. Change strategy instead of retrying the same command."
        )

    def _judge_result(
        self,
        objective: str,
        acceptance_criteria: str,
        result: str,
        current_model: BaseModel | None = None,
    ) -> str:
        """Evaluate a subtask/execute result against acceptance criteria using a cheap judge model."""
        if not self.model_factory:
            return "PASS\n(no judge available)"

        cur = current_model or self.model
        cur_name = getattr(cur, "model", "")
        judge_name, judge_effort = _lowest_tier_model(cur_name)

        cache_key = ("_judge_" + judge_name, judge_effort)
        with self._lock:
            if cache_key not in self._model_cache:
                try:
                    self._model_cache[cache_key] = self.model_factory(judge_name, judge_effort)
                except Exception:
                    return "PASS\n(no judge available)"
            judge_model = self._model_cache[cache_key]
        if hasattr(judge_model, "tool_defs"):
            judge_model.tool_defs = []

        truncated = result[:4000] if len(result) > 4000 else result
        prompt = (
            "You are a judge evaluating whether a task result meets acceptance criteria.\n\n"
            f"Objective: {objective}\n\n"
            f"Acceptance criteria: {acceptance_criteria}\n\n"
            f"Result:\n{truncated}\n\n"
            "Respond with exactly one line starting with PASS: or FAIL: followed by a brief explanation."
        )

        try:
            conversation = judge_model.create_conversation("You are a concise evaluator.", prompt)
            turn = judge_model.complete(conversation)
            verdict = (turn.text or "").strip()
            if not verdict:
                return "PASS\n(judge returned empty response)"
            return verdict
        except Exception as exc:
            return f"PASS\n(judge error: {exc})"

    def _objective_allows_meta_final(self, objective: str) -> bool:
        return bool(_META_DELIVERABLE_OBJECTIVE_PATTERN.search(objective))

    def _is_meta_final_text(self, text: str, objective: str = "") -> bool:
        stripped = text.strip()
        if not stripped:
            return True
        if any(pattern.search(stripped) for pattern in _STRONG_PROCESS_META_PATTERNS):
            return True
        if any(pattern.search(stripped) for pattern in _WEAK_STRUCTURAL_META_PATTERNS):
            return not self._objective_allows_meta_final(objective)
        return False

    def _solve_recursive(
        self,
        objective: str,
        depth: int,
        context: ExternalContext,
        on_event: EventCallback | None = None,
        on_step: StepCallback | None = None,
        on_content_delta: ContentDeltaCallback | None = None,
        deadline: float = 0,
        model_override: BaseModel | None = None,
        replay_logger: ReplayLogger | None = None,
        turn_history: list[TurnSummary] | None = None,
        question_reasoning_packet: dict[str, Any] | None = None,
    ) -> str:
        model = model_override or self.model

        self._emit(f"[depth {depth}] objective: {objective}", on_event)

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if depth == 0 and not self.config.recursive:
            initial_msg_dict = {
                "timestamp": now_iso,
                "objective": objective,
                "max_steps_per_call": self.config.max_steps_per_call,
                "workspace": str(self.config.workspace),
                "external_context_summary": context.summary(),
            }
        else:
            if depth == 0:
                repl_hint = "Begin REPL cycle 1: start with a broad READ of the workspace."
            else:
                repl_hint = "Begin REPL cycle 1: parent has surveyed — READ only what this objective requires, then act."
            initial_msg_dict = {
                "timestamp": now_iso,
                "objective": objective,
                "depth": depth,
                "max_depth": self.config.max_depth,
                "max_steps_per_call": self.config.max_steps_per_call,
                "workspace": str(self.config.workspace),
                "external_context_summary": context.summary(),
                "repl_hint": repl_hint,
            }
        if self.session_dir is not None:
            initial_msg_dict["session_dir"] = str(self.session_dir)
        if self.session_id is not None:
            initial_msg_dict["session_id"] = self.session_id
        if depth == 0 and turn_history:
            initial_msg_dict["turn_history"] = [t.to_dict() for t in turn_history]
            initial_msg_dict["turn_history_note"] = (
                f"{len(turn_history)} prior turn(s). "
                f"Read replay.jsonl/events.jsonl in session_dir for full details."
            )
        if depth == 0 and question_reasoning_packet is not None:
            initial_msg_dict["question_reasoning_packet"] = question_reasoning_packet
        initial_message = json.dumps(initial_msg_dict, ensure_ascii=True)

        conversation = model.create_conversation(self.system_prompt, initial_message)

        loop_metrics: dict[str, Any] = {
            "steps": 0,
            "model_turns": 0,
            "tool_calls": 0,
            "phase_counts": {"investigate": 0, "build": 0, "iterate": 0, "finalize": 0},
            "recon_streak": 0,
            "max_recon_streak": 0,
            "guardrail_warnings": 0,
            "final_rejections": 0,
            "last_guardrail_streak": 0,
            "budget_extension_enabled": bool(self.config.budget_extension_enabled),
            "budget_extension_block_steps": int(self.config.budget_extension_block_steps),
            "budget_extension_max_blocks": int(self.config.budget_extension_max_blocks),
            "extensions_granted": 0,
            "extension_eligible_checks": 0,
            "extension_denials_no_progress": 0,
            "extension_denials_cap": 0,
            "termination_reason": "",
        }
        step_records: list[StepProgressRecord] = []
        active_step_budget = self.config.max_steps_per_call
        max_total_steps = self.config.max_steps_per_call + (
            self.config.budget_extension_block_steps * self.config.budget_extension_max_blocks
            if self.config.budget_extension_enabled
            else 0
        )

        self.last_loop_metrics = loop_metrics

        if replay_logger and replay_logger.needs_header:
            replay_logger.write_header(
                provider=type(model).__name__,
                model=getattr(model, "model", "(unknown)"),
                base_url=getattr(model, "base_url", ""),
                system_prompt=self.system_prompt,
                tool_defs=getattr(model, "tool_defs", None) or [],
                reasoning_effort=getattr(model, "reasoning_effort", None),
                temperature=getattr(model, "temperature", None),
            )

        for step in range(1, max_total_steps + 1):
            if self._cancel.is_set():
                self._emit(f"[d{depth}] cancelled by user", on_event)
                loop_metrics["termination_reason"] = "cancelled"
                self.last_loop_metrics = loop_metrics
                return "Task cancelled."
            if deadline and time.monotonic() > deadline:
                self._emit(f"[d{depth}] wall-clock limit reached", on_event)
                loop_metrics["termination_reason"] = "time_limit"
                self.last_loop_metrics = loop_metrics
                return "Time limit exceeded. Try a more focused objective."
            self._emit(f"[d{depth}/s{step}] calling model...", on_event)
            t0 = time.monotonic()
            # Stream thinking/text deltas only for top-level calls
            if on_content_delta and depth == 0 and hasattr(model, "on_content_delta"):
                model.on_content_delta = on_content_delta
            try:
                rate_limit_retries = 0
                while True:
                    if self._cancel.is_set():
                        self._emit(f"[d{depth}] cancelled by user", on_event)
                        self.last_loop_metrics = loop_metrics
                        return "Task cancelled."
                    try:
                        turn = model.complete(conversation)
                        break
                    except RateLimitError as exc:
                        if rate_limit_retries >= self.config.rate_limit_max_retries:
                            self._emit(f"[d{depth}/s{step}] model error: {exc}", on_event)
                            loop_metrics["termination_reason"] = "model_error"
                            self.last_loop_metrics = loop_metrics
                            return f"Model error at depth {depth}, step {step}: {exc}"
                        rate_limit_retries += 1
                        delay: float | None = None
                        if exc.retry_after_sec is not None:
                            delay = min(
                                max(exc.retry_after_sec, 0.0),
                                self.config.rate_limit_retry_after_cap_sec,
                            )
                        if delay is None:
                            delay = self.config.rate_limit_backoff_base_sec * (2 ** (rate_limit_retries - 1))
                        delay += random.uniform(0.0, 0.25)
                        delay = min(delay, self.config.rate_limit_backoff_max_sec)
                        if deadline and (time.monotonic() + delay) > deadline:
                            self._emit(f"[d{depth}] wall-clock limit reached", on_event)
                            loop_metrics["termination_reason"] = "time_limit"
                            self.last_loop_metrics = loop_metrics
                            return "Time limit exceeded. Try a more focused objective."
                        provider_code = f" ({exc.provider_code})" if exc.provider_code is not None else ""
                        self._emit(
                            f"[d{depth}/s{step}] rate limited{provider_code}. "
                            f"Sleeping {delay:.1f}s before retry {rate_limit_retries}/{self.config.rate_limit_max_retries}...",
                            on_event,
                        )
                        if delay > 0:
                            time.sleep(delay)
            except ModelError as exc:
                self._emit(f"[d{depth}/s{step}] model error: {exc}", on_event)
                loop_metrics["termination_reason"] = "model_error"
                self.last_loop_metrics = loop_metrics
                return f"Model error at depth {depth}, step {step}: {exc}"
            finally:
                if hasattr(model, "on_content_delta"):
                    model.on_content_delta = None
            elapsed = time.monotonic() - t0
            loop_metrics["steps"] = step
            loop_metrics["model_turns"] += 1

            if replay_logger:
                try:
                    replay_logger.log_call(
                        depth=depth,
                        step=step,
                        messages=conversation.get_messages(),
                        response=turn.raw_response,
                        input_tokens=turn.input_tokens,
                        output_tokens=turn.output_tokens,
                        elapsed_sec=elapsed,
                    )
                except OSError:
                    pass

            # Accumulate token usage per model
            if turn.input_tokens or turn.output_tokens:
                model_name = getattr(model, "model", "(unknown)")
                with self._lock:
                    bucket = self.session_tokens.setdefault(model_name, {"input": 0, "output": 0})
                    bucket["input"] += turn.input_tokens
                    bucket["output"] += turn.output_tokens

            model.append_assistant_turn(conversation, turn)

            # Context condensation
            if turn.input_tokens:
                model_name = getattr(model, "model", "(unknown)")
                context_window = _MODEL_CONTEXT_WINDOWS.get(model_name, _DEFAULT_CONTEXT_WINDOW)
                if turn.input_tokens > _CONDENSATION_THRESHOLD * context_window:
                    condense_fn = getattr(model, "condense_conversation", None)
                    if condense_fn:
                        condense_fn(conversation)

            if on_step:
                try:
                    on_step(
                        {
                            "depth": depth,
                            "step": step,
                            "objective": objective,
                            "action": {"name": "_model_turn"},
                            "observation": "",
                            "model_text": turn.text or "",
                            "tool_call_names": [tc.name for tc in turn.tool_calls],
                            "input_tokens": turn.input_tokens,
                            "output_tokens": turn.output_tokens,
                            "elapsed_sec": round(elapsed, 2),
                            "is_final": False,
                            "phase": "model",
                        }
                    )
                except Exception:
                    pass

            # No tool calls + text present = final answer
            if not turn.tool_calls and turn.text:
                if self._is_meta_final_text(turn.text, objective):
                    loop_metrics["final_rejections"] += 1
                    self._emit(
                        f"[d{depth}/s{step}] rejected meta final-answer text; requesting concrete completion",
                        on_event,
                    )
                    rejection_result = ToolResult(
                        tool_call_id="meta-final-reject",
                        name="system",
                        content=(
                            "Final-answer candidate rejected: response is meta/process text. "
                            "Provide a concrete completion summary (what was produced/changed) "
                            "instead of describing what you will do next."
                        ),
                    )
                    model.append_tool_results(conversation, [rejection_result])
                    continue
                loop_metrics["phase_counts"]["finalize"] += 1
                loop_metrics["termination_reason"] = "success"
                preview = turn.text[:200] + "..." if len(turn.text) > 200 else turn.text
                self._emit(
                    f"[d{depth}/s{step}] final answer ({len(turn.text)} chars, {elapsed:.1f}s): {preview}",
                    on_event,
                )
                self.last_loop_metrics = loop_metrics
                if on_step:
                    try:
                        on_step(
                            {
                                "depth": depth,
                                "step": step,
                                "objective": objective,
                                "action": {"name": "final", "arguments": {"text": turn.text}},
                                "observation": turn.text,
                                "is_final": True,
                                "phase": "finalize",
                                "loop_metrics": dict(loop_metrics),
                            }
                        )
                    except Exception:
                        pass
                return turn.text

            # No tool calls and no text = unexpected empty response
            if not turn.tool_calls:
                self._emit(f"[d{depth}/s{step}] empty model response ({elapsed:.1f}s), nudging...", on_event)
                empty_result = ToolResult(
                    tool_call_id="empty",
                    name="system",
                    content="No tool calls and no text in response. Please use a tool or provide a final answer.",
                )
                model.append_tool_results(conversation, [empty_result])
                continue

            # Log tool calls from model
            tc_names = [tc.name for tc in turn.tool_calls]
            loop_metrics["tool_calls"] += len(tc_names)
            has_recon = any(name in _RECON_TOOL_NAMES for name in tc_names)
            has_artifact = any(name in _ARTIFACT_TOOL_NAMES for name in tc_names)
            if has_recon and not has_artifact and all(name in _RECON_TOOL_NAMES for name in tc_names):
                loop_metrics["recon_streak"] += 1
                loop_metrics["phase_counts"]["investigate"] += 1
            elif has_artifact:
                loop_metrics["recon_streak"] = 0
                loop_metrics["last_guardrail_streak"] = 0
                loop_metrics["phase_counts"]["build"] += 1
            else:
                loop_metrics["recon_streak"] = 0
                loop_metrics["last_guardrail_streak"] = 0
                loop_metrics["phase_counts"]["iterate"] += 1
            loop_metrics["max_recon_streak"] = max(
                int(loop_metrics["max_recon_streak"]), int(loop_metrics["recon_streak"])
            )
            self._emit(
                f"[d{depth}/s{step}] model returned {len(turn.tool_calls)} tool call(s) ({elapsed:.1f}s): {', '.join(tc_names)}",
                on_event,
            )
            if turn.text:
                self._emit(f"[d{depth}/s{step}] model text: {turn.text[:200]}", on_event)

            # Execute all tool calls — parallel for subtask/execute, sequential for others.
            results: list[ToolResult] = []
            final_answer: str | None = None

            _PARALLEL_TOOLS = {"subtask", "execute"}

            sequential = [(i, tc) for i, tc in enumerate(turn.tool_calls) if tc.name not in _PARALLEL_TOOLS]
            parallel = [(i, tc) for i, tc in enumerate(turn.tool_calls) if tc.name in _PARALLEL_TOOLS]

            # If no factory and we have execute calls, fall back to sequential.
            if not self.model_factory and any(tc.name == "execute" for _, tc in parallel):
                sequential = list(enumerate(turn.tool_calls))
                parallel = []

            indexed_results: dict[int, tuple[ToolResult, bool]] = {}

            for idx, tc in sequential:
                result_entry, is_final_entry = self._run_one_tool(
                    tc=tc, depth=depth, step=step, objective=objective,
                    context=context, on_event=on_event, on_step=on_step,
                    deadline=deadline, current_model=model,
                    replay_logger=replay_logger,
                )
                indexed_results[idx] = (result_entry, is_final_entry)
                if is_final_entry:
                    final_answer = result_entry.content
                    break

            if parallel and final_answer is None:
                group_id = f"d{depth}-s{step}-{time.monotonic_ns()}"
                use_parallel_owner = len(parallel) > 1
                begin_group = getattr(self.tools, "begin_parallel_write_group", None)
                end_group = getattr(self.tools, "end_parallel_write_group", None)
                if callable(begin_group):
                    begin_group(group_id)
                try:
                    with ThreadPoolExecutor(max_workers=len(parallel)) as pool:
                        futures = {
                            pool.submit(
                                self._run_one_tool,
                                tc=tc, depth=depth, step=step, objective=objective,
                                context=context, on_event=on_event, on_step=on_step,
                                deadline=deadline, current_model=model,
                                replay_logger=replay_logger,
                                parallel_group_id=group_id,
                                parallel_owner=(f"{tc.id or 'tc'}:{idx}" if use_parallel_owner else None),
                            ): idx
                            for idx, tc in parallel
                        }
                        for future in futures:
                            idx = futures[future]
                            result_entry, is_final_entry = future.result()
                            indexed_results[idx] = (result_entry, is_final_entry)
                finally:
                    if callable(end_group):
                        end_group(group_id)

            for i in sorted(indexed_results):
                r, is_final_entry = indexed_results[i]
                results.append(r)
                if is_final_entry and final_answer is None:
                    final_answer = r.content

            # Timestamp + step budget + context usage awareness
            if final_answer is None and results:
                budget_total = active_step_budget
                remaining = budget_total - step
                ts_tag = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}]"
                budget_tag = f"[Step {step}/{budget_total}]"
                _mname = getattr(model, "model", "(unknown)")
                _ctx_window = _MODEL_CONTEXT_WINDOWS.get(_mname, _DEFAULT_CONTEXT_WINDOW)
                ctx_tag = f"[Context {turn.input_tokens}/{_ctx_window} tokens]"
                r0 = results[0]
                results[0] = ToolResult(
                    r0.tool_call_id, r0.name,
                    f"{ts_tag} {budget_tag} {ctx_tag} {r0.content}", r0.is_error,
                    image=r0.image,
                )
                if 0 < remaining <= budget_total // 4:
                    warning = (
                        f"\n\n** BUDGET CRITICAL: {remaining} of {budget_total} steps remain. "
                        "Stop exploring/surveying. Write your output files NOW with your best answer. "
                        "A partial result beats no result."
                    )
                    rl = results[-1]
                    results[-1] = ToolResult(
                        rl.tool_call_id, rl.name,
                        rl.content + warning, rl.is_error,
                        image=rl.image,
                    )
                elif remaining <= budget_total // 2:
                    warning = (
                        f"\n\n** BUDGET WARNING: {remaining} of {budget_total} steps remain. "
                        "Focus on completing the task directly. Do not write exploration scripts."
                    )
                    rl = results[-1]
                    results[-1] = ToolResult(
                        rl.tool_call_id, rl.name,
                        rl.content + warning, rl.is_error,
                        image=rl.image,
                    )

            phase_name = (
                "build"
                if has_artifact
                else "investigate"
                if has_recon and all(name in _RECON_TOOL_NAMES for name in tc_names)
                else "iterate"
            )
            step_records.append(
                _build_step_progress_record(
                    step=step,
                    phase=phase_name,
                    tool_calls=turn.tool_calls,
                    results=results,
                )
            )

            if (
                final_answer is None
                and results
                and int(loop_metrics["recon_streak"]) >= 3
                and not has_artifact
                and int(loop_metrics.get("last_guardrail_streak", 0)) == 0
            ):
                loop_metrics["guardrail_warnings"] += 1
                loop_metrics["last_guardrail_streak"] = int(loop_metrics["recon_streak"])
                soft_warning = ToolResult(
                    "recon-guardrail",
                    "system",
                    (
                        "Soft guardrail: you've spent multiple consecutive steps in read/list/search mode "
                        "without producing artifacts. Move to implementation now (edit files, run targeted "
                        "validation, and return concrete outputs)."
                    ),
                )
                results.append(soft_warning)

            # Plan injection — find newest *.plan.md in session dir, append to last result
            if self.session_dir is not None and results and final_answer is None:
                try:
                    plan_files = sorted(
                        self.session_dir.glob("*.plan.md"),
                        key=lambda p: p.stat().st_mtime,
                        reverse=True,
                    )
                    if plan_files:
                        plan_path = plan_files[0]
                        plan_text = plan_path.read_text(encoding="utf-8")
                        if plan_text.strip():
                            max_pc = self.config.max_plan_chars
                            if len(plan_text) > max_pc:
                                plan_text = plan_text[:max_pc] + "\n...[plan truncated]..."
                            plan_block = (
                                f"\n[SESSION PLAN file={plan_path.name}]\n"
                                f"{plan_text}\n[/SESSION PLAN]\n"
                            )
                            rl = results[-1]
                            results[-1] = ToolResult(
                                rl.tool_call_id, rl.name,
                                rl.content + plan_block, rl.is_error,
                                image=rl.image,
                            )
                except OSError:
                    pass

            model.append_tool_results(conversation, results)

            if final_answer is not None:
                self._emit(f"[d{depth}] completed in {step} step(s)", on_event)
                loop_metrics["termination_reason"] = "success"
                self.last_loop_metrics = loop_metrics
                return final_answer

            for r in results:
                context.add(f"[depth {depth} step {step}]\n{r.content}")

            if step >= active_step_budget:
                evaluation = _evaluate_budget_extension(
                    step_records,
                    recon_streak=int(loop_metrics.get("recon_streak", 0)),
                )
                loop_metrics["extension_eligible_checks"] = int(
                    loop_metrics.get("extension_eligible_checks", 0)
                ) + 1
                loop_metrics["last_budget_extension_eval"] = evaluation
                can_extend = (
                    self.config.budget_extension_enabled
                    and int(loop_metrics.get("extensions_granted", 0)) < self.config.budget_extension_max_blocks
                    and bool(evaluation.get("eligible"))
                )
                if can_extend:
                    loop_metrics["extensions_granted"] = int(loop_metrics.get("extensions_granted", 0)) + 1
                    active_step_budget += self.config.budget_extension_block_steps
                    extension_notice = ToolResult(
                        tool_call_id="budget-extension",
                        name="system",
                        content=(
                            "Progress-based budget extension granted. You have a small number of extra steps. "
                            "Finish the deliverable now and avoid repeating the same loop."
                        ),
                    )
                    model.append_tool_results(conversation, [extension_notice])
                    continue

                if int(loop_metrics.get("extensions_granted", 0)) >= self.config.budget_extension_max_blocks:
                    loop_metrics["extension_denials_cap"] = int(loop_metrics.get("extension_denials_cap", 0)) + 1
                    loop_metrics["termination_reason"] = "budget_cap"
                else:
                    loop_metrics["extension_denials_no_progress"] = int(
                        loop_metrics.get("extension_denials_no_progress", 0)
                    ) + 1
                    loop_metrics["termination_reason"] = "budget_no_progress"
                self.last_loop_metrics = loop_metrics
                return _render_partial_completion(objective, loop_metrics, evaluation, step_records)

        loop_metrics["termination_reason"] = "budget_cap"
        self.last_loop_metrics = loop_metrics
        return _render_partial_completion(
            objective,
            loop_metrics,
            {
                "eligible": False,
                "window_size": 0,
                "repeated_signature_streak": 0,
                "failure_ratio": 0.0,
                "novel_action_count": 0,
                "state_delta_count": 0,
                "has_build_or_finalize": False,
                "positive_signals": 0,
                "blockers": ["max_total_steps"],
            },
            step_records,
        )

    def _run_one_tool(
        self,
        tc: ToolCall,
        depth: int,
        step: int,
        objective: str,
        context: ExternalContext,
        on_event: EventCallback | None,
        on_step: StepCallback | None,
        deadline: float,
        current_model: BaseModel,
        replay_logger: ReplayLogger | None,
        parallel_group_id: str | None = None,
        parallel_owner: str | None = None,
    ) -> tuple[ToolResult, bool]:
        """Run a single tool call. Returns (ToolResult, is_final)."""
        if self._cancel.is_set():
            return ToolResult(tc.id, tc.name, "Task cancelled.", is_error=False), False
        arg_summary = _summarize_args(tc.arguments)
        self._emit(f"[d{depth}/s{step}] {tc.name}({arg_summary})", on_event)

        t1 = time.monotonic()
        scope_fn = getattr(self.tools, "execution_scope", None)
        scope_cm = (
            scope_fn(parallel_group_id, parallel_owner)
            if callable(scope_fn) and parallel_group_id and parallel_owner
            else nullcontext()
        )
        with scope_cm:
            # Clear any pending image data from a previous call.
            self._pending_image.data = None
            try:
                is_final, observation = self._apply_tool_call(
                    tool_call=tc,
                    depth=depth,
                    context=context,
                    on_event=on_event,
                    on_step=on_step,
                    deadline=deadline,
                    current_model=current_model,
                    replay_logger=replay_logger,
                    step=step,
                    child_conversation_owner=parallel_owner,
                )
            except Exception as exc:
                observation = f"Tool {tc.name} crashed: {type(exc).__name__}: {exc}"
                is_final = False
        observation = self._clip_observation(observation)
        tool_elapsed = time.monotonic() - t1

        # Check for pending image data from read_image.
        image: ImageData | None = None
        pending = getattr(self._pending_image, "data", None)
        if pending is not None:
            b64, media_type = pending
            image = ImageData(base64_data=b64, media_type=media_type)
            self._pending_image.data = None

        obs_summary = _summarize_observation(observation)
        self._emit(f"[d{depth}/s{step}]   -> {obs_summary} ({tool_elapsed:.1f}s)", on_event)

        if on_step:
            try:
                on_step(
                    {
                        "depth": depth,
                        "step": step,
                        "objective": objective,
                        "action": {"name": tc.name, "arguments": tc.arguments},
                        "observation": observation,
                        "elapsed_sec": round(tool_elapsed, 2),
                        "is_final": is_final,
                    }
                )
            except Exception:
                pass

        return ToolResult(tc.id, tc.name, observation, is_error=False, image=image), is_final

    def _apply_tool_call(
        self,
        tool_call: ToolCall,
        depth: int,
        context: ExternalContext,
        on_event: EventCallback | None,
        on_step: StepCallback | None,
        deadline: float = 0,
        current_model: BaseModel | None = None,
        replay_logger: ReplayLogger | None = None,
        step: int = 0,
        child_conversation_owner: str | None = None,
    ) -> tuple[bool, str]:
        name = tool_call.name
        args = tool_call.arguments
        policy_error = self._runtime_policy_check(name=name, args=args, depth=depth)
        if policy_error:
            return False, policy_error

        if name == "think":
            note = str(args.get("note", ""))
            return False, f"Thought noted: {note}"

        if name == "list_files":
            glob = args.get("glob")
            return False, self.tools.list_files(glob=str(glob) if glob else None)

        if name == "search_files":
            query = str(args.get("query", "")).strip()
            glob = args.get("glob")
            if not query:
                return False, "search_files requires non-empty query"
            return False, self.tools.search_files(query=query, glob=str(glob) if glob else None)

        if name == "repo_map":
            glob = args.get("glob")
            raw_max_files = args.get("max_files", 200)
            max_files = raw_max_files if isinstance(raw_max_files, int) else 200
            return False, self.tools.repo_map(glob=str(glob) if glob else None, max_files=max_files)

        if name == "web_search":
            query = str(args.get("query", "")).strip()
            if not query:
                return False, "web_search requires non-empty query"
            raw_num_results = args.get("num_results", 10)
            num_results = raw_num_results if isinstance(raw_num_results, int) else 10
            raw_include_text = args.get("include_text", False)
            include_text = bool(raw_include_text) if isinstance(raw_include_text, bool) else False
            return False, self.tools.web_search(
                query=query,
                num_results=num_results,
                include_text=include_text,
            )

        if name == "fetch_url":
            urls = args.get("urls")
            if not isinstance(urls, list):
                return False, "fetch_url requires a list of URL strings"
            return False, self.tools.fetch_url([str(u) for u in urls if isinstance(u, str)])

        if name == "read_file":
            path = str(args.get("path", "")).strip()
            if not path:
                return False, "read_file requires path"
            hashline = args.get("hashline")
            hashline = hashline if hashline is not None else True
            return False, self.tools.read_file(path, hashline=hashline)

        if name == "read_image":
            path = str(args.get("path", "")).strip()
            if not path:
                return False, "read_image requires path"
            text, b64, media_type = self.tools.read_image(path)
            if b64 is not None and media_type is not None:
                self._pending_image.data = (b64, media_type)
            return False, text

        if name == "audio_transcribe":
            path = str(args.get("path", "")).strip()
            if not path:
                return False, "audio_transcribe requires path"
            diarize = args.get("diarize")
            diarize = diarize if isinstance(diarize, bool) else None
            raw_timestamps = args.get("timestamp_granularities")
            if isinstance(raw_timestamps, list):
                timestamp_granularities = [
                    str(v).strip() for v in raw_timestamps if str(v).strip()
                ]
            elif isinstance(raw_timestamps, str) and raw_timestamps.strip():
                timestamp_granularities = [raw_timestamps.strip()]
            else:
                timestamp_granularities = None
            raw_context_bias = args.get("context_bias")
            if isinstance(raw_context_bias, list):
                context_bias = [
                    str(v).strip() for v in raw_context_bias if str(v).strip()
                ]
            elif isinstance(raw_context_bias, str) and raw_context_bias.strip():
                context_bias = [
                    part.strip()
                    for part in raw_context_bias.split(",")
                    if part.strip()
                ]
            else:
                context_bias = None
            language = str(args.get("language", "")).strip() or None
            model = str(args.get("model", "")).strip() or None
            raw_temperature = args.get("temperature")
            temperature = None
            if isinstance(raw_temperature, (int, float)) and not isinstance(
                raw_temperature, bool
            ):
                temperature = float(raw_temperature)
            chunking = str(args.get("chunking", "")).strip().lower() or None
            raw_chunk_max_seconds = args.get("chunk_max_seconds")
            chunk_max_seconds = None
            if isinstance(raw_chunk_max_seconds, int) and not isinstance(
                raw_chunk_max_seconds, bool
            ):
                chunk_max_seconds = raw_chunk_max_seconds
            raw_chunk_overlap_seconds = args.get("chunk_overlap_seconds")
            chunk_overlap_seconds = None
            if isinstance(raw_chunk_overlap_seconds, (int, float)) and not isinstance(
                raw_chunk_overlap_seconds, bool
            ):
                chunk_overlap_seconds = float(raw_chunk_overlap_seconds)
            raw_max_chunks = args.get("max_chunks")
            max_chunks = None
            if isinstance(raw_max_chunks, int) and not isinstance(raw_max_chunks, bool):
                max_chunks = raw_max_chunks
            raw_continue_on_chunk_error = args.get("continue_on_chunk_error")
            continue_on_chunk_error = (
                raw_continue_on_chunk_error
                if isinstance(raw_continue_on_chunk_error, bool)
                else None
            )
            return False, self.tools.audio_transcribe(
                path=path,
                diarize=diarize,
                timestamp_granularities=timestamp_granularities,
                context_bias=context_bias,
                language=language,
                model=model,
                temperature=temperature,
                chunking=chunking,
                chunk_max_seconds=chunk_max_seconds,
                chunk_overlap_seconds=chunk_overlap_seconds,
                max_chunks=max_chunks,
                continue_on_chunk_error=continue_on_chunk_error,
            )

        if name == "write_file":
            path = str(args.get("path", "")).strip()
            if not path:
                return False, "write_file requires path"
            content = str(args.get("content", ""))
            return False, self.tools.write_file(path, content)

        if name == "apply_patch":
            patch = str(args.get("patch", ""))
            if not patch.strip():
                return False, "apply_patch requires non-empty patch"
            return False, self.tools.apply_patch(patch)

        if name == "edit_file":
            path = str(args.get("path", "")).strip()
            if not path:
                return False, "edit_file requires path"
            old_text = str(args.get("old_text", ""))
            new_text = str(args.get("new_text", ""))
            if not old_text:
                return False, "edit_file requires old_text"
            return False, self.tools.edit_file(path, old_text, new_text)

        if name == "hashline_edit":
            path = str(args.get("path", "")).strip()
            if not path:
                return False, "hashline_edit requires path"
            edits = args.get("edits")
            if not isinstance(edits, list):
                return False, "hashline_edit requires edits array"
            return False, self.tools.hashline_edit(path, edits)

        if name == "run_shell":
            command = str(args.get("command", "")).strip()
            if not command:
                return False, "run_shell requires command"
            raw_timeout = args.get("timeout")
            timeout = int(raw_timeout) if raw_timeout is not None else None
            return False, self.tools.run_shell(command, timeout=timeout)

        if name == "run_shell_bg":
            command = str(args.get("command", "")).strip()
            if not command:
                return False, "run_shell_bg requires command"
            return False, self.tools.run_shell_bg(command)

        if name == "check_shell_bg":
            raw_id = args.get("job_id")
            if raw_id is None:
                return False, "check_shell_bg requires job_id"
            return False, self.tools.check_shell_bg(int(raw_id))

        if name == "kill_shell_bg":
            raw_id = args.get("job_id")
            if raw_id is None:
                return False, "kill_shell_bg requires job_id"
            return False, self.tools.kill_shell_bg(int(raw_id))

        if name == "subtask":
            if not self.config.recursive:
                return False, "Subtask tool not available in flat mode."
            if depth >= self.config.max_depth:
                return False, "Max recursion depth reached; cannot run subtask."
            objective = str(args.get("objective", "")).strip()
            if not objective:
                return False, "subtask requires objective"
            criteria = str(args.get("acceptance_criteria", "") or "").strip()
            if self.config.acceptance_criteria and not criteria:
                return False, (
                    "subtask requires acceptance_criteria when acceptance criteria mode is enabled. "
                    "Provide specific, verifiable criteria for judging the result."
                )

            # Sub-model routing
            requested_model_name = args.get("model")
            requested_effort = args.get("reasoning_effort")
            subtask_model: BaseModel | None = None

            if (requested_model_name or requested_effort) and self.model_factory:
                cur = current_model or self.model
                cur_name = getattr(cur, "model", "")
                cur_effort = getattr(cur, "reasoning_effort", None)
                cur_tier = _model_tier(cur_name, cur_effort)

                req_name = requested_model_name or cur_name
                req_effort = requested_effort
                req_tier = _model_tier(req_name, req_effort or cur_effort)

                if req_tier < cur_tier:
                    return False, (
                        f"Cannot delegate to higher-tier model "
                        f"(current tier {cur_tier}, requested tier {req_tier}). "
                        f"Use an equal or lower-tier model."
                    )

                cache_key = (req_name, requested_effort)
                with self._lock:
                    if cache_key not in self._model_cache:
                        self._model_cache[cache_key] = self.model_factory(req_name, requested_effort)
                    subtask_model = self._model_cache[cache_key]

            self._emit(f"[d{depth}] >> entering subtask: {objective}", on_event)
            child_logger = (
                replay_logger.child(depth, step, owner=child_conversation_owner)
                if replay_logger else None
            )
            subtask_result = self._solve_recursive(
                objective=objective,
                depth=depth + 1,
                context=context,
                on_event=on_event,
                on_step=on_step,
                on_content_delta=None,
                deadline=deadline,
                model_override=subtask_model,
                replay_logger=child_logger,
            )
            observation = f"Subtask result for '{objective}':\n{subtask_result}"

            if criteria and self.config.acceptance_criteria:
                verdict = self._judge_result(objective, criteria, subtask_result, current_model)
                tag = "PASS" if verdict.startswith("PASS") else "FAIL"
                observation += f"\n\n[ACCEPTANCE CRITERIA: {tag}]\n{verdict}"

            return False, observation

        if name == "execute":
            objective = str(args.get("objective", "")).strip()
            if not objective:
                return False, "execute requires objective"
            criteria = str(args.get("acceptance_criteria", "") or "").strip()
            if self.config.acceptance_criteria and not criteria:
                return False, (
                    "execute requires acceptance_criteria when acceptance criteria mode is enabled. "
                    "Provide specific, verifiable criteria for judging the result."
                )
            if depth >= self.config.max_depth:
                return False, "Max recursion depth reached; cannot run execute."

            # Resolve lowest-tier model for the executor.
            cur = current_model or self.model
            cur_name = getattr(cur, "model", "")
            exec_name, exec_effort = _lowest_tier_model(cur_name)

            exec_model: BaseModel | None = None
            if self.model_factory:
                cache_key = (exec_name, exec_effort)
                with self._lock:
                    if cache_key not in self._model_cache:
                        self._model_cache[cache_key] = self.model_factory(exec_name, exec_effort)
                    exec_model = self._model_cache[cache_key]

            # Give executor full tools (no subtask, no execute).
            _saved_defs = None
            if exec_model and hasattr(exec_model, "tool_defs"):
                exec_model.tool_defs = get_tool_definitions(include_subtask=False, include_acceptance_criteria=self.config.acceptance_criteria)
            elif exec_model is None and hasattr(cur, "tool_defs"):
                _saved_defs = cur.tool_defs
                cur.tool_defs = get_tool_definitions(include_subtask=False, include_acceptance_criteria=self.config.acceptance_criteria)

            self._emit(f"[d{depth}] >> executing leaf: {objective}", on_event)
            child_logger = (
                replay_logger.child(depth, step, owner=child_conversation_owner)
                if replay_logger else None
            )
            exec_result = self._solve_recursive(
                objective=objective,
                depth=depth + 1,
                context=context,
                on_event=on_event,
                on_step=on_step,
                on_content_delta=None,
                deadline=deadline,
                model_override=exec_model,
                replay_logger=child_logger,
            )
            if _saved_defs is not None:
                cur.tool_defs = _saved_defs
            observation = f"Execute result for '{objective}':\n{exec_result}"

            if criteria and self.config.acceptance_criteria:
                verdict = self._judge_result(objective, criteria, exec_result, current_model)
                tag = "PASS" if verdict.startswith("PASS") else "FAIL"
                observation += f"\n\n[ACCEPTANCE CRITERIA: {tag}]\n{verdict}"

            return False, observation

        if name == "list_artifacts":
            return False, self._list_artifacts()

        if name == "read_artifact":
            aid = str(args.get("artifact_id", "")).strip()
            if not aid:
                return False, "read_artifact requires artifact_id"
            offset = int(args.get("offset", 0) or 0)
            limit = int(args.get("limit", 100) or 100)
            return False, self._read_artifact(aid, offset, limit)

        return False, f"Unknown action type: {name}"

    # ------------------------------------------------------------------
    # Artifact helpers
    # ------------------------------------------------------------------

    def _list_artifacts(self) -> str:
        """List available artifacts."""
        artifacts_dir = self.config.workspace / ".openplanter_artifacts"
        if not artifacts_dir.exists():
            return "No artifacts found."
        entries = sorted(artifacts_dir.glob("*.jsonl"))
        if not entries:
            return "No artifacts found."
        lines = []
        for p in entries:
            try:
                with open(p) as f:
                    first = json.loads(f.readline())
                lines.append(
                    f"- {first.get('artifact_id', p.stem)}: "
                    f"{first.get('objective', '(no objective)')[:120]}"
                )
            except (json.JSONDecodeError, OSError):
                lines.append(f"- {p.stem}: (unreadable)")
        return f"Artifacts ({len(lines)}):\n" + "\n".join(lines)

    def _read_artifact(self, artifact_id: str, offset: int = 0, limit: int = 100) -> str:
        """Read an artifact's conversation log."""
        artifacts_dir = self.config.workspace / ".openplanter_artifacts"
        path = artifacts_dir / f"{artifact_id}.jsonl"
        if not path.exists():
            return f"Artifact '{artifact_id}' not found."
        lines = path.read_text().splitlines()
        total = len(lines)
        selected = lines[offset:offset + limit]
        header = f"Artifact {artifact_id} (lines {offset}-{offset + len(selected)} of {total}):\n"
        return header + "\n".join(selected)

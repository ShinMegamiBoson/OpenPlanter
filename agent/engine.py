from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AgentConfig
from .model import BaseModel, ModelError, ToolCall, ToolResult
from .prompts import build_system_prompt
from .replay_log import ReplayLogger
from .tool_defs import get_tool_definitions
from .tools import WorkspaceTools

EventCallback = Callable[[str], None]
StepCallback = Callable[[dict[str, Any]], None]
ContentDeltaCallback = Callable[[str, str], None]


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
    "gemini-2.5-pro": 1_000_000,
    "gemini-2.5-flash": 1_000_000,
    "gemini-3-flash": 1_000_000,
    "gemini-2.0-flash": 1_000_000,
    "gemini-2.0-flash-lite": 1_000_000,
}
_DEFAULT_CONTEXT_WINDOW = 128_000
_CONDENSATION_THRESHOLD = 0.75


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
    if "gemini" in lower:
        if "pro" in lower:
            return 1
        if "lite" in lower:
            return 3
        return 2  # flash variants
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
    if "gemini" in lower:
        return ("gemini-2.0-flash-lite", None)
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
        self._tool_handlers: dict[str, Callable[[dict[str, Any]], tuple[bool, str]]] = self._build_tool_registry()

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
    ) -> tuple[str, ExternalContext]:
        if not objective.strip():
            return "No objective provided.", context or ExternalContext()
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
        initial_message = json.dumps(initial_msg_dict, ensure_ascii=True)

        conversation = model.create_conversation(self.system_prompt, initial_message)

        if replay_logger and replay_logger._seq == 0:
            replay_logger.write_header(
                provider=type(model).__name__,
                model=getattr(model, "model", "(unknown)"),
                base_url=getattr(model, "base_url", ""),
                system_prompt=self.system_prompt,
                tool_defs=getattr(model, "tool_defs", None) or [],
                reasoning_effort=getattr(model, "reasoning_effort", None),
                temperature=getattr(model, "temperature", None),
            )

        for step in range(1, self.config.max_steps_per_call + 1):
            if deadline and time.monotonic() > deadline:
                self._emit(f"[d{depth}] wall-clock limit reached", on_event)
                return "Time limit exceeded. Try a more focused objective."
            self._emit(f"[d{depth}/s{step}] calling model...", on_event)
            t0 = time.monotonic()
            # Stream thinking/text deltas only for top-level calls
            if on_content_delta and depth == 0 and hasattr(model, "on_content_delta"):
                model.on_content_delta = on_content_delta
            try:
                turn = model.complete(conversation)
            except ModelError as exc:
                self._emit(f"[d{depth}/s{step}] model error: {exc}", on_event)
                return f"Model error at depth {depth}, step {step}: {exc}"
            finally:
                if hasattr(model, "on_content_delta"):
                    model.on_content_delta = None
            elapsed = time.monotonic() - t0

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
                        }
                    )
                except Exception:
                    pass

            # No tool calls + text present = final answer
            if not turn.tool_calls and turn.text:
                preview = turn.text[:200] + "..." if len(turn.text) > 200 else turn.text
                self._emit(
                    f"[d{depth}/s{step}] final answer ({len(turn.text)} chars, {elapsed:.1f}s): {preview}",
                    on_event,
                )
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
            self._emit(
                f"[d{depth}/s{step}] model returned {len(turn.tool_calls)} tool call(s) ({elapsed:.1f}s): {', '.join(tc_names)}",
                on_event,
            )
            if turn.text:
                self._emit(f"[d{depth}/s{step}] model text: {turn.text[:200]}", on_event)

            # Execute all tool calls — parallel for subtask/execute, sequential for others.
            results: list[ToolResult] = []
            final_answer: str | None = None

            parallel_tools = {"subtask", "execute"}

            sequential = [(i, tc) for i, tc in enumerate(turn.tool_calls) if tc.name not in parallel_tools]
            parallel = [(i, tc) for i, tc in enumerate(turn.tool_calls) if tc.name in parallel_tools]

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
                                parallel_owner=f"{tc.id or 'tc'}:{idx}",
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
                budget_total = self.config.max_steps_per_call
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
                    )

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
                            )
                except OSError:
                    pass

            model.append_tool_results(conversation, results)

            if final_answer is not None:
                self._emit(f"[d{depth}] completed in {step} step(s)", on_event)
                return final_answer

            for r in results:
                context.add(f"[depth {depth} step {step}]\n{r.content}")

        return (
            f"Step budget exhausted at depth {depth} for objective: {objective}\n"
            "Please try with a more specific task, higher step budget, or deeper recursion."
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
                )
            except Exception as exc:
                observation = f"Tool {tc.name} crashed: {type(exc).__name__}: {exc}"
                is_final = False
        observation = self._clip_observation(observation)
        tool_elapsed = time.monotonic() - t1

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

        return ToolResult(tc.id, tc.name, observation, is_error=False), is_final

    def _build_tool_registry(self) -> dict[str, Callable[[dict[str, Any]], tuple[bool, str]]]:
        return {
            "think": self._handle_think,
            "list_files": self._handle_list_files,
            "search_files": self._handle_search_files,
            "repo_map": self._handle_repo_map,
            "web_search": self._handle_web_search,
            "fetch_url": self._handle_fetch_url,
            "read_file": self._handle_read_file,
            "write_file": self._handle_write_file,
            "apply_patch": self._handle_apply_patch,
            "edit_file": self._handle_edit_file,
            "hashline_edit": self._handle_hashline_edit,
            "run_shell": self._handle_run_shell,
            "run_shell_bg": self._handle_run_shell_bg,
            "check_shell_bg": self._handle_check_shell_bg,
            "kill_shell_bg": self._handle_kill_shell_bg,
            "list_artifacts": self._handle_list_artifacts,
            "read_artifact": self._handle_read_artifact,
        }

    def _handle_think(self, args: dict[str, Any]) -> tuple[bool, str]:
        note = str(args.get("note", ""))
        return False, f"Thought noted: {note}"

    def _handle_list_files(self, args: dict[str, Any]) -> tuple[bool, str]:
        glob = args.get("glob")
        return False, self.tools.list_files(glob=str(glob) if glob else None)

    def _handle_search_files(self, args: dict[str, Any]) -> tuple[bool, str]:
        query = str(args.get("query", "")).strip()
        glob = args.get("glob")
        if not query:
            return False, "search_files requires non-empty query"
        return False, self.tools.search_files(query=query, glob=str(glob) if glob else None)

    def _handle_repo_map(self, args: dict[str, Any]) -> tuple[bool, str]:
        glob = args.get("glob")
        raw_max_files = args.get("max_files", 200)
        max_files = raw_max_files if isinstance(raw_max_files, int) else 200
        return False, self.tools.repo_map(glob=str(glob) if glob else None, max_files=max_files)

    def _handle_web_search(self, args: dict[str, Any]) -> tuple[bool, str]:
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

    def _handle_fetch_url(self, args: dict[str, Any]) -> tuple[bool, str]:
        urls = args.get("urls")
        if not isinstance(urls, list):
            return False, "fetch_url requires a list of URL strings"
        return False, self.tools.fetch_url([str(u) for u in urls if isinstance(u, str)])

    def _handle_read_file(self, args: dict[str, Any]) -> tuple[bool, str]:
        path = str(args.get("path", "")).strip()
        if not path:
            return False, "read_file requires path"
        hashline = args.get("hashline")
        hashline = hashline if hashline is not None else True
        return False, self.tools.read_file(path, hashline=hashline)

    def _handle_write_file(self, args: dict[str, Any]) -> tuple[bool, str]:
        path = str(args.get("path", "")).strip()
        if not path:
            return False, "write_file requires path"
        content = str(args.get("content", ""))
        return False, self.tools.write_file(path, content)

    def _handle_apply_patch(self, args: dict[str, Any]) -> tuple[bool, str]:
        patch = str(args.get("patch", ""))
        if not patch.strip():
            return False, "apply_patch requires non-empty patch"
        return False, self.tools.apply_patch(patch)

    def _handle_edit_file(self, args: dict[str, Any]) -> tuple[bool, str]:
        path = str(args.get("path", "")).strip()
        if not path:
            return False, "edit_file requires path"
        old_text = str(args.get("old_text", ""))
        new_text = str(args.get("new_text", ""))
        if not old_text:
            return False, "edit_file requires old_text"
        return False, self.tools.edit_file(path, old_text, new_text)

    def _handle_hashline_edit(self, args: dict[str, Any]) -> tuple[bool, str]:
        path = str(args.get("path", "")).strip()
        if not path:
            return False, "hashline_edit requires path"
        edits = args.get("edits")
        if not isinstance(edits, list):
            return False, "hashline_edit requires edits array"
        return False, self.tools.hashline_edit(path, edits)

    def _handle_run_shell(self, args: dict[str, Any]) -> tuple[bool, str]:
        command = str(args.get("command", "")).strip()
        if not command:
            return False, "run_shell requires command"
        raw_timeout = args.get("timeout")
        timeout = int(raw_timeout) if raw_timeout is not None else None
        return False, self.tools.run_shell(command, timeout=timeout)

    def _handle_run_shell_bg(self, args: dict[str, Any]) -> tuple[bool, str]:
        command = str(args.get("command", "")).strip()
        if not command:
            return False, "run_shell_bg requires command"
        return False, self.tools.run_shell_bg(command)

    def _handle_check_shell_bg(self, args: dict[str, Any]) -> tuple[bool, str]:
        raw_id = args.get("job_id")
        if raw_id is None:
            return False, "check_shell_bg requires job_id"
        return False, self.tools.check_shell_bg(int(raw_id))

    def _handle_kill_shell_bg(self, args: dict[str, Any]) -> tuple[bool, str]:
        raw_id = args.get("job_id")
        if raw_id is None:
            return False, "kill_shell_bg requires job_id"
        return False, self.tools.kill_shell_bg(int(raw_id))

    def _handle_list_artifacts(self, args: dict[str, Any]) -> tuple[bool, str]:
        return False, self._list_artifacts()

    def _handle_read_artifact(self, args: dict[str, Any]) -> tuple[bool, str]:
        aid = str(args.get("artifact_id", "")).strip()
        if not aid:
            return False, "read_artifact requires artifact_id"
        offset = int(args.get("offset", 0) or 0)
        limit = int(args.get("limit", 100) or 100)
        return False, self._read_artifact(aid, offset, limit)

    def _apply_subtask(
        self,
        args: dict[str, Any],
        depth: int,
        context: ExternalContext,
        on_event: EventCallback | None,
        on_step: StepCallback | None,
        deadline: float,
        current_model: BaseModel | None,
        replay_logger: ReplayLogger | None,
        step: int,
    ) -> tuple[bool, str]:
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
        child_logger = replay_logger.child(depth, step) if replay_logger else None
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

    def _apply_execute(
        self,
        args: dict[str, Any],
        depth: int,
        context: ExternalContext,
        on_event: EventCallback | None,
        on_step: StepCallback | None,
        deadline: float,
        current_model: BaseModel | None,
        replay_logger: ReplayLogger | None,
        step: int,
    ) -> tuple[bool, str]:
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
        child_logger = replay_logger.child(depth, step) if replay_logger else None
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
            cur.tool_defs = _saved_defs  # type: ignore[attr-defined]
        observation = f"Execute result for '{objective}':\n{exec_result}"

        if criteria and self.config.acceptance_criteria:
            verdict = self._judge_result(objective, criteria, exec_result, current_model)
            tag = "PASS" if verdict.startswith("PASS") else "FAIL"
            observation += f"\n\n[ACCEPTANCE CRITERIA: {tag}]\n{verdict}"

        return False, observation

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
    ) -> tuple[bool, str]:
        name = tool_call.name
        args = tool_call.arguments
        policy_error = self._runtime_policy_check(name=name, args=args, depth=depth)
        if policy_error:
            return False, policy_error

        handler = self._tool_handlers.get(name)
        if handler is not None:
            return handler(args)

        if name == "subtask":
            return self._apply_subtask(args, depth, context, on_event, on_step, deadline, current_model, replay_logger, step)
        if name == "execute":
            return self._apply_execute(args, depth, context, on_event, on_step, deadline, current_model, replay_logger, step)

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

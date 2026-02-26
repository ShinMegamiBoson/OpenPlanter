"""Textual-based TUI for OpenPlanter with wiki knowledge graph panel.

Provides a widget-based layout with:
- Chat pane (message log, activity indicator, prompt input)
- Graph pane (force-directed wiki knowledge graph visualization)
- Agent execution via Worker thread with message-based bridge
"""
from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Footer, Header, Input, RichLog, Static

from .config import AgentConfig
from .engine import _DEFAULT_CONTEXT_WINDOW, _MODEL_CONTEXT_WINDOWS, RLMEngine
from .tui import (
    HELP_LINES,
    MODEL_ALIASES,
    SLASH_COMMANDS,
    SPLASH_ART,
    ChatContext,
    _StepState,
    _ToolCallRecord,
    _clip_event,
    _extract_key_arg,
    _format_session_tokens,
    _format_token_count,
    _get_model_display_name,
    _make_left_markdown,
    dispatch_slash_command,
)

_LeftMarkdown = _make_left_markdown()

# Event parsing patterns — reuse from tui.py
from .tui import (
    _EVENT_MAX_CHARS,
    _RE_CALLING,
    _RE_ERROR,
    _RE_EXECUTE,
    _RE_PREFIX,
    _RE_SUBTASK,
    _RE_TOOL_START,
    _THINKING_MAX_LINE_WIDTH,
    _THINKING_TAIL_LINES,
)


# ---------------------------------------------------------------------------
# Custom Messages
# ---------------------------------------------------------------------------

class AgentEvent(Message):
    """Trace event from the agent (calling model, subtask, error, tool start)."""

    def __init__(self, msg: str) -> None:
        self.msg = msg
        super().__init__()


class AgentStepEvent(Message):
    """Structured step completion event from the engine."""

    def __init__(self, step_event: dict[str, Any]) -> None:
        self.step_event = step_event
        super().__init__()


class AgentContentDelta(Message):
    """Streaming content delta (thinking, text, tool_args)."""

    def __init__(self, delta_type: str, text: str) -> None:
        self.delta_type = delta_type
        self.text = text
        super().__init__()


class AgentComplete(Message):
    """Agent finished — carries the final result text."""

    def __init__(self, result: str) -> None:
        self.result = result
        super().__init__()


class WikiChanged(Message):
    """Wiki files changed on disk — rebuild graph."""
    pass


# ---------------------------------------------------------------------------
# Activity Indicator Widget
# ---------------------------------------------------------------------------

class ActivityIndicator(Widget):
    """Shows thinking/streaming/tool status during agent execution."""

    DEFAULT_CSS = """
    ActivityIndicator {
        height: auto;
        max-height: 10;
        padding: 0 1;
    }
    """

    mode: reactive[str] = reactive("idle")

    def __init__(self, censor_fn: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._censor_fn = censor_fn
        self._lock = threading.Lock()
        self._text_buf: str = ""
        self._step_label: str = ""
        self._tool_name: str = ""
        self._tool_key_arg: str = ""
        self._tool_arg_buf: str = ""
        self._tool_arg_name: str = ""
        self._start_time: float = 0.0

    def start_activity(self, mode: str = "thinking", step_label: str = "") -> None:
        with self._lock:
            self._text_buf = ""
            self._step_label = step_label
            self._tool_name = ""
            self._tool_key_arg = ""
            self._tool_arg_buf = ""
            self._tool_arg_name = ""
            self._start_time = time.monotonic()
        self.mode = mode

    def stop_activity(self) -> None:
        self.mode = "idle"
        with self._lock:
            self._text_buf = ""
            self._tool_name = ""
            self._tool_key_arg = ""
            self._tool_arg_buf = ""
            self._tool_arg_name = ""

    def feed(self, delta_type: str, text: str) -> None:
        new_mode: str | None = None
        with self._lock:
            if delta_type == "tool_call_start":
                self._tool_arg_name = text
                self._tool_arg_buf = ""
                new_mode = "tool_args"
            elif delta_type == "tool_call_args":
                self._tool_arg_buf += text
            else:
                if delta_type == "text" and self.mode in ("thinking", "tool_args"):
                    self._text_buf = ""
                    new_mode = "streaming"
                if delta_type in ("thinking", "text"):
                    self._text_buf += text
        # Mode transitions outside the lock (reactive setter may trigger watchers)
        if new_mode is not None:
            self.mode = new_mode

    def set_tool(self, tool_name: str, key_arg: str = "", step_label: str = "") -> None:
        with self._lock:
            self._tool_name = tool_name
            self._tool_key_arg = key_arg
            self._text_buf = ""
            self._tool_arg_buf = ""
            self._tool_arg_name = ""
            if step_label:
                self._step_label = step_label
            self._start_time = time.monotonic()
        self.mode = "tool"

    def set_step_label(self, label: str) -> None:
        with self._lock:
            self._step_label = label

    def render(self) -> Text:
        if self.mode == "idle":
            return Text("")

        with self._lock:
            elapsed = time.monotonic() - self._start_time if self._start_time else 0.0
            mode = self.mode
            buf = self._text_buf
            step_label = self._step_label
            tool_name = self._tool_name
            tool_key_arg = self._tool_key_arg
            tool_arg_buf = self._tool_arg_buf
            tool_arg_name = self._tool_arg_name

        if self._censor_fn:
            buf = self._censor_fn(buf)

        step_part = f"  {step_label}" if step_label else ""

        if mode == "thinking":
            header = f"Thinking...  ({elapsed:.1f}s){step_part}"
            style = "bold cyan"
        elif mode == "streaming":
            header = f"Responding...  ({elapsed:.1f}s){step_part}"
            style = "bold green"
        elif mode == "tool_args":
            header = f"Generating {tool_arg_name}...  ({elapsed:.1f}s){step_part}"
            style = "bold yellow"
        else:  # tool
            header = f"Running {tool_name}...  ({elapsed:.1f}s){step_part}"
            style = "bold yellow"

        result = Text()
        result.append(header, style=style)

        if mode == "tool" and tool_key_arg:
            display = tool_key_arg[:_THINKING_MAX_LINE_WIDTH]
            result.append(f"\n  {display}", style="dim italic")
        elif mode == "tool_args" and tool_arg_buf:
            preview = _extract_tool_arg_preview(tool_arg_buf)
            lines = preview.splitlines()[-_THINKING_TAIL_LINES:]
            for ln in lines:
                if len(ln) > _THINKING_MAX_LINE_WIDTH:
                    ln = ln[:_THINKING_MAX_LINE_WIDTH - 3] + "..."
                result.append(f"\n  {ln}", style="dim italic")
        elif buf:
            lines = buf.splitlines()[-_THINKING_TAIL_LINES:]
            for ln in lines:
                if len(ln) > _THINKING_MAX_LINE_WIDTH:
                    ln = ln[:_THINKING_MAX_LINE_WIDTH - 3] + "..."
                result.append(f"\n  {ln}", style="dim italic")

        return result

    def watch_mode(self, new_mode: str) -> None:
        """Called by Textual when mode reactive changes — triggers re-render."""
        try:
            if new_mode != "idle":
                self._refresh_timer = self.set_interval(1 / 8, self._tick, name="activity_tick")
            else:
                for timer in list(self._timers):
                    if getattr(timer, "_name", "") == "activity_tick":
                        timer.stop()
        except (RuntimeError, AttributeError):
            # No running event loop (e.g. unit test outside Textual App)
            pass

    def _tick(self) -> None:
        """8fps refresh — just trigger a re-render."""
        if self.mode != "idle":
            self.refresh()


def _extract_tool_arg_preview(buf: str) -> str:
    """Extract human-readable preview from partial JSON tool args."""
    for key in ('"content": "', '"content":"', '"patch": "', '"patch":"'):
        idx = buf.find(key)
        if idx < 0:
            continue
        value_start = idx + len(key)
        raw = buf[value_start:]
        raw = raw.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"').replace("\\\\", "\\")
        if raw.endswith("\\"):
            raw = raw[:-1]
        return raw
    lines = buf.splitlines()
    return "\n".join(lines[-3:]) if lines else buf


# ---------------------------------------------------------------------------
# Wiki Graph Canvas Widget
# ---------------------------------------------------------------------------

class WikiGraphCanvas(Widget):
    """Character-cell rendering of the wiki knowledge graph."""

    DEFAULT_CSS = """
    WikiGraphCanvas {
        height: 1fr;
        min-height: 10;
    }
    """

    def __init__(self, wiki_dir: Path | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._wiki_dir = wiki_dir
        self._model: Any = None  # WikiGraphModel

    def on_mount(self) -> None:
        if self._wiki_dir is not None:
            try:
                from .wiki_graph import WikiGraphModel
                self._model = WikiGraphModel(self._wiki_dir)
                self._model.rebuild()
            except Exception:
                pass

    def rebuild(self) -> None:
        if self._model is not None:
            self._model.rebuild()
            self.refresh()

    def render(self) -> Text:
        if self._model is None:
            return Text("No wiki data", style="dim")

        width = self.size.width or 40
        height = self.size.height or 15

        try:
            buf = self._model.render_to_buffer(width, height)
        except Exception:
            return Text("Graph render error", style="bold red")

        result = Text()
        for row_idx, row in enumerate(buf):
            for ch, color in row:
                result.append(ch, style=color)
            if row_idx < len(buf) - 1:
                result.append("\n")
        return result

    @property
    def node_count(self) -> int:
        return self._model.node_count() if self._model else 0

    @property
    def edge_count(self) -> int:
        return self._model.edge_count() if self._model else 0


# ---------------------------------------------------------------------------
# OpenPlanter Textual App
# ---------------------------------------------------------------------------

class OpenPlanterApp(App):
    """Textual App for OpenPlanter with chat pane and wiki graph panel."""

    CSS = """
    #main-container {
        height: 1fr;
    }
    #chat-pane {
        width: 3fr;
        height: 1fr;
    }
    #message-log {
        height: 1fr;
        border: round $accent;
        scrollbar-size: 1 1;
    }
    #activity {
        height: auto;
        max-height: 10;
    }
    #prompt-input {
        dock: bottom;
        margin: 0 0;
    }
    #graph-pane {
        width: 1fr;
        height: 1fr;
        border: round $accent;
        padding: 0 1;
    }
    #graph-title {
        text-align: center;
        text-style: bold;
        height: 1;
    }
    #graph-legend {
        height: 1;
        text-align: center;
    }
    """

    BINDINGS = [
        ("escape", "cancel_agent", "Cancel"),
        ("ctrl+c", "quit", "Quit"),
    ]

    def __init__(
        self,
        ctx: ChatContext,
        startup_info: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.ctx = ctx
        self._startup_info = startup_info or {}
        self._current_step: _StepState | None = None
        self._agent_running = False
        self._queued_inputs: list[str] = []
        self._wiki_dir = self._resolve_wiki_dir()
        self._watcher: Any = None

        # Demo mode censor
        self._censor_fn = None
        if ctx.cfg.demo:
            from .demo import DemoCensor
            self._censor_fn = DemoCensor(ctx.cfg.workspace).censor_text

    def _resolve_wiki_dir(self) -> Path | None:
        """Find the wiki directory."""
        candidates = [
            Path(self.ctx.cfg.workspace) / ".openplanter" / "wiki",
            Path(self.ctx.cfg.workspace) / "wiki",
        ]
        for c in candidates:
            if c.is_dir():
                return c
        return None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-container"):
            with Vertical(id="chat-pane"):
                yield RichLog(id="message-log", highlight=True, markup=True, wrap=True)
                yield ActivityIndicator(censor_fn=self._censor_fn, id="activity")
                yield Input(placeholder="Type a message or /help...", id="prompt-input")
            with Vertical(id="graph-pane"):
                yield Static("Wiki Knowledge Graph", id="graph-title")
                yield WikiGraphCanvas(wiki_dir=self._wiki_dir, id="wiki-graph")
                yield Static("", id="graph-legend")
        yield Footer()

    def on_mount(self) -> None:
        """Called when the app is ready."""
        log = self.query_one("#message-log", RichLog)

        # Show splash art
        log.write(Text(SPLASH_ART, style="bold cyan"))
        log.write("")

        # Show startup info
        for key, val in self._startup_info.items():
            text = f"  {key:>10}  {val}"
            if self._censor_fn:
                text = self._censor_fn(text)
            log.write(Text(text, style="dim"))
        log.write("")
        log.write(Text("Type /help for commands. ESC to cancel a running task.", style="dim"))
        log.write("")

        # Update graph legend
        self._update_graph_legend()

        # Start wiki watcher
        if self._wiki_dir is not None:
            try:
                from .wiki_graph import WikiWatcher
                self._watcher = WikiWatcher(self._wiki_dir)
                self._watcher.start(on_change=lambda: self.call_from_thread(self.post_message, WikiChanged()))
            except Exception:
                pass

        # Focus the input
        self.query_one("#prompt-input", Input).focus()

    def on_unmount(self) -> None:
        if self._watcher is not None:
            self._watcher.stop()

    def _update_graph_legend(self) -> None:
        canvas = self.query_one("#wiki-graph", WikiGraphCanvas)
        legend = self.query_one("#graph-legend", Static)
        legend.update(f"{canvas.node_count} sources, {canvas.edge_count} links")

    # -------------------------------------------------------------------
    # Input handling
    # -------------------------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        user_input = event.value.strip()
        inp = self.query_one("#prompt-input", Input)
        inp.value = ""

        if not user_input:
            return

        log = self.query_one("#message-log", RichLog)

        # If agent is running, queue non-slash input
        if self._agent_running:
            if user_input.startswith("/"):
                result = dispatch_slash_command(
                    user_input,
                    self.ctx,
                    emit=lambda line: log.write(Text(line, style="cyan"), scroll_end=True),
                )
                if result == "quit":
                    self.ctx.runtime.engine.cancel()
                    self.exit()
                    return
                if result == "clear":
                    log.clear()
                return
            self._queued_inputs.append(user_input)
            log.write(
                Text(f"  (queued: {user_input[:60]}{'...' if len(user_input) > 60 else ''})", style="dim"),
                scroll_end=True,
            )
            return

        # Show user prompt
        log.write(Text(f"you> {user_input}", style="bold"), scroll_end=True)

        # Handle slash commands
        result = dispatch_slash_command(
            user_input,
            self.ctx,
            emit=lambda line: log.write(Text(line, style="cyan"), scroll_end=True),
        )
        if result == "quit":
            self.exit()
            return
        if result == "clear":
            log.clear()
            return
        if result == "handled":
            return

        # Regular objective — launch agent worker
        log.write("")
        self._agent_running = True
        self._current_step = None
        self._run_agent(user_input)

    # -------------------------------------------------------------------
    # Agent execution bridge
    # -------------------------------------------------------------------

    @work(thread=True)
    def _run_agent(self, objective: str) -> None:
        """Run the agent in a background worker thread."""
        try:
            result = self.ctx.runtime.solve(
                objective,
                on_event=self._bridge_event,
                on_step=self._bridge_step,
                on_content_delta=self._bridge_content_delta,
            )
        except Exception as exc:
            result = f"Agent error: {type(exc).__name__}: {exc}"

        self.call_from_thread(self.post_message, AgentComplete(result))

    def _bridge_event(self, msg: str) -> None:
        self.call_from_thread(self.post_message, AgentEvent(msg))

    def _bridge_step(self, step_event: dict[str, Any]) -> None:
        self.call_from_thread(self.post_message, AgentStepEvent(step_event))

    def _bridge_content_delta(self, delta_type: str, text: str) -> None:
        self.call_from_thread(self.post_message, AgentContentDelta(delta_type, text))

    # -------------------------------------------------------------------
    # Message handlers
    # -------------------------------------------------------------------

    def on_agent_event(self, message: AgentEvent) -> None:
        msg = message.msg
        m = _RE_PREFIX.match(msg)
        body = msg[m.end():] if m else msg

        step_label = ""
        if m:
            _s = m.group(2)
            if _s:
                step_label = f"Step {_s}/{self.ctx.cfg.max_steps_per_call}"

        activity = self.query_one("#activity", ActivityIndicator)
        log = self.query_one("#message-log", RichLog)

        if _RE_CALLING.search(body):
            self._flush_step()
            activity.start_activity(mode="thinking", step_label=step_label)
            return

        if _RE_SUBTASK.search(body) or _RE_EXECUTE.search(body):
            self._flush_step()
            activity.stop_activity()
            import re
            label = re.sub(r">> (entering subtask|executing leaf):\s*", "", body).strip()
            log.write(Text(f"--- {label} ---", style="dim"), scroll_end=True)
            return

        if _RE_ERROR.search(body):
            activity.stop_activity()
            first_line = msg.split("\n", 1)[0]
            if len(first_line) > _EVENT_MAX_CHARS:
                first_line = first_line[:_EVENT_MAX_CHARS] + "..."
            log.write(Text(first_line, style="bold red"), scroll_end=True)
            return

        tm = _RE_TOOL_START.search(body)
        if tm:
            tool_name = tm.group(1)
            tool_arg = tm.group(2) or ""
            activity.set_tool(tool_name, key_arg=tool_arg, step_label=step_label)
            return

    def on_agent_step_event(self, message: AgentStepEvent) -> None:
        step_event = message.step_event
        action = step_event.get("action")
        if not isinstance(action, dict):
            return
        name = action.get("name", "")

        activity = self.query_one("#activity", ActivityIndicator)

        if name == "_model_turn":
            activity.stop_activity()
            self._current_step = _StepState(
                depth=step_event.get("depth", 0),
                step=step_event.get("step", 0),
                max_steps=self.ctx.cfg.max_steps_per_call,
                model_text=step_event.get("model_text", ""),
                model_elapsed_sec=step_event.get("elapsed_sec", 0.0),
                input_tokens=step_event.get("input_tokens", 0),
                output_tokens=step_event.get("output_tokens", 0),
            )
            return

        if name == "final":
            self._flush_step()
            return

        if self._current_step is not None:
            key_arg = _extract_key_arg(name, action.get("arguments", {}))
            elapsed = step_event.get("elapsed_sec", 0.0)
            is_error = bool(
                step_event.get("observation", "").startswith("Tool ")
                and "crashed" in step_event.get("observation", "")
            )
            self._current_step.tool_calls.append(
                _ToolCallRecord(
                    name=name,
                    key_arg=key_arg,
                    elapsed_sec=elapsed,
                    is_error=is_error,
                )
            )

    def on_agent_content_delta(self, message: AgentContentDelta) -> None:
        activity = self.query_one("#activity", ActivityIndicator)
        activity.feed(message.delta_type, message.text)

    def on_agent_complete(self, message: AgentComplete) -> None:
        activity = self.query_one("#activity", ActivityIndicator)
        activity.stop_activity()
        self._flush_step()

        log = self.query_one("#message-log", RichLog)
        log.write("")

        # Render markdown result
        answer = message.result
        if self._censor_fn:
            answer = self._censor_fn(answer)
        log.write(_LeftMarkdown(answer), scroll_end=True)

        # Token summary
        token_str = _format_session_tokens(self.ctx.runtime.engine.session_tokens)
        if token_str:
            log.write(Text(f"  tokens: {token_str}", style="dim"), scroll_end=True)
        log.write("")

        self._agent_running = False

        # Process queued inputs
        if self._queued_inputs:
            next_input = self._queued_inputs.pop(0)
            log.write(Text(f"you> {next_input}", style="bold"), scroll_end=True)
            log.write("")
            self._agent_running = True
            self._current_step = None
            self._run_agent(next_input)

    def on_wiki_changed(self, message: WikiChanged) -> None:
        canvas = self.query_one("#wiki-graph", WikiGraphCanvas)
        canvas.rebuild()
        self._update_graph_legend()

    # -------------------------------------------------------------------
    # Step rendering
    # -------------------------------------------------------------------

    def _flush_step(self) -> None:
        step = self._current_step
        if step is None:
            return
        self._current_step = None

        log = self.query_one("#message-log", RichLog)

        ts = datetime.now().strftime("%H:%M:%S")
        model_name = getattr(self.ctx.runtime.engine.model, "model", "(unknown)")
        context_window = _MODEL_CONTEXT_WINDOWS.get(model_name, _DEFAULT_CONTEXT_WINDOW)
        ctx_str = f"{_format_token_count(step.input_tokens)}/{_format_token_count(context_window)}"

        # Step header
        left = f" {ts}  Step {step.step} "
        right_parts = []
        if step.depth > 0:
            right_parts.append(f"depth {step.depth}")
        if step.max_steps:
            right_parts.append(f"{step.step}/{step.max_steps}")
        if step.input_tokens or step.output_tokens:
            right_parts.append(
                f"{_format_token_count(step.input_tokens)}in/"
                f"{_format_token_count(step.output_tokens)}out"
            )
        right_parts.append(f"[{ctx_str}]")
        right = " | ".join(right_parts) if right_parts else ""

        header_text = Text()
        header_text.append(f"--- {left}", style="bold cyan")
        header_text.append(right, style="dim")
        header_text.append(" ---", style="bold cyan")
        log.write(header_text, scroll_end=True)

        # Model text preview
        if step.model_text:
            preview = step.model_text.strip()
            if len(preview) > 200:
                preview = preview[:197] + "..."
            if self._censor_fn:
                preview = self._censor_fn(preview)
            log.write(Text(f"  ({step.model_elapsed_sec:.1f}s) {preview}", style="dim"), scroll_end=True)

        # Tool call tree
        n = len(step.tool_calls)
        for i, tc in enumerate(step.tool_calls):
            is_last = i == n - 1
            connector = "\u2514\u2500" if is_last else "\u251c\u2500"
            name_style = "bold red" if tc.is_error else ""

            parts = Text()
            parts.append(f"  {connector} ", style="dim")
            parts.append(f"{tc.name}", style=name_style)
            if tc.key_arg:
                arg = tc.key_arg
                if self._censor_fn:
                    arg = self._censor_fn(arg)
                parts.append(f'  "{arg}"', style="dim")
            parts.append(f"  {tc.elapsed_sec:.1f}s", style="dim")
            log.write(parts, scroll_end=True)

    # -------------------------------------------------------------------
    # Actions
    # -------------------------------------------------------------------

    def action_cancel_agent(self) -> None:
        if self._agent_running:
            self.ctx.runtime.engine.cancel()
            log = self.query_one("#message-log", RichLog)
            log.write(Text("Cancelling...", style="dim"), scroll_end=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_textual_app(ctx: ChatContext, startup_info: dict[str, str] | None = None) -> None:
    """Launch the Textual TUI."""
    app = OpenPlanterApp(ctx, startup_info=startup_info)
    app.run()

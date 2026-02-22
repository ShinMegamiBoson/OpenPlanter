from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .config import AgentConfig
from .engine import RLMEngine, _MODEL_CONTEXT_WINDOWS, _DEFAULT_CONTEXT_WINDOW
from .model import EchoFallbackModel, ModelError
from .runtime import SessionRuntime
from .settings import SettingsStore


SLASH_COMMANDS: list[str] = ["/quit", "/exit", "/help", "/status", "/clear", "/model", "/reasoning"]


def _queue_prompt_style():
    """Prompt style for the secondary (queued input) prompt."""
    from prompt_toolkit.styles import Style
    return Style.from_dict({"dim": "ansibrightblack italic"})


def _make_left_markdown():
    """Create a Markdown subclass that left-aligns headings instead of centering."""
    from rich import box as _box
    from rich.markdown import Markdown as _RichMarkdown, Heading as _RichHeading
    from rich.panel import Panel as _Panel
    from rich.text import Text as _Text

    class _LeftHeading(_RichHeading):
        def __rich_console__(self, console, options):
            text = self.text
            text.justify = "left"
            if self.tag == "h1":
                yield _Panel(text, box=_box.HEAVY, style="markdown.h1.border")
            else:
                if self.tag == "h2":
                    yield _Text("")
                yield text

    class _LeftMarkdown(_RichMarkdown):
        elements = {**_RichMarkdown.elements, "heading_open": _LeftHeading}

    return _LeftMarkdown


_LeftMarkdown = _make_left_markdown()

_PLANT_LEFT = [
    " .oOo.  ",
    "oO.|.Oo ",
    "Oo.|.oO ",
    "  .|.   ",
    "[=====] ",
    " \\___/  ",
]

_PLANT_RIGHT = [
    "  .oOo. ",
    " oO.|.Oo",
    " Oo.|.oO",
    "   .|.  ",
    " [=====]",
    "  \\___/ ",
]


def _build_splash() -> str:
    """Generate the startup ASCII art banner with potted plants."""
    try:
        import pyfiglet
        art = pyfiglet.figlet_format("OpenPlanter", font="standard").rstrip()
    except Exception:
        art = "   OpenPlanter"
    lines = art.splitlines()
    # Strip common leading whitespace so the plants align flush
    min_indent = min((len(l) - len(l.lstrip()) for l in lines if l.strip()), default=0)
    stripped = [l[min_indent:] for l in lines]
    max_w = max(len(l) for l in stripped)
    padded = [l.ljust(max_w) for l in stripped]

    # Pad plant art to match the number of text lines (bottom-align plants)
    n = len(padded)
    pw_l = max(len(l) for l in _PLANT_LEFT)
    pw_r = max(len(l) for l in _PLANT_RIGHT)
    left = [" " * pw_l] * (n - len(_PLANT_LEFT)) + _PLANT_LEFT if n > len(_PLANT_LEFT) else _PLANT_LEFT[-n:]
    right = [" " * pw_r] * (n - len(_PLANT_RIGHT)) + _PLANT_RIGHT if n > len(_PLANT_RIGHT) else _PLANT_RIGHT[-n:]

    framed = "\n".join(f"{left[i]}  {padded[i]}  {right[i]}" for i in range(n))
    return framed


SPLASH_ART = _build_splash()

# Short aliases for common models.  Keys are lowered before lookup.
HELP_LINES: list[str] = [
    "Commands:",
    "  /model              Show current model, provider, aliases",
    "  /model <name>       Switch model (e.g. /model opus, /model gpt5)",
    "  /model <name> --save  Switch and persist as default",
    "  /model list [all]   List available models",
    "  /reasoning [low|medium|high|off]  Change reasoning effort",
    "  /status  /clear  /quit  /exit  /help",
]

MODEL_ALIASES: dict[str, str] = {
    "opus": "claude-opus-4-6",
    "opus4.6": "claude-opus-4-6",
    "sonnet": "claude-sonnet-4-5-20250929",
    "sonnet4.5": "claude-sonnet-4-5-20250929",
    "haiku": "claude-haiku-4-5-20251001",
    "haiku4.5": "claude-haiku-4-5-20251001",
    "gpt5": "gpt-5.2",
    "gpt5.2": "gpt-5.2",
    "gpt4": "gpt-4.1",
    "gpt4.1": "gpt-4.1",
    "gpt4o": "gpt-4o",
    "o4": "o4-mini",
    "o4-mini": "o4-mini",
    "o3": "o3-mini",
    "o3-mini": "o3-mini",
    "cerebras": "qwen-3-235b-a22b-instruct-2507",
    "qwen235b": "qwen-3-235b-a22b-instruct-2507",
    "oss120b": "gpt-oss-120b",
    "llama": "llama3.2",
    "llama3": "llama3.2",
    "mistral": "mistral",
}


@dataclass
class ChatContext:
    runtime: SessionRuntime
    cfg: AgentConfig
    settings_store: SettingsStore


def _format_token_count(n: int) -> str:
    """Format a token count for display: 1234 -> '1.2k', 15678 -> '15.7k'."""
    if n < 1000:
        return str(n)
    if n < 10000:
        return f"{n / 1000:.1f}k"
    if n < 1000000:
        return f"{n / 1000:.0f}k"
    return f"{n / 1000000:.1f}M"


def _format_session_tokens(session_tokens: dict[str, dict[str, int]]) -> str:
    """Build a compact token summary string from engine.session_tokens."""
    total_in = sum(v["input"] for v in session_tokens.values())
    total_out = sum(v["output"] for v in session_tokens.values())
    if total_in == 0 and total_out == 0:
        return ""
    return f"{_format_token_count(total_in)} in / {_format_token_count(total_out)} out"


def _get_model_display_name(engine: RLMEngine) -> str:
    """Extract a human-readable model name from the engine's model object."""
    model = engine.model
    if isinstance(model, EchoFallbackModel):
        return "(no model)"
    return getattr(model, "model", "(unknown)")


def _api_key_for_provider(cfg: AgentConfig, provider: str) -> str | None:
    """Return the configured API key for *provider*, or ``None``."""
    return {
        "openai": cfg.openai_api_key,
        "anthropic": cfg.anthropic_api_key,
        "openrouter": cfg.openrouter_api_key,
        "cerebras": cfg.cerebras_api_key,
        "ollama": "ollama",
    }.get(provider)


def _available_providers(cfg: AgentConfig) -> list[str]:
    """Return provider names that have an API key configured."""
    providers: list[str] = []
    if cfg.openai_api_key:
        providers.append("openai")
    if cfg.anthropic_api_key:
        providers.append("anthropic")
    if cfg.openrouter_api_key:
        providers.append("openrouter")
    if cfg.cerebras_api_key:
        providers.append("cerebras")
    providers.append("ollama")
    return providers


def handle_model_command(args: str, ctx: ChatContext) -> list[str]:
    """Handle /model sub-commands. Returns display lines."""
    from .builder import (
        _fetch_models_for_provider,
        build_engine,
        infer_provider_for_model,
    )

    parts = args.strip().split()

    if not parts:
        model_name = _get_model_display_name(ctx.runtime.engine)
        effort = ctx.cfg.reasoning_effort or "(off)"
        avail = ", ".join(_available_providers(ctx.cfg)) or "none"
        return [
            f"Provider: {ctx.cfg.provider} | Model: {model_name} | Reasoning: {effort}",
            f"Configured providers: {avail}",
            f"Aliases: {', '.join(sorted(MODEL_ALIASES.keys()))}",
        ]

    # /model list [all|<provider>]
    if parts[0] == "list":
        list_target = parts[1] if len(parts) > 1 else None
        if list_target == "all":
            providers = _available_providers(ctx.cfg)
        elif list_target in {"openai", "anthropic", "openrouter", "cerebras", "ollama"}:
            providers = [list_target]
        else:
            providers = [ctx.cfg.provider]

        lines: list[str] = []
        for provider in providers:
            try:
                models = _fetch_models_for_provider(ctx.cfg, provider)
            except ModelError as exc:
                lines.append(f"{provider}: skipped ({exc})")
                continue
            lines.append(f"{provider}: {len(models)} models")
            for row in models[:15]:
                lines.append(f"  {row['id']}")
            if len(models) > 15:
                lines.append(f"  ...and {len(models) - 15} more")
        return lines

    # Switch model — resolve aliases first.
    raw_model = parts[0]
    new_model = MODEL_ALIASES.get(raw_model.lower(), raw_model)
    save = "--save" in parts

    # Auto-switch provider when the model name implies a different one.
    inferred = infer_provider_for_model(new_model)
    provider_switched = False
    if inferred and inferred != ctx.cfg.provider and ctx.cfg.provider != "openrouter":
        key = _api_key_for_provider(ctx.cfg, inferred)
        if not key:
            return [
                f"Model '{new_model}' requires provider '{inferred}', "
                f"but no API key is configured for it."
            ]
        ctx.cfg.provider = inferred
        provider_switched = True

    ctx.cfg.model = new_model
    try:
        new_engine = build_engine(ctx.cfg)
    except ModelError as exc:
        return [f"Failed to switch model: {exc}"]
    ctx.runtime.engine = new_engine

    alias_note = f" (alias: {raw_model})" if raw_model.lower() in MODEL_ALIASES else ""
    lines = [f"Switched to model: {new_model}{alias_note}"]
    if provider_switched:
        lines.append(f"Provider auto-switched to: {ctx.cfg.provider}")

    if save:
        settings = ctx.settings_store.load()
        provider = ctx.cfg.provider
        if provider == "openai":
            settings.default_model_openai = new_model
        elif provider == "anthropic":
            settings.default_model_anthropic = new_model
        elif provider == "openrouter":
            settings.default_model_openrouter = new_model
        elif provider == "cerebras":
            settings.default_model_cerebras = new_model
        elif provider == "ollama":
            settings.default_model_ollama = new_model
        else:
            settings.default_model = new_model
        ctx.settings_store.save(settings)
        lines.append("Saved as workspace default.")

    return lines


def handle_reasoning_command(args: str, ctx: ChatContext) -> list[str]:
    """Handle /reasoning sub-commands. Returns display lines."""
    from .builder import build_engine

    parts = args.strip().split()
    if not parts:
        effort = ctx.cfg.reasoning_effort or "(off)"
        return [
            f"Current reasoning effort: {effort}",
            "Usage: /reasoning <low|medium|high|off> [--save]",
        ]

    value = parts[0].lower()
    save = "--save" in parts

    if value in {"off", "none", "disable", "disabled"}:
        ctx.cfg.reasoning_effort = None
    elif value in {"low", "medium", "high"}:
        ctx.cfg.reasoning_effort = value
    else:
        return [f"Invalid effort '{value}'. Use: low, medium, high, off"]

    # Rebuild engine with new reasoning effort.
    try:
        new_engine = build_engine(ctx.cfg)
    except ModelError as exc:
        return [f"Failed to apply reasoning change: {exc}"]
    ctx.runtime.engine = new_engine

    display = ctx.cfg.reasoning_effort or "off"
    lines = [f"Reasoning effort set to: {display}"]

    if save:
        settings = ctx.settings_store.load()
        settings.default_reasoning_effort = ctx.cfg.reasoning_effort
        ctx.settings_store.save(settings)
        lines.append("Saved as workspace default.")

    return lines


def _compute_suggestions(buf: str) -> tuple[list[str], int]:
    """Return (matching_commands, selected_index) for the current input buffer.

    Activates only when *buf* starts with ``/`` and contains no spaces.
    ``selected_index`` starts at -1 (nothing highlighted).
    """
    if not buf.startswith("/") or " " in buf:
        return [], -1
    matches = [cmd for cmd in SLASH_COMMANDS if cmd.startswith(buf)]
    return matches, -1


def _get_mode_label(cfg: AgentConfig) -> str:
    """Return a short mode label for the current config."""
    if cfg.recursive:
        return "recursive"
    return "flat"


def dispatch_slash_command(
    command: str,
    ctx: ChatContext,
    emit: Callable[[str], None],
) -> str | None:
    """Dispatch a slash command. Returns "quit", "clear", "handled", or None (not a command)."""
    if command in {"/quit", "/exit"}:
        return "quit"
    if command == "/help":
        for ln in HELP_LINES:
            emit(ln)
        return "handled"
    if command == "/status":
        model_name = _get_model_display_name(ctx.runtime.engine)
        effort = ctx.cfg.reasoning_effort or "(off)"
        mode = _get_mode_label(ctx.cfg)
        emit(f"Provider: {ctx.cfg.provider} | Model: {model_name} | Reasoning: {effort} | Mode: {mode}")
        tokens = ctx.runtime.engine.session_tokens
        if tokens:
            for mname, counts in tokens.items():
                emit(
                    f"  {mname}: "
                    f"{_format_token_count(counts['input'])} in / "
                    f"{_format_token_count(counts['output'])} out"
                )
        else:
            emit("  Tokens: (none yet)")
        return "handled"
    if command == "/clear":
        return "clear"
    if command.startswith("/model"):
        cmd_args = command[len("/model"):].strip()
        lines = handle_model_command(cmd_args, ctx)
        for line in lines:
            emit(line)
        return "handled"
    if command.startswith("/reasoning"):
        cmd_args = command[len("/reasoning"):].strip()
        lines = handle_reasoning_command(cmd_args, ctx)
        for line in lines:
            emit(line)
        return "handled"
    return None


# -- Event parsing for trace output --

# Patterns for event messages from the engine/runtime.
_RE_PREFIX = re.compile(r"^\[d(\d+)(?:/s(\d+))?\]\s*")
_RE_CALLING = re.compile(r"calling model")
_RE_SUBTASK = re.compile(r">> entering subtask")
_RE_EXECUTE = re.compile(r">> executing leaf")
_RE_ERROR = re.compile(r"model error:", re.IGNORECASE)
_RE_TOOL_START = re.compile(r"(\w+)\((.*)?\)$")

# Max characters to display per trace event line (first line only for multi-line).
_EVENT_MAX_CHARS = 300


def _clip_event(text: str) -> str:
    """Clip a trace event body to a reasonable display length."""
    first_line, _, rest = text.partition("\n")
    if len(first_line) > _EVENT_MAX_CHARS:
        return first_line[:_EVENT_MAX_CHARS] + "..."
    if rest:
        extra_lines = rest.count("\n") + 1
        return first_line + f"  (+{extra_lines} lines)"
    return first_line


# Map tool names to their most informative argument for compact display.
_KEY_ARGS: dict[str, str] = {
    "read_file": "path",
    "read_image": "path",
    "write_file": "path",
    "edit_file": "path",
    "hashline_edit": "path",
    "apply_patch": "patch",
    "run_shell": "command",
    "run_shell_bg": "command",
    "web_search": "query",
    "fetch_url": "urls",
    "search_files": "query",
    "list_files": "glob",
    "repo_map": "glob",
    "subtask": "objective",
    "execute": "objective",
    "think": "note",
    "check_shell_bg": "job_id",
    "kill_shell_bg": "job_id",
}

# How many lines of thinking text to show during the spinner.
_THINKING_TAIL_LINES = 6
_THINKING_MAX_LINE_WIDTH = 80


@dataclass
class _ToolCallRecord:
    name: str
    key_arg: str
    elapsed_sec: float
    is_error: bool = False


@dataclass
class _StepState:
    depth: int = 0
    step: int = 0
    max_steps: int = 0
    model_text: str = ""
    model_elapsed_sec: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: list[_ToolCallRecord] = field(default_factory=list)


def _extract_key_arg(name: str, arguments: dict[str, Any]) -> str:
    """Extract the most informative argument value for compact display."""
    key = _KEY_ARGS.get(name)
    if not key:
        # Fallback: first string-valued argument
        for v in arguments.values():
            if isinstance(v, str) and v.strip():
                s = v.strip()
                if len(s) > 60:
                    s = s[:57] + "..."
                return s
        return ""
    val = arguments.get(key, "")
    if isinstance(val, list):
        val = ", ".join(str(x) for x in val[:3])
    s = str(val).strip()
    if len(s) > 60:
        s = s[:57] + "..."
    return s


class _ActivityDisplay:
    """Unified live display for thinking, streaming response, and tool execution.

    Modes:
      - ``thinking``  — cyan header with streaming thinking text
      - ``streaming`` — green header with streaming response text
      - ``tool``      — yellow header with tool name and key argument
    """

    def __init__(self, console: Any, censor_fn: Callable[[str], str] | None = None) -> None:
        self._console = console
        self._censor_fn = censor_fn
        self._lock = threading.Lock()
        self._text_buf: str = ""
        self._mode: str = "thinking"  # thinking | streaming | tool
        self._step_label: str = ""
        self._tool_name: str = ""
        self._tool_key_arg: str = ""
        self._start_time: float = 0.0
        self._live: Any | None = None
        self._active = False

    # -- Rich renderable protocol --------------------------------------------

    def __rich__(self) -> "Any":
        """Let Rich's Live auto-refresh poll current state instead of pushing updates."""
        return self._build_renderable()

    # -- lifecycle -----------------------------------------------------------

    def start(self, mode: str = "thinking", step_label: str = "") -> None:
        from rich.live import Live

        with self._lock:
            self._mode = mode
            self._step_label = step_label
            self._text_buf = ""
            self._tool_name = ""
            self._tool_key_arg = ""
            self._start_time = time.monotonic()

        if self._active and self._live is not None:
            # Reuse existing Live — state updated above, auto-refresh picks it up.
            return

        self._active = True
        self._live = Live(
            self,
            console=self._console,
            transient=True,
            refresh_per_second=8,
        )
        self._live.__enter__()

    def stop(self) -> None:
        if not self._active:
            return
        self._active = False
        if self._live is not None:
            try:
                self._live.__exit__(None, None, None)
            except Exception:
                pass
            self._live = None
        with self._lock:
            self._text_buf = ""
            self._tool_name = ""
            self._tool_key_arg = ""

    # -- data feeds ----------------------------------------------------------

    def feed(self, delta_type: str, text: str) -> None:
        """Handle thinking or text content deltas.

        Only updates internal state — the Live auto-refresh renders at 8fps.
        """
        if not self._active:
            return
        with self._lock:
            if delta_type == "text" and self._mode == "thinking":
                # Auto-transition from thinking to streaming on first text delta
                self._mode = "streaming"
                self._text_buf = ""
            if delta_type in ("thinking", "text"):
                self._text_buf += text

    def set_tool(self, tool_name: str, key_arg: str = "", step_label: str = "") -> None:
        """Switch to tool mode.

        Only updates internal state — the Live auto-refresh renders at 8fps.
        """
        with self._lock:
            self._mode = "tool"
            self._tool_name = tool_name
            self._tool_key_arg = key_arg
            self._text_buf = ""
            if step_label:
                self._step_label = step_label
            self._start_time = time.monotonic()
        if not self._active:
            self.start(mode="tool", step_label=step_label)
            return

    def set_step_label(self, label: str) -> None:
        with self._lock:
            self._step_label = label

    # -- rendering -----------------------------------------------------------

    def _build_renderable(self) -> Any:
        from rich.text import Text

        elapsed = time.monotonic() - self._start_time if self._start_time else 0.0

        with self._lock:
            mode = self._mode
            buf = self._text_buf
            step_label = self._step_label
            tool_name = self._tool_name
            tool_key_arg = self._tool_key_arg

        if self._censor_fn:
            buf = self._censor_fn(buf)

        step_part = f"  [dim]{step_label}[/dim]" if step_label else ""

        if mode == "thinking":
            header = f"[bold cyan]Thinking...[/bold cyan]  [dim]({elapsed:.1f}s)[/dim]{step_part}"
        elif mode == "streaming":
            header = f"[bold green]Responding...[/bold green]  [dim]({elapsed:.1f}s)[/dim]{step_part}"
        else:  # tool
            header = f"[bold yellow]Running {tool_name}...[/bold yellow]  [dim]({elapsed:.1f}s)[/dim]{step_part}"

        if mode == "tool":
            if tool_key_arg:
                arg_display = tool_key_arg
                if len(arg_display) > _THINKING_MAX_LINE_WIDTH:
                    arg_display = arg_display[:_THINKING_MAX_LINE_WIDTH - 3] + "..."
                return Text.from_markup(f"\u2800 {header}\n  [dim italic]{arg_display}[/dim italic]")
            return Text.from_markup(f"\u2800 {header}")

        if not buf:
            return Text.from_markup(f"\u2800 {header}")

        # Take last N lines, truncate width
        lines = buf.splitlines()
        tail = lines[-_THINKING_TAIL_LINES:]
        clipped = []
        for ln in tail:
            if len(ln) > _THINKING_MAX_LINE_WIDTH:
                ln = ln[:_THINKING_MAX_LINE_WIDTH - 3] + "..."
            clipped.append(ln)
        snippet = "\n".join(f"  [dim italic]{ln}[/dim italic]" for ln in clipped)
        return Text.from_markup(f"\u2800 {header}\n{snippet}")

    @property
    def active(self) -> bool:
        return self._active

    @property
    def mode(self) -> str:
        with self._lock:
            return self._mode


class RichREPL:
    def __init__(self, ctx: ChatContext, startup_info: dict[str, str] | None = None) -> None:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.completion import WordCompleter
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.key_binding import KeyBindings
        from rich.console import Console

        self.ctx = ctx
        self.console = Console()
        self._startup_info = startup_info or {}
        self._current_step: _StepState | None = None

        # Background agent thread state
        self._agent_thread: threading.Thread | None = None
        self._agent_result: str | None = None
        self._queued_input: list[str] = []

        # Demo mode: prepare render hook (installed in run() after splash art).
        censor_fn = None
        self._demo_hook = None
        if ctx.cfg.demo:
            from .demo import DemoCensor, DemoRenderHook
            censor = DemoCensor(ctx.cfg.workspace)
            censor_fn = censor.censor_text
            self._demo_hook = DemoRenderHook(censor)

        self._activity = _ActivityDisplay(self.console, censor_fn=censor_fn)

        history_dir = Path.home() / ".openplanter"
        history_dir.mkdir(parents=True, exist_ok=True)
        history_path = history_dir / "repl_history"

        completer = WordCompleter(SLASH_COMMANDS, sentence=True)

        kb = KeyBindings()

        @kb.add("escape", "enter")
        def _multiline(event: object) -> None:
            # Alt+Enter inserts a newline
            buf = getattr(event, "current_buffer", None) or getattr(event, "app", None)
            if buf is not None and hasattr(buf, "insert_text"):
                buf.insert_text("\n")
            elif hasattr(event, "current_buffer"):
                event.current_buffer.insert_text("\n")  # type: ignore[union-attr]

        @kb.add("escape")
        def _cancel_agent(event: object) -> None:
            if self._agent_thread is not None and self._agent_thread.is_alive():
                self.ctx.runtime.engine.cancel()
                self.console.print("[dim]Cancelling...[/dim]")

        self.session: PromptSession[str] = PromptSession(
            history=FileHistory(str(history_path)),
            completer=completer,
            key_bindings=kb,
            multiline=False,
        )

    # ------------------------------------------------------------------
    # on_event — simplified, only handles calling model / subtask / error
    # ------------------------------------------------------------------

    def _on_event(self, msg: str) -> None:
        """Callback for runtime.solve() trace events."""
        m = _RE_PREFIX.match(msg)
        body = msg[m.end():] if m else msg

        # Extract step label from prefix (e.g. "[d0/s3]" → "Step 3/20")
        step_label = ""
        if m:
            _s = m.group(2)
            if _s:
                step_label = f"Step {_s}/{self.ctx.cfg.max_steps_per_call}"

        # Calling model → flush previous step, start thinking display
        if _RE_CALLING.search(body):
            self._flush_step()
            self._activity.start(mode="thinking", step_label=step_label)
            return

        # Subtask/execute entry → flush step, render rule
        if _RE_SUBTASK.search(body) or _RE_EXECUTE.search(body):
            self._flush_step()
            self._activity.stop()
            label = re.sub(r">> (entering subtask|executing leaf):\s*", "", body).strip()
            self.console.rule(f"[dim]{label}[/dim]", style="dim")
            return

        # Error
        if _RE_ERROR.search(body):
            self._activity.stop()
            from rich.text import Text
            first_line = msg.split("\n", 1)[0]
            if len(first_line) > _EVENT_MAX_CHARS:
                first_line = first_line[:_EVENT_MAX_CHARS] + "..."
            self.console.print(Text(first_line, style="bold red"))
            return

        # Tool start (e.g. "read_file(path=foo.py)") → switch to tool mode
        tm = _RE_TOOL_START.search(body)
        if tm:
            tool_name = tm.group(1)
            tool_arg = tm.group(2) or ""
            self._activity.set_tool(tool_name, key_arg=tool_arg, step_label=step_label)
            return

    # ------------------------------------------------------------------
    # on_step — receives structured step events from engine
    # ------------------------------------------------------------------

    def _on_step(self, step_event: dict[str, Any]) -> None:
        action = step_event.get("action")
        if not isinstance(action, dict):
            return
        name = action.get("name", "")

        if name == "_model_turn":
            # Model turn completed → stop activity display, create new step state
            self._activity.stop()
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
            # Final answer — flush whatever we have
            self._flush_step()
            return

        # Tool call — append to current step
        if self._current_step is not None:
            key_arg = _extract_key_arg(name, action.get("arguments", {}))
            elapsed = step_event.get("elapsed_sec", 0.0)
            is_error = bool(step_event.get("observation", "").startswith("Tool ") and "crashed" in step_event.get("observation", ""))
            self._current_step.tool_calls.append(
                _ToolCallRecord(
                    name=name,
                    key_arg=key_arg,
                    elapsed_sec=elapsed,
                    is_error=is_error,
                )
            )

    # ------------------------------------------------------------------
    # on_content_delta — forward to thinking display
    # ------------------------------------------------------------------

    def _on_content_delta(self, delta_type: str, text: str) -> None:
        self._activity.feed(delta_type, text)

    # ------------------------------------------------------------------
    # _flush_step — render a completed step
    # ------------------------------------------------------------------

    def _flush_step(self) -> None:
        step = self._current_step
        if step is None:
            return
        self._current_step = None

        from rich.text import Text

        # Timestamp
        ts = datetime.now().strftime("%H:%M:%S")

        # Context usage: input_tokens is how many tokens were in context this turn
        model_name = getattr(self.ctx.runtime.engine.model, "model", "(unknown)")
        context_window = _MODEL_CONTEXT_WINDOWS.get(model_name, _DEFAULT_CONTEXT_WINDOW)
        ctx_str = f"{_format_token_count(step.input_tokens)}/{_format_token_count(context_window)}"

        # Step header rule
        left = f" {ts}  Step {step.step} "
        right_parts = []
        if step.depth > 0:
            right_parts.append(f"depth {step.depth}")
        if step.max_steps:
            right_parts.append(f"{step.step}/{step.max_steps}")
        if step.input_tokens or step.output_tokens:
            right_parts.append(
                f"{_format_token_count(step.input_tokens)}in/{_format_token_count(step.output_tokens)}out"
            )
        right_parts.append(f"[{ctx_str}]")
        right = " | ".join(right_parts) if right_parts else ""
        self.console.rule(f"[bold]{left}[/bold][dim]{right}[/dim]", style="cyan")

        # Model text (dim, truncated)
        if step.model_text:
            preview = step.model_text.strip()
            if len(preview) > 200:
                preview = preview[:197] + "..."
            self.console.print(
                Text(f"  ({step.model_elapsed_sec:.1f}s) {preview}", style="dim"),
            )

        # Tool call tree
        n = len(step.tool_calls)
        for i, tc in enumerate(step.tool_calls):
            is_last = i == n - 1
            connector = "\u2514\u2500" if is_last else "\u251c\u2500"
            name_style = "bold red" if tc.is_error else ""

            # Build line: connector + name + key_arg + elapsed
            parts = Text()
            parts.append(f"  {connector} ", style="dim")
            parts.append(f"{tc.name}", style=name_style)
            if tc.key_arg:
                parts.append(f"  \"{tc.key_arg}\"", style="dim")
            parts.append(f"  {tc.elapsed_sec:.1f}s", style="dim")
            self.console.print(parts)

    # ------------------------------------------------------------------
    # run — main REPL loop
    # ------------------------------------------------------------------

    def _run_agent(self, objective: str) -> None:
        """Run the agent in a background thread. Stores result in _agent_result."""
        try:
            self._agent_result = self.ctx.runtime.solve(
                objective,
                on_event=self._on_event,
                on_step=self._on_step,
                on_content_delta=self._on_content_delta,
            )
        except Exception as exc:
            self._agent_result = f"Agent error: {type(exc).__name__}: {exc}"

    def _present_result(self, answer: str) -> None:
        """Render an agent answer to the console."""
        from rich.text import Text

        self._activity.stop()
        self._flush_step()

        self.console.print()
        self.console.print(_LeftMarkdown(answer), justify="left")

        token_str = _format_session_tokens(self.ctx.runtime.engine.session_tokens)
        if token_str:
            self.console.print(Text(f"  tokens: {token_str}", style="dim"))
        self.console.print()

    def run(self) -> None:
        from prompt_toolkit.patch_stdout import patch_stdout
        from rich.text import Text

        self.console.clear()
        self.console.print(Text(SPLASH_ART, style="bold cyan"))

        # Install demo render hook AFTER splash art so the header is uncensored.
        if self._demo_hook is not None:
            self.console.push_render_hook(self._demo_hook)

        if self._startup_info:
            for key, val in self._startup_info.items():
                self.console.print(Text(f"  {key:>10}  {val}", style="dim"))
            self.console.print()
        self.console.print(
            "Type /help for commands, Ctrl+D to exit.  ESC to cancel a running task.",
            style="dim",
        )
        self.console.print()

        with patch_stdout():
            while True:
                # Check if there's queued input from a previous agent run
                if self._queued_input:
                    user_input = self._queued_input.pop(0)
                    self.console.print(Text(f"you> {user_input}", style="bold"))
                else:
                    try:
                        user_input = self.session.prompt("you> ").strip()
                    except KeyboardInterrupt:
                        continue
                    except EOFError:
                        break

                if not user_input:
                    continue

                result = dispatch_slash_command(
                    user_input,
                    self.ctx,
                    emit=lambda line: self.console.print(Text(line, style="cyan")),
                )
                if result == "quit":
                    break
                if result == "clear":
                    self.console.clear()
                    continue
                if result == "handled":
                    continue

                # Regular objective — run in background thread
                self.console.print()
                self._agent_result = None
                self._agent_thread = threading.Thread(
                    target=self._run_agent,
                    args=(user_input,),
                    daemon=True,
                )
                self._agent_thread.start()

                # Secondary input loop: accept input while agent works
                while self._agent_thread.is_alive():
                    try:
                        queued = self.session.prompt(
                            [("class:dim", "... ")],
                            style=_queue_prompt_style(),
                        ).strip()
                        if queued:
                            self._queued_input.append(queued)
                            self.console.print(
                                Text(f"  (queued: {queued[:60]}{'...' if len(queued) > 60 else ''})", style="dim"),
                            )
                    except KeyboardInterrupt:
                        continue
                    except EOFError:
                        # Ctrl+D during agent run — just wait for agent to finish
                        break

                self._agent_thread.join()
                self._agent_thread = None

                if self._agent_result is not None:
                    self._present_result(self._agent_result)


def run_rich_repl(ctx: ChatContext, startup_info: dict[str, str] | None = None) -> None:
    """Entry point for the Rich REPL."""
    repl = RichREPL(ctx, startup_info=startup_info)
    repl.run()

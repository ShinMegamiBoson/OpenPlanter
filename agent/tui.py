from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import AgentConfig
from .engine import RLMEngine
from .model import EchoFallbackModel, ModelError
from .runtime import SessionRuntime
from .settings import SettingsStore


SLASH_COMMANDS: list[str] = ["/quit", "/exit", "/help", "/status", "/clear", "/model", "/reasoning"]

_PLANT_LEFT = [
    "  ,  ",
    " /|\\ ",
    "(_|_)",
    " \\|/ ",
    "  |  ",
    " [_] ",
]

_PLANT_RIGHT = [
    "  ,  ",
    " /|\\ ",
    "(_|_)",
    " \\|/ ",
    "  |  ",
    " [_] ",
]


def _build_splash() -> str:
    """Generate the startup ASCII art banner with potted plants."""
    try:
        import pyfiglet
        art = pyfiglet.figlet_format("OpenPlanter", font="slant").rstrip()
    except Exception:
        art = "   OpenPlanter"
    lines = art.splitlines()
    # Strip common leading whitespace
    min_indent = min((len(l) - len(l.lstrip()) for l in lines if l.strip()), default=0)
    stripped = [l[min_indent:] for l in lines]
    max_w = max(len(l) for l in stripped)
    padded = [l.ljust(max_w) for l in stripped]

    # Pad plant art to match the number of text lines (top-align text, bottom-align plants)
    n = len(padded)
    pw = max(len(l) for l in _PLANT_LEFT)
    left = [" " * pw] * (n - len(_PLANT_LEFT)) + _PLANT_LEFT if n > len(_PLANT_LEFT) else _PLANT_LEFT[-n:]
    right = [" " * pw] * (n - len(_PLANT_RIGHT)) + _PLANT_RIGHT if n > len(_PLANT_RIGHT) else _PLANT_RIGHT[-n:]

    framed = "\n".join(f"  {left[i]}  {padded[i]}  {right[i]}" for i in range(n))
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
        elif list_target in {"openai", "anthropic", "openrouter", "cerebras"}:
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
_RE_RESULT = re.compile(r"^\s*->\s*")
_RE_ERROR = re.compile(r"model error:", re.IGNORECASE)

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


class RichREPL:
    def __init__(self, ctx: ChatContext, startup_info: dict[str, str] | None = None) -> None:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.completion import WordCompleter
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.key_binding import KeyBindings
        from rich.console import Console

        self.ctx = ctx
        self.console = Console()
        self._spinner_active = False
        self._startup_info = startup_info or {}

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

        self.session: PromptSession[str] = PromptSession(
            history=FileHistory(str(history_path)),
            completer=completer,
            key_bindings=kb,
            multiline=False,
        )

    def _on_event(self, msg: str) -> None:
        """Callback for runtime.solve() trace events."""
        from rich.text import Text

        # Strip the [dN/sN] prefix for display, but extract depth/step.
        m = _RE_PREFIX.match(msg)
        if m:
            prefix_tag = msg[: m.end()].strip()
            body = msg[m.end() :]
        else:
            prefix_tag = ""
            body = msg

        # Calling model → start spinner
        if _RE_CALLING.search(body):
            if not self._spinner_active:
                self._spinner_active = True
                self._status_ctx = self.console.status("Thinking...", spinner="dots")
                self._status_ctx.__enter__()
            return

        # Any non-model-call event stops the spinner.
        self._stop_spinner()

        # Subtask entry → horizontal rule
        if _RE_SUBTASK.search(body):
            self.console.rule(body.replace(">> entering subtask:", "").strip(), style="dim")
            return

        # Error
        if _RE_ERROR.search(body):
            self.console.print(Text(_clip_event(msg), style="bold red"))
            return

        # Tool result line (-> summary)
        if _RE_RESULT.match(body):
            self.console.print(Text(f"         {_clip_event(body.strip())}", style="dim"))
            return

        # Tool call line
        if prefix_tag:
            self.console.print(Text(f"  {prefix_tag}  {_clip_event(body)}", style=""))
            return

        # Fallback
        self.console.print(Text(_clip_event(msg), style="dim"))

    def _stop_spinner(self) -> None:
        if self._spinner_active:
            self._spinner_active = False
            try:
                self._status_ctx.__exit__(None, None, None)
            except Exception:
                pass

    def run(self) -> None:
        from rich.markdown import Markdown
        from rich.text import Text

        self.console.print(Text(SPLASH_ART, style="bold cyan"))
        if self._startup_info:
            for key, val in self._startup_info.items():
                self.console.print(Text(f"  {key:>10}  {val}", style="dim"))
            self.console.print()
        self.console.print("Type /help for commands, Ctrl+D to exit.", style="dim")
        self.console.print()

        while True:
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

            # Regular objective
            self.console.print()
            answer = self.ctx.runtime.solve(user_input, on_event=self._on_event)
            self._stop_spinner()

            self.console.print()
            self.console.print(Markdown(answer))

            # Token usage
            token_str = _format_session_tokens(self.ctx.runtime.engine.session_tokens)
            if token_str:
                self.console.print(Text(f"  tokens: {token_str}", style="dim"))
            self.console.print()


def run_rich_repl(ctx: ChatContext, startup_info: dict[str, str] | None = None) -> None:
    """Entry point for the Rich REPL."""
    repl = RichREPL(ctx, startup_info=startup_info)
    repl.run()

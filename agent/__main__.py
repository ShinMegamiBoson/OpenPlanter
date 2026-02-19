from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

from .builder import _fetch_models_for_provider, build_engine, infer_provider_for_model
from .config import AgentConfig
from .credentials import (
    CredentialBundle,
    CredentialStore,
    UserCredentialStore,
    credentials_from_env,
    discover_env_candidates,
    parse_env_file,
    prompt_for_credentials,
)
from .model import ModelError
from .runtime import SessionError, SessionRuntime, SessionStore
from .settings import PersistentSettings, SettingsStore, normalize_reasoning_effort
from .tui import ChatContext, _clip_event, _get_model_display_name, dispatch_slash_command, run_rich_repl

VALID_REASONING_FLAGS = ["low", "medium", "high", "none"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openplanter-agent",
        description="OpenPlanter coding agent with terminal UI.",
    )
    parser.add_argument("--workspace", default=".", help="Workspace root directory.")
    parser.add_argument(
        "--provider",
        default=None,
        choices=["auto", "openai", "anthropic", "openrouter", "cerebras", "all"],
        help="Model provider. Use 'all' only with --list-models.",
    )
    parser.add_argument("--model", help="Model name (use 'newest' to auto-select latest from API).")
    parser.add_argument(
        "--reasoning-effort",
        choices=VALID_REASONING_FLAGS,
        help="Per-run reasoning effort override.",
    )
    parser.add_argument(
        "--default-model",
        help="Persist workspace default model in .openplanter/settings.json.",
    )
    parser.add_argument(
        "--default-reasoning-effort",
        choices=VALID_REASONING_FLAGS,
        help="Persist workspace default reasoning effort.",
    )
    parser.add_argument(
        "--default-model-openai",
        help="Persist workspace default model for OpenAI provider.",
    )
    parser.add_argument(
        "--default-model-anthropic",
        help="Persist workspace default model for Anthropic provider.",
    )
    parser.add_argument(
        "--default-model-openrouter",
        help="Persist workspace default model for OpenRouter provider.",
    )
    parser.add_argument(
        "--default-model-cerebras",
        help="Persist workspace default model for Cerebras provider.",
    )
    parser.add_argument(
        "--show-settings",
        action="store_true",
        help="Show persistent workspace defaults and exit (unless task/list action is also provided).",
    )
    parser.add_argument("--base-url", help="Provider base URL override for this run.")
    parser.add_argument("--api-key", help="Legacy API key alias (maps to OpenAI).")
    parser.add_argument("--openai-api-key", help="OpenAI API key override.")
    parser.add_argument("--anthropic-api-key", help="Anthropic API key override.")
    parser.add_argument("--openrouter-api-key", help="OpenRouter API key override.")
    parser.add_argument("--cerebras-api-key", help="Cerebras API key override.")
    parser.add_argument("--exa-api-key", help="Exa API key override.")
    parser.add_argument("--voyage-api-key", help="Voyage API key override.")
    parser.add_argument(
        "--configure-keys",
        action="store_true",
        help="Prompt to set/update provider API keys and persist them locally.",
    )
    parser.add_argument("--max-depth", type=int, help="Maximum recursion depth.")
    parser.add_argument("--max-steps", type=int, help="Maximum steps per recursive call.")
    parser.add_argument("--timeout", type=int, help="Shell command timeout seconds.")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Disable interactive UI/prompts; intended for CI/non-TTY execution.",
    )
    parser.add_argument(
        "--no-tui",
        action="store_true",
        help="Use plain REPL instead of Rich REPL (no colors, no spinner).",
    )
    parser.add_argument("--task", help="Single objective to run and exit.")
    parser.add_argument(
        "--session-id",
        help="Session id to use. If omitted, a new id is generated unless --resume is used.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume an existing session (with --session-id or latest session).",
    )
    parser.add_argument(
        "--list-sessions",
        action="store_true",
        help="List known sessions in .openplanter and exit.",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="Fetch and list available provider models from newest to oldest via API.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Enable recursive mode with subtask delegation (default: flat agent).",
    )
    parser.add_argument(
        "--acceptance-criteria",
        action="store_true",
        help="Enable acceptance criteria: subtask/execute results are judged by a lightweight model.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Censor entity names and workspace path segments in output (UI-only).",
    )
    return parser


def _format_ts(ts: int) -> str:
    if ts <= 0:
        return "unknown"
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _resolve_provider(requested: str, creds: CredentialBundle) -> str:
    requested = requested.strip().lower()
    if requested in {"openai", "anthropic", "openrouter", "cerebras"}:
        return requested
    if requested == "all":
        return "all"
    if creds.openai_api_key:
        return "openai"
    if creds.anthropic_api_key:
        return "anthropic"
    if creds.openrouter_api_key:
        return "openrouter"
    if creds.cerebras_api_key:
        return "cerebras"
    return "openai"


def _print_models(cfg: AgentConfig, requested_provider: str) -> int:
    providers: list[str]
    if requested_provider == "all":
        providers = ["openai", "anthropic", "openrouter", "cerebras"]
    elif requested_provider == "auto":
        providers = ["openai", "anthropic", "openrouter", "cerebras"]
    else:
        providers = [requested_provider]

    printed_any = False
    for provider in providers:
        try:
            models = _fetch_models_for_provider(cfg, provider)
        except ModelError as exc:
            print(f"{provider}: skipped ({exc})")
            continue
        print(f"{provider}: {len(models)} models")
        for row in models:
            model_id = str(row.get("id", ""))
            created_ts = int(row.get("created_ts") or 0)
            print(f"  {model_id} | {_format_ts(created_ts)}")
        printed_any = True
    if not printed_any:
        print("No models could be listed. Configure at least one provider API key.")
        return 1
    return 0


def _load_credentials(
    cfg: AgentConfig,
    args: argparse.Namespace,
    allow_prompt: bool,
) -> CredentialBundle:
    user_store = UserCredentialStore()
    user_creds = user_store.load()

    creds = CredentialBundle(
        openai_api_key=user_creds.openai_api_key,
        anthropic_api_key=user_creds.anthropic_api_key,
        openrouter_api_key=user_creds.openrouter_api_key,
        cerebras_api_key=user_creds.cerebras_api_key,
        exa_api_key=user_creds.exa_api_key,
        voyage_api_key=user_creds.voyage_api_key,
    )

    store = CredentialStore(workspace=cfg.workspace, session_root_dir=cfg.session_root_dir)
    stored = store.load()
    if stored.openai_api_key:
        creds.openai_api_key = stored.openai_api_key
    if stored.anthropic_api_key:
        creds.anthropic_api_key = stored.anthropic_api_key
    if stored.openrouter_api_key:
        creds.openrouter_api_key = stored.openrouter_api_key
    if stored.cerebras_api_key:
        creds.cerebras_api_key = stored.cerebras_api_key
    if stored.exa_api_key:
        creds.exa_api_key = stored.exa_api_key
    if stored.voyage_api_key:
        creds.voyage_api_key = stored.voyage_api_key

    env_creds = credentials_from_env()
    if env_creds.openai_api_key:
        creds.openai_api_key = env_creds.openai_api_key
    if env_creds.anthropic_api_key:
        creds.anthropic_api_key = env_creds.anthropic_api_key
    if env_creds.openrouter_api_key:
        creds.openrouter_api_key = env_creds.openrouter_api_key
    if env_creds.cerebras_api_key:
        creds.cerebras_api_key = env_creds.cerebras_api_key
    if env_creds.exa_api_key:
        creds.exa_api_key = env_creds.exa_api_key
    if env_creds.voyage_api_key:
        creds.voyage_api_key = env_creds.voyage_api_key

    for env_path in discover_env_candidates(cfg.workspace):
        file_creds = parse_env_file(env_path)
        creds.merge_missing(file_creds)

    if args.api_key:
        creds.openai_api_key = args.api_key.strip() or creds.openai_api_key
    if args.openai_api_key:
        creds.openai_api_key = args.openai_api_key.strip() or creds.openai_api_key
    if args.anthropic_api_key:
        creds.anthropic_api_key = args.anthropic_api_key.strip() or creds.anthropic_api_key
    if args.openrouter_api_key:
        creds.openrouter_api_key = args.openrouter_api_key.strip() or creds.openrouter_api_key
    if args.cerebras_api_key:
        creds.cerebras_api_key = args.cerebras_api_key.strip() or creds.cerebras_api_key
    if args.exa_api_key:
        creds.exa_api_key = args.exa_api_key.strip() or creds.exa_api_key
    if args.voyage_api_key:
        creds.voyage_api_key = args.voyage_api_key.strip() or creds.voyage_api_key

    changed_by_prompt = False
    if allow_prompt:
        updated, changed_by_prompt = prompt_for_credentials(
            existing=creds,
            force=bool(args.configure_keys),
        )
        creds = updated
    elif args.configure_keys:
        print("Headless/non-interactive mode: skipping interactive key prompt.")

    if not creds.has_any():
        print(
            "No API keys are configured. "
            "Set keys with --configure-keys, env vars, or .env files."
        )

    if changed_by_prompt or (creds != user_creds):
        user_store.save(creds)
    if stored.has_any() and (creds != stored):
        store.save(creds)
    return creds


def _apply_runtime_overrides(cfg: AgentConfig, args: argparse.Namespace, creds: CredentialBundle) -> None:
    if args.max_depth is not None:
        cfg.max_depth = args.max_depth
    if args.max_steps is not None:
        cfg.max_steps_per_call = args.max_steps
    if args.timeout is not None:
        cfg.command_timeout_sec = args.timeout

    if args.provider:
        cfg.provider = args.provider
    cfg.provider = _resolve_provider(cfg.provider, creds)

    cfg.openai_api_key = creds.openai_api_key
    cfg.anthropic_api_key = creds.anthropic_api_key
    cfg.openrouter_api_key = creds.openrouter_api_key
    cfg.cerebras_api_key = creds.cerebras_api_key
    cfg.exa_api_key = creds.exa_api_key
    cfg.voyage_api_key = creds.voyage_api_key
    cfg.api_key = cfg.openai_api_key

    if args.base_url:
        if cfg.provider == "openai":
            cfg.openai_base_url = args.base_url
        elif cfg.provider == "anthropic":
            cfg.anthropic_base_url = args.base_url
        elif cfg.provider == "openrouter":
            cfg.openrouter_base_url = args.base_url
        elif cfg.provider == "cerebras":
            cfg.cerebras_base_url = args.base_url
        cfg.base_url = args.base_url

    if args.model:
        cfg.model = args.model
    if args.reasoning_effort:
        cfg.reasoning_effort = None if args.reasoning_effort == "none" else args.reasoning_effort
    if args.recursive:
        cfg.recursive = True
    if args.acceptance_criteria:
        cfg.acceptance_criteria = True
    if args.demo:
        cfg.demo = True


def run_plain_repl(ctx: ChatContext) -> None:
    from .demo import DemoCensor

    censor_fn = DemoCensor(ctx.cfg.workspace).censor_text if ctx.cfg.demo else None

    def _out(text: str) -> None:
        print(censor_fn(text) if censor_fn else text)

    _out("OpenPlanter Agent (plain mode). Type /quit to exit.")
    while True:
        try:
            objective = input("you> ").strip()
        except EOFError:
            print()
            break
        if not objective:
            continue
        result = dispatch_slash_command(
            objective,
            ctx,
            emit=lambda line: _out(f"agent> {line}"),
        )
        if result == "quit":
            break
        if result == "clear":
            continue
        if result == "handled":
            continue
        response = ctx.runtime.solve(objective, on_event=lambda ev: _out(f"trace> {_clip_event(ev)}"))
        _out(f"agent> {response}")


def _apply_persistent_settings(
    cfg: AgentConfig,
    args: argparse.Namespace,
    store: SettingsStore,
) -> PersistentSettings:
    settings = store.load()
    changed = False

    if args.default_model is not None:
        settings.default_model = args.default_model.strip() or None
        changed = True
    if args.default_reasoning_effort is not None:
        if args.default_reasoning_effort == "none":
            settings.default_reasoning_effort = None
        else:
            settings.default_reasoning_effort = normalize_reasoning_effort(args.default_reasoning_effort)
        changed = True
    if args.default_model_openai is not None:
        settings.default_model_openai = args.default_model_openai.strip() or None
        changed = True
    if args.default_model_anthropic is not None:
        settings.default_model_anthropic = args.default_model_anthropic.strip() or None
        changed = True
    if args.default_model_openrouter is not None:
        settings.default_model_openrouter = args.default_model_openrouter.strip() or None
        changed = True
    if args.default_model_cerebras is not None:
        settings.default_model_cerebras = args.default_model_cerebras.strip() or None
        changed = True

    if changed:
        store.save(settings)
        settings = settings.normalized()
        print("Saved persistent defaults to .openplanter/settings.json")

    if (
        args.model is None
        and not os.getenv("OPENPLANTER_MODEL")
        and settings.default_model
    ):
        cfg.model = settings.default_model
    if (
        args.reasoning_effort is None
        and not os.getenv("OPENPLANTER_REASONING_EFFORT")
        and settings.default_reasoning_effort
    ):
        cfg.reasoning_effort = settings.default_reasoning_effort

    return settings


def _print_settings(settings: PersistentSettings) -> None:
    print("Persistent settings:")
    print(f"  default_model: {settings.default_model or '(unset)'}")
    print(f"  default_reasoning_effort: {settings.default_reasoning_effort or '(unset)'}")
    print(f"  default_model_openai: {settings.default_model_openai or '(unset)'}")
    print(f"  default_model_anthropic: {settings.default_model_anthropic or '(unset)'}")
    print(f"  default_model_openrouter: {settings.default_model_openrouter or '(unset)'}")
    print(f"  default_model_cerebras: {settings.default_model_cerebras or '(unset)'}")


def _has_non_interactive_command(args: argparse.Namespace) -> bool:
    if args.task:
        return True
    if args.list_models:
        return True
    if args.list_sessions:
        return True
    if args.show_settings:
        return True
    if args.configure_keys:
        return True
    if args.default_model is not None:
        return True
    if args.default_reasoning_effort is not None:
        return True
    if args.default_model_openai is not None:
        return True
    if args.default_model_anthropic is not None:
        return True
    if args.default_model_openrouter is not None:
        return True
    if args.default_model_cerebras is not None:
        return True
    return False


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    non_tty = not (sys.stdin.isatty() and sys.stdout.isatty())
    if args.headless or non_tty:
        args.no_tui = True

    cfg = AgentConfig.from_env(args.workspace)
    settings_store = SettingsStore(workspace=cfg.workspace, session_root_dir=cfg.session_root_dir)
    settings = _apply_persistent_settings(cfg, args, settings_store)

    if args.list_sessions:
        store = SessionStore(
            workspace=cfg.workspace,
            session_root_dir=cfg.session_root_dir,
        )
        sessions = store.list_sessions(limit=200)
        if not sessions:
            print("No sessions found.")
            return
        for sess in sessions:
            sid = sess.get("session_id")
            created = sess.get("created_at") or "unknown"
            updated = sess.get("updated_at") or "unknown"
            print(f"{sid} | created={created} | updated={updated}")
        return

    if args.show_settings:
        _print_settings(settings)
        if not args.task and not args.list_models:
            return

    if (args.headless or non_tty) and not _has_non_interactive_command(args):
        print(
            "Headless/non-interactive mode requires --task or a non-interactive command "
            "(e.g., --list-models, --show-settings)."
        )
        raise SystemExit(2)

    creds = _load_credentials(cfg, args, allow_prompt=not (args.headless or non_tty))
    _apply_runtime_overrides(cfg, args, creds)

    if not cfg.model.strip():
        provider_model = settings.default_model_for_provider(cfg.provider)
        if provider_model:
            cfg.model = provider_model

    if args.configure_keys and not args.task and not args.list_models and not args.show_settings:
        print("Credential configuration step complete.")
        return

    if args.list_models:
        requested_provider = (args.provider or "auto").strip().lower()
        rc = _print_models(cfg, requested_provider=requested_provider)
        if rc != 0:
            raise SystemExit(rc)
        return

    if cfg.provider == "all":
        print("Provider 'all' is only valid with --list-models.")
        raise SystemExit(2)

    model_for_check = (cfg.model or "").strip()
    if model_for_check and cfg.provider != "openrouter":
        inferred = infer_provider_for_model(model_for_check)
        if inferred and inferred != cfg.provider:
            key = {
                "openai": cfg.openai_api_key,
                "anthropic": cfg.anthropic_api_key,
                "openrouter": cfg.openrouter_api_key,
                "cerebras": cfg.cerebras_api_key,
            }.get(inferred)
            if key:
                cfg.provider = inferred
            else:
                print(
                    f"Model '{model_for_check}' requires provider '{inferred}' "
                    f"but no API key is configured for it."
                )
                raise SystemExit(1)

    engine = build_engine(cfg)
    model_name = _get_model_display_name(engine)

    try:
        runtime = SessionRuntime.bootstrap(
            engine=engine,
            config=engine.config,
            session_id=args.session_id,
            resume=args.resume,
        )
    except SessionError as exc:
        print(f"Session error: {exc}")
        return

    startup_info: dict[str, str] = {
        "Provider": cfg.provider,
        "Model": model_name,
    }
    if cfg.reasoning_effort:
        startup_info["Reasoning"] = cfg.reasoning_effort
    startup_info["Mode"] = "recursive" if cfg.recursive else "flat"
    startup_info["Workspace"] = str(cfg.workspace)
    startup_info["Session"] = runtime.session_id

    ctx = ChatContext(runtime=runtime, cfg=cfg, settings_store=settings_store)

    # Build optional censor for headless / plain text paths.
    censor_fn = None
    if cfg.demo:
        from .demo import DemoCensor
        censor_fn = DemoCensor(cfg.workspace).censor_text

    def _print_startup(info: dict[str, str]) -> None:
        for key, val in info.items():
            line = f"{key:>10}  {val}"
            print(censor_fn(line) if censor_fn else line)
        print()

    if args.task:
        # Headless task mode — print config plainly, then run.
        _print_startup(startup_info)
        result = runtime.solve(args.task, on_event=lambda ev: print(
            censor_fn(f"trace> {_clip_event(ev)}") if censor_fn else f"trace> {_clip_event(ev)}"
        ))
        print(censor_fn(result) if censor_fn else result)
        return

    if args.no_tui:
        if not sys.stdin.isatty():
            print("No interactive stdin available; use --task for headless execution.")
            raise SystemExit(2)
        _print_startup(startup_info)
        run_plain_repl(ctx)
        return

    try:
        run_rich_repl(ctx, startup_info=startup_info)
    except ImportError:
        _print_startup(startup_info)
        run_plain_repl(ctx)


if __name__ == "__main__":
    main()

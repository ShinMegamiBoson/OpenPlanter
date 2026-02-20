#!/usr/bin/env python3
"""Bridge script: delegate an investigation to the OpenPlanter RLM agent.

Spawns the full OpenPlanter recursive language model agent as a subprocess
for complex investigations that exceed what the skill scripts can handle.
The RLM agent uses tiered model delegation to minimize cost while maintaining
investigation quality. Provider-agnostic: works with any LLM provider the
agent supports (Anthropic, OpenAI, OpenRouter, Cerebras) — auto-inferred
from the model name or set explicitly.

Use skill scripts when: 2 datasets, entity resolution + cross-referencing,
no web research needed. Delegate to RLM when: 3+ datasets, web search
required, iterative exploration, or 20+ reasoning steps needed.

Returns JSON to stdout with investigation results and session metadata.

Uses Python stdlib only — zero external dependencies.

Provider auto-detection examples:
    claude-*          → anthropic
    gpt-*, o1-*, o3-* → openai
    */model-name      → openrouter (slash = OpenRouter routing)
    llama*cerebras    → cerebras

API keys pass through environment variables (checked by the agent):
    ANTHROPIC_API_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY, CEREBRAS_API_KEY
    (or OPENPLANTER_-prefixed variants)

Usage:
    python3 delegate_to_rlm.py --objective "Cross-reference campaign finance
        with lobbying disclosures" --workspace /path/to/investigation
    python3 delegate_to_rlm.py --objective "..." --workspace DIR --model claude-sonnet-4-5-20250929
    python3 delegate_to_rlm.py --objective "..." --workspace DIR --model gpt-4o --provider openai
    python3 delegate_to_rlm.py --objective "..." --workspace DIR --model anthropic/claude-sonnet-4-5
    python3 delegate_to_rlm.py --objective "..." --workspace DIR --max-steps 30 --timeout 300
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Repo directory found by find_agent_command(), used as cwd for -m agent
_AGENT_REPO: Path | None = None


def find_agent_command() -> list[str] | None:
    """Locate the openplanter-agent command.

    Checks in order:
    1. openplanter-agent on PATH (pip install -e)
    2. python -m agent from known repo locations

    When using ``-m agent``, sets ``_AGENT_REPO`` so subprocess.run
    can pass the correct ``cwd``.
    """
    global _AGENT_REPO

    # Check PATH
    if shutil.which("openplanter-agent"):
        _AGENT_REPO = None
        return ["openplanter-agent"]

    # Check common repo locations
    candidates = [
        Path.home() / "Desktop" / "Programming" / "OpenPlanter",
        Path.home() / "OpenPlanter",
        Path.cwd().parent,
    ]
    for repo in candidates:
        if (repo / "agent" / "__main__.py").exists():
            _AGENT_REPO = repo
            return [sys.executable, "-m", "agent"]

    return None


def _infer_provider(model: str) -> str:
    """Infer the LLM provider from the model name.

    Mirrors the logic in agent/builder.py:infer_provider_for_model() so we
    can set a sensible default without importing the agent package.
    """
    if "/" in model:
        return "openrouter"
    lower = model.lower()
    if lower.startswith("claude"):
        return "anthropic"
    if any(lower.startswith(p) for p in ("gpt", "o1-", "o1", "o3-", "o3", "o4-", "o4", "chatgpt")):
        return "openai"
    if "cerebras" in lower:
        return "cerebras"
    # Fall back to auto — let the agent figure it out
    return "auto"


def build_command(
    objective: str,
    workspace: str,
    model: str = "claude-sonnet-4-5-20250929",
    provider: str = "auto",
    max_steps: int = 50,
    max_depth: int = 3,
    recursive: bool = True,
    acceptance_criteria: bool = True,
) -> list[str]:
    """Build the openplanter-agent CLI command.

    Provider is auto-inferred from the model name if set to "auto".
    Supports any model/provider combination the OpenPlanter agent supports:
    Anthropic (claude-*), OpenAI (gpt-*, o1-*, o3-*), OpenRouter (org/model),
    Cerebras (llama*cerebras, qwen-*).
    """
    agent_cmd = find_agent_command()
    if not agent_cmd:
        raise RuntimeError(
            "openplanter-agent not found. Install with: "
            "pip install -e /path/to/OpenPlanter"
        )

    resolved_provider = provider if provider != "auto" else _infer_provider(model)

    cmd = [
        *agent_cmd,
        "--task", objective,
        "--workspace", workspace,
        "--model", model,
        "--max-steps", str(max_steps),
        "--max-depth", str(max_depth),
        "--headless",
    ]
    # Only pass --provider if we resolved to a specific one
    if resolved_provider != "auto":
        cmd.extend(["--provider", resolved_provider])
    if recursive:
        cmd.append("--recursive")
    if acceptance_criteria:
        cmd.append("--acceptance-criteria")
    return cmd


def parse_output(stdout: str) -> tuple[str, list[str]]:
    """Separate trace lines from the final answer."""
    lines = stdout.strip().split("\n")
    trace_lines = []
    answer_lines = []
    in_answer = False

    for line in lines:
        if line.startswith("trace>"):
            trace_lines.append(line)
            in_answer = False
        elif line.startswith("  ") and not in_answer and not trace_lines:
            # Startup info lines (Provider, Model, etc.)
            continue
        else:
            answer_lines.append(line)
            in_answer = True

    answer = "\n".join(answer_lines).strip()
    return answer, trace_lines


def collect_session_artifacts(workspace: Path) -> dict:
    """Find the most recent session and collect its metadata."""
    session_dir = workspace / ".openplanter" / "sessions"
    if not session_dir.exists():
        return {}

    sessions = sorted(
        [d for d in session_dir.iterdir() if d.is_dir()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not sessions:
        return {}

    latest = sessions[0]
    artifacts: dict = {
        "session_id": latest.name,
        "session_path": str(latest),
    }

    # Read metadata
    meta_path = latest / "metadata.json"
    if meta_path.exists():
        try:
            artifacts["metadata"] = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    # List artifact files
    art_dir = latest / "artifacts"
    if art_dir.exists():
        artifacts["artifact_files"] = [
            str(p.relative_to(latest))
            for p in art_dir.rglob("*")
            if p.is_file()
        ]

    # Read investigation plan if exists
    plans = sorted(
        latest.glob("*.plan.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if plans:
        try:
            artifacts["plan"] = plans[0].read_text(encoding="utf-8")[:5000]
        except OSError:
            pass

    return artifacts


def collect_output_files(workspace: Path) -> list[str]:
    """List investigation output files in the workspace."""
    output_files = []
    for subdir in ["findings", "entities", "evidence"]:
        d = workspace / subdir
        if d.exists():
            for f in d.iterdir():
                if f.is_file() and f.name != ".gitkeep":
                    output_files.append(str(f.relative_to(workspace)))
    return output_files


def run_delegation(
    objective: str,
    workspace: str,
    model: str = "claude-sonnet-4-5-20250929",
    provider: str = "auto",
    max_steps: int = 50,
    max_depth: int = 3,
    timeout: int = 600,
    recursive: bool = True,
    acceptance_criteria: bool = True,
) -> dict:
    """Run the OpenPlanter agent and return structured results."""
    ws = Path(workspace).resolve()

    try:
        cmd = build_command(
            objective=objective,
            workspace=str(ws),
            model=model,
            provider=provider,
            max_steps=max_steps,
            max_depth=max_depth,
            recursive=recursive,
            acceptance_criteria=acceptance_criteria,
        )
    except RuntimeError as e:
        return {
            "status": "error",
            "answer": None,
            "error": str(e),
            "elapsed_sec": 0,
        }

    t0 = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ},
            cwd=str(_AGENT_REPO) if _AGENT_REPO else None,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "answer": None,
            "error": f"RLM agent exceeded {timeout}s timeout",
            "elapsed_sec": round(time.monotonic() - t0, 2),
        }
    except FileNotFoundError:
        return {
            "status": "error",
            "answer": None,
            "error": "openplanter-agent command not found",
            "elapsed_sec": round(time.monotonic() - t0, 2),
        }

    elapsed = round(time.monotonic() - t0, 2)
    answer, trace_lines = parse_output(result.stdout)

    return {
        "status": "success" if result.returncode == 0 else "error",
        "answer": answer,
        "exit_code": result.returncode,
        "stderr": result.stderr[:2000] if result.stderr else None,
        "trace_steps": len(trace_lines),
        "artifacts": collect_session_artifacts(ws),
        "output_files": collect_output_files(ws),
        "elapsed_sec": elapsed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Delegate an investigation to the OpenPlanter RLM agent"
    )
    parser.add_argument(
        "--objective", required=True,
        help="Investigation objective (what the agent should accomplish)",
    )
    parser.add_argument(
        "--workspace", required=True, type=Path,
        help="Path to investigation workspace directory",
    )
    parser.add_argument(
        "--model", default="claude-sonnet-4-5-20250929",
        help="Model name for the top-level agent. Provider is auto-inferred "
             "from the name: claude-* → anthropic, gpt-*/o1-* → openai, "
             "org/model → openrouter. (default: claude-sonnet-4-5-20250929)",
    )
    parser.add_argument(
        "--provider", default="auto",
        help="LLM provider: auto, anthropic, openai, openrouter, cerebras. "
             "'auto' infers from the model name. (default: auto)",
    )
    parser.add_argument(
        "--max-steps", type=int, default=50,
        help="Maximum steps per agent call (default: 50)",
    )
    parser.add_argument(
        "--max-depth", type=int, default=3,
        help="Maximum recursion depth for sub-agents (default: 3)",
    )
    parser.add_argument(
        "--timeout", type=int, default=600,
        help="Wall-clock timeout in seconds (default: 600)",
    )
    parser.add_argument(
        "--no-recursive", action="store_true",
        help="Disable recursive sub-agent delegation",
    )
    parser.add_argument(
        "--no-acceptance-criteria", action="store_true",
        help="Disable acceptance criteria judging",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Check if openplanter-agent is available and exit",
    )
    args = parser.parse_args()

    if args.check:
        cmd = find_agent_command()
        if cmd:
            print(json.dumps({"available": True, "command": cmd}))
        else:
            print(json.dumps({"available": False, "error": "openplanter-agent not found"}))
            sys.exit(1)
        return

    workspace = args.workspace.resolve()
    if not workspace.exists():
        print(
            json.dumps({"status": "error", "error": f"Workspace does not exist: {workspace}"}),
        )
        sys.exit(1)

    result = run_delegation(
        objective=args.objective,
        workspace=str(workspace),
        model=args.model,
        provider=args.provider,
        max_steps=args.max_steps,
        max_depth=args.max_depth,
        timeout=args.timeout,
        recursive=not args.no_recursive,
        acceptance_criteria=not args.no_acceptance_criteria,
    )
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "success" else 1)


if __name__ == "__main__":
    main()

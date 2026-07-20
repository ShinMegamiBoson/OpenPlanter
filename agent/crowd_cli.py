"""Headless CLI for OpenPlanter Crowd operations.

Used by the Tauri desktop app to perform crowd tasks via the Python backend.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .config import AgentConfig
from .crowd import CrowdStore, CrowdTask, crowd_client_from_config
from .settings import SettingsStore


def _load_client(workspace: str):
    ws = Path(workspace)
    cfg = AgentConfig.from_env(ws)
    cfg.crowd_enabled = True
    settings = SettingsStore(ws, cfg.session_root_dir).load().to_json()
    return crowd_client_from_config(cfg, settings)


def _task_preview(task: CrowdTask) -> dict[str, object]:
    return {
        "task_hash": task.task_hash,
        "objective": task.objective,
        "tags": task.tags,
        "status": task.status,
        "stake": task.stake,
        "created_at": task.created_at,
    }


def cmd_publish(args: argparse.Namespace) -> int:
    client = _load_client(args.workspace)
    raw = " ".join(args.args) if args.args else ""
    tags, objective = _parse_tags_and_objective(raw)
    if not objective.strip():
        _error("Missing objective. Usage: publish #tag ... <objective>")
        return 1
    task = CrowdTask.build(
        objective=objective,
        acceptance_criteria=args.acceptance or "",
        context_hash=args.context or "",
        tags=tags,
        stake=args.stake or "low",
        required_tier=args.tier,
        deadline=args.deadline,
    )
    event = client.publish_task(task)
    _ok(
        {
            "task": _task_preview(task),
            "event_id": event.id,
            "pubkey": event.pubkey,
        }
    )
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    client = _load_client(args.workspace)
    status = args.status or ("open" if args.open else None)
    tasks = client.store.list_tasks(status=status, tags=args.tags or None)
    _ok({"tasks": [_task_preview(t) for t in tasks]})
    return 0


def cmd_claim(args: argparse.Namespace) -> int:
    client = _load_client(args.workspace)
    prefix = args.hash or ""
    task = _resolve_task(client.store, prefix)
    if task is None:
        _error(f"Task not found: {prefix}")
        return 1
    event = client.claim_task(task.task_hash)
    if event is None:
        _error(f"Could not claim task {task.task_hash[:12]} (not open)")
        return 1
    updated = client.store.get_task(task.task_hash)
    _ok({"task": _task_preview(updated or task), "event_id": event.id})
    return 0


def cmd_cancel(args: argparse.Namespace) -> int:
    client = _load_client(args.workspace)
    prefix = args.hash or ""
    task = _resolve_task(client.store, prefix)
    if task is None:
        _error(f"Task not found: {prefix}")
        return 1
    event = client.cancel_task(task.task_hash)
    if event is None:
        _error(f"Could not cancel task {task.task_hash[:12]}")
        return 1
    updated = client.store.get_task(task.task_hash)
    _ok({"task": _task_preview(updated or task), "event_id": event.id})
    return 0


def cmd_trust(args: argparse.Namespace) -> int:
    client = _load_client(args.workspace)
    npub = args.npub or ""
    client.store.add_trusted(npub)
    _ok({"trusted": npub})
    return 0


def _resolve_task(store: CrowdStore, prefix: str):
    task = store.get_task(prefix)
    if task is not None:
        return task
    candidates = [t for t in store.list_tasks() if t.task_hash.startswith(prefix)]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _parse_tags_and_objective(text: str):
    tags: list[str] = []
    parts = text.split()
    rest: list[str] = []
    for p in parts:
        if p.startswith("#"):
            tags.append(p[1:])
        else:
            rest.append(p)
    return tags, " ".join(rest)


def _ok(payload: dict) -> None:
    print(json.dumps({"ok": True, **payload}), flush=True)


def _error(message: str) -> None:
    print(json.dumps({"ok": False, "error": message}), flush=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openplanter-crowd", description="OpenPlanter Crowd CLI")
    parser.add_argument("--workspace", default=".", help="Workspace directory")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("publish", help="Publish a crowd task")
    p.add_argument("args", nargs="*", help="#tag ... <objective>")
    p.add_argument("--acceptance", default="", help="Acceptance criteria")
    p.add_argument("--context", default="", help="Context hash")
    p.add_argument("--stake", default="low", help="Stake")
    p.add_argument("--tier", default=None, help="Required tier")
    p.add_argument("--deadline", default=None, help="Deadline")
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser("list", help="List tasks")
    p.add_argument("--status", default=None, help="Filter by status")
    p.add_argument("--open", action="store_true", help="Only open tasks")
    p.add_argument("--tags", nargs="*", default=None, help="Filter by tags")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("claim", help="Claim a task")
    p.add_argument("hash", help="Task hash or prefix")
    p.set_defaults(func=cmd_claim)

    p = sub.add_parser("cancel", help="Cancel a task")
    p.add_argument("hash", help="Task hash or prefix")
    p.set_defaults(func=cmd_cancel)

    p = sub.add_parser("trust", help="Trust a worker npub")
    p.add_argument("npub", help="Worker public key (hex)")
    p.set_defaults(func=cmd_trust)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

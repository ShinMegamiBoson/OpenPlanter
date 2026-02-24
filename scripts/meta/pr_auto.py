#!/usr/bin/env python3
"""Autonomous PR workflow with deterministic preflight checks.

Usage:
  python scripts/meta/pr_auto.py --preflight-only --expected-origin-repo my-repo
  python scripts/meta/pr_auto.py --expected-origin-repo my-repo --fill --auto-merge
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Mapping


GITHUB_TOKEN_ENV_VARS: tuple[str, ...] = (
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GITHUB_ENTERPRISE_TOKEN",
)

IGNORABLE_STATUS_PREFIXES: tuple[str, ...] = (
    "?? .claude/active-work.yaml",
    "?? .claude/sessions/",
)


def sanitize_github_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return env with token overrides removed so gh uses stored auth."""
    base = dict(env if env is not None else os.environ)
    for var in GITHUB_TOKEN_ENV_VARS:
        base.pop(var, None)
    base.setdefault("GIT_CONFIG_NOSYSTEM", "1")
    return base


def parse_github_repo_slug(remote_url: str) -> str | None:
    """Parse owner/repo slug from common GitHub remote URL forms."""
    candidate = remote_url.strip()
    if not candidate:
        return None
    match = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$", candidate)
    if not match:
        return None
    owner = match.group(1).strip()
    repo = match.group(2).strip()
    if not owner or not repo:
        return None
    return f"{owner}/{repo}"


def origin_matches_expected_repo(remote_url: str, expected_repo: str) -> bool:
    """Return True when origin URL resolves to the expected repository name."""
    slug = parse_github_repo_slug(remote_url)
    if slug is None:
        return False
    repo = slug.split("/", 1)[1]
    return repo == expected_repo


def filter_non_ignorable_status_lines(lines: list[str]) -> list[str]:
    """Drop known transient metadata files from git-status output lines."""
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if any(stripped.startswith(prefix) for prefix in IGNORABLE_STATUS_PREFIXES):
            continue
        out.append(stripped)
    return out


def run_cmd(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run command in cwd and return captured completed-process output."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        check=check,
        capture_output=True,
        text=True,
    )


def _git_stdout(args: list[str], *, cwd: Path) -> str:
    return run_cmd(["git", *args], cwd=cwd).stdout.strip()


def _gh(
    args: list[str],
    *,
    cwd: Path,
    gh_env: dict[str, str],
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return run_cmd(["gh", *args], cwd=cwd, env=gh_env, check=check)


def _ensure_clean_tree(cwd: Path) -> None:
    raw = _git_stdout(["status", "--short"], cwd=cwd).splitlines()
    filtered = filter_non_ignorable_status_lines(raw)
    if filtered:
        raise SystemExit(
            "Preflight failed: working tree has non-ignorable changes:\n"
            + "\n".join(f"  {line}" for line in filtered),
        )


def _ensure_branch(cwd: Path) -> str:
    branch = _git_stdout(["branch", "--show-current"], cwd=cwd)
    if branch in {"", "main", "master"}:
        raise SystemExit(
            "Preflight failed: run pr-auto from a feature branch (not main/master).",
        )
    return branch


def _ensure_origin(cwd: Path, expected_repo: str) -> None:
    origin_url = _git_stdout(["config", "--get", "remote.origin.url"], cwd=cwd)
    if not origin_matches_expected_repo(origin_url, expected_repo):
        raise SystemExit(
            f"Preflight failed: origin '{origin_url}' does not match expected repo '{expected_repo}'.",
        )


def _switch_gh_account(cwd: Path, gh_env: dict[str, str], account: str) -> None:
    result = _gh(["auth", "switch", "-u", account], cwd=cwd, gh_env=gh_env, check=False)
    if result.returncode != 0:
        raise SystemExit(
            "GitHub auth switch failed. Run: gh auth login\n"
            f"stderr: {result.stderr.strip()}",
        )


def _fetch_and_rebase(cwd: Path, base: str) -> None:
    run_cmd(["git", "fetch", "origin", base], cwd=cwd)
    run_cmd(["git", "rebase", f"origin/{base}"], cwd=cwd)


def _push_branch(cwd: Path) -> None:
    run_cmd(["git", "push", "-u", "origin", "HEAD"], cwd=cwd)


def _find_open_pr(
    *,
    cwd: Path,
    gh_env: dict[str, str],
    branch: str,
    base: str,
) -> tuple[int, str] | None:
    result = _gh(
        ["pr", "list", "--head", branch, "--base", base, "--state", "open", "--json", "number,url"],
        cwd=cwd,
        gh_env=gh_env,
    )
    data = json.loads(result.stdout)
    if not isinstance(data, list) or not data:
        return None
    first = data[0]
    return int(first["number"]), str(first["url"])


def _create_pr(
    *,
    cwd: Path,
    gh_env: dict[str, str],
    branch: str,
    base: str,
    fill: bool,
    title: str | None,
    body_file: Path | None,
) -> None:
    cmd = ["pr", "create", "--base", base, "--head", branch]
    if fill:
        cmd.append("--fill")
    if title:
        cmd.extend(["--title", title])
    if body_file:
        cmd.extend(["--body-file", str(body_file)])
    _gh(cmd, cwd=cwd, gh_env=gh_env)


def _enable_auto_merge(*, cwd: Path, gh_env: dict[str, str], pr_number: int) -> bool:
    result = _gh(
        ["pr", "merge", str(pr_number), "--squash", "--delete-branch", "--auto"],
        cwd=cwd,
        gh_env=gh_env,
        check=False,
    )
    if result.returncode == 0:
        return True

    stderr = result.stderr.strip()
    if "enablePullRequestAutoMerge" in stderr or "Auto merge is not allowed" in stderr:
        print("Auto-merge unavailable for this repository policy; PR remains open.")
        return False

    raise SystemExit(
        "Failed to enable auto-merge.\n"
        f"stdout: {result.stdout.strip()}\n"
        f"stderr: {stderr}",
    )


def main() -> int:
    """Execute preflighted non-interactive PR flow."""
    parser = argparse.ArgumentParser(description="Autonomous PR workflow with preflight checks.")
    parser.add_argument("--base", default="main", help="Target base branch.")
    parser.add_argument("--expected-origin-repo", required=True, help="Expected origin repo name (e.g., my-repo).")
    parser.add_argument("--account", default="BrianMills2718", help="GitHub account for gh auth switch.")
    parser.add_argument("--fill", action="store_true", help="Use gh --fill when creating PR.")
    parser.add_argument("--title", default=None, help="PR title (optional).")
    parser.add_argument("--body-file", type=Path, default=None, help="PR body file path.")
    parser.add_argument("--preflight-only", action="store_true", help="Run checks only; do not rebase/push/create.")
    parser.add_argument("--auto-merge", action="store_true", help="Enable auto-merge after PR create/reuse.")
    args = parser.parse_args()

    cwd = Path.cwd()
    gh_env = sanitize_github_env()

    branch = _ensure_branch(cwd)
    _ensure_clean_tree(cwd)
    _ensure_origin(cwd, args.expected_origin_repo)
    _switch_gh_account(cwd, gh_env, args.account)

    if args.preflight_only:
        print("Preflight passed.")
        return 0

    _fetch_and_rebase(cwd, args.base)
    _push_branch(cwd)

    pr = _find_open_pr(cwd=cwd, gh_env=gh_env, branch=branch, base=args.base)
    if pr is None:
        _create_pr(
            cwd=cwd,
            gh_env=gh_env,
            branch=branch,
            base=args.base,
            fill=args.fill,
            title=args.title,
            body_file=args.body_file,
        )
        pr = _find_open_pr(cwd=cwd, gh_env=gh_env, branch=branch, base=args.base)
        if pr is None:
            raise SystemExit("PR creation failed: unable to locate open PR after create.")

    pr_number, pr_url = pr
    print(f"PR: {pr_url}")

    if args.auto_merge:
        enabled = _enable_auto_merge(cwd=cwd, gh_env=gh_env, pr_number=pr_number)
        if enabled:
            print(f"Auto-merge enabled for PR #{pr_number}.")
        else:
            print(f"Auto-merge not enabled for PR #{pr_number}.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

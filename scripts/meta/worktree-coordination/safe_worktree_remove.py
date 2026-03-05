#!/usr/bin/env python3
"""Safely remove a git worktree, checking for uncommitted changes first.

This prevents accidental data loss when removing worktrees that have
uncommitted changes (which are lost forever when the worktree is removed).

Usage:
    python scripts/safe_worktree_remove.py <worktree-path>
    python scripts/safe_worktree_remove.py worktrees/plan-46-review-fix

    # Force removal (skips safety check)
    python scripts/safe_worktree_remove.py --force <worktree-path>
"""

import argparse
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml


# Session marker settings
SESSION_MARKER_FILE = ".claude_session"
SESSION_STALENESS_HOURS = 24  # Block removal if marker is newer than this


def run_cmd(cmd: list[str], cwd: str | None = None) -> tuple[bool, str]:
    """Run command and return (success, output)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1"},
        )
        return result.returncode == 0, result.stdout.strip()
    except Exception as e:
        return False, str(e)


def has_uncommitted_changes(worktree_path: str) -> tuple[bool, str]:
    """Check if worktree has uncommitted changes.

    Returns (has_changes, details).
    """
    # Check for modified/staged/untracked files
    success, output = run_cmd(
        ["git", "status", "--porcelain"],
        cwd=worktree_path
    )

    if not success:
        return False, f"Could not check status: {output}"

    if output.strip():
        return True, output

    return False, ""


def get_worktree_branch(worktree_path: str) -> str | None:
    """Get the branch name of a worktree."""
    success, output = run_cmd(
        ["git", "branch", "--show-current"],
        cwd=worktree_path
    )
    return output if success else None


def get_main_repo_root() -> Path:
    """Get the main repo root (not worktree).

    For worktrees, returns the main repository's root directory.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1"},
        )
        git_dir = Path(result.stdout.strip())
        return git_dir.parent
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd()


def get_current_cc_identity() -> dict[str, Any]:
    """Get the current CC instance's identity.

    Returns dict with:
        - branch: Current git branch name
        - is_main: True if on main branch
        - cwd: Current working directory name
    """
    # Get current branch
    success, branch = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    branch = branch if success else ""

    return {
        "branch": branch,
        "is_main": branch == "main",
        "cwd": Path.cwd().name,
    }


def check_worktree_claimed(
    worktree_path: str,
    claims_file: Path | None = None,
) -> tuple[bool, dict[str, Any] | None]:
    """Check if a worktree has an active claim.

    Args:
        worktree_path: Path to the worktree to check
        claims_file: Optional path to claims file (for testing)

    Returns:
        (is_claimed, claim_info) - claim_info is the claim dict if found
    """
    if claims_file is None:
        claims_file = get_main_repo_root() / ".claude" / "active-work.yaml"

    if not claims_file.exists():
        return False, None

    try:
        data = yaml.safe_load(claims_file.read_text()) or {}
    except yaml.YAMLError:
        return False, None

    claims = data.get("claims", [])

    # Normalize the worktree path for comparison
    normalized_path = str(Path(worktree_path).resolve())

    for claim in claims:
        claim_worktree = claim.get("worktree_path")
        if claim_worktree:
            # Normalize claim's worktree path too
            normalized_claim_path = str(Path(claim_worktree).resolve())
            if normalized_path == normalized_claim_path:
                return True, claim

    return False, None


def check_session_marker_recent(worktree_path: str) -> tuple[bool, datetime | None]:
    """Check if session marker exists and is recent (< 24h old).

    The session marker is created when a worktree is created and refreshed
    on every Edit/Write operation. If the marker is recent, a Claude session
    is likely still using this worktree.

    Args:
        worktree_path: Path to the worktree to check

    Returns:
        (is_recent, marker_time) - is_recent is True if marker exists and is < 24h old
    """
    marker_path = Path(worktree_path) / SESSION_MARKER_FILE

    if not marker_path.exists():
        return False, None

    try:
        content = marker_path.read_text().strip()
        # Parse ISO format timestamp
        marker_time = datetime.fromisoformat(content)

        # Ensure timezone aware for comparison
        if marker_time.tzinfo is None:
            marker_time = marker_time.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        age = now - marker_time

        if age < timedelta(hours=SESSION_STALENESS_HOURS):
            return True, marker_time

        return False, marker_time
    except (ValueError, OSError):
        # Can't parse marker - treat as not recent
        return False, None


def should_block_removal(
    worktree_path: str,
    force: bool = False,
    claims_file: Path | None = None,
    my_identity: dict[str, Any] | None = None,
) -> tuple[bool, str, dict[str, Any] | None]:
    """Determine if worktree removal should be blocked.

    Checks three conditions (Plan #115: Worktree Ownership Enforcement):
    1. Ownership mismatch - claim exists but belongs to different CC instance
    2. Active claim in .claude/active-work.yaml (same owner)
    3. Recent session marker (< 24h old) - indicates active Claude session

    Args:
        worktree_path: Path to the worktree
        force: If True, don't block (still returns info)
        claims_file: Optional path to claims file (for testing)
        my_identity: Optional identity dict (for testing), otherwise auto-detected

    Returns:
        (should_block, reason, info) where:
        - should_block: True if removal should be blocked (and force=False)
        - reason: "ownership", "claim", "session_marker", or "" if not blocked
        - info: claim dict or session marker info
    """
    # Get current CC identity for ownership comparison
    if my_identity is None:
        my_identity = get_current_cc_identity()

    # Check for active claims first
    is_claimed, claim_info = check_worktree_claimed(worktree_path, claims_file)

    if is_claimed and claim_info and not force:
        # Check if the claim owner matches our identity
        claim_owner = claim_info.get("cc_id", "")

        # Match by branch name or directory name
        my_branch = my_identity.get("branch", "")
        my_cwd = my_identity.get("cwd", "")

        # Owner matches if our branch/cwd matches the claim's cc_id
        is_mine = claim_owner and (claim_owner == my_branch or claim_owner == my_cwd)

        if not is_mine:
            # Different owner - block with ownership reason
            return True, "ownership", claim_info

        # Same owner but still claimed - block with claim reason
        return True, "claim", claim_info

    # Check for recent session marker
    is_recent, marker_time = check_session_marker_recent(worktree_path)
    if is_recent and not force:
        return True, "session_marker", {"marker_time": marker_time}

    # Return claim info if available for informational purposes
    return False, "", claim_info


def remove_worktree(worktree_path: str, force: bool = False) -> bool:
    """Remove a worktree safely.

    Returns True if removal succeeded, False otherwise.
    """
    path = Path(worktree_path)

    if not path.exists():
        print(f"❌ Worktree path does not exist: {worktree_path}")
        return False

    # Check if we're currently inside the worktree we're trying to delete
    # This would break our shell (CWD becomes invalid after deletion)
    try:
        current_dir = os.getcwd()
        worktree_abs = os.path.abspath(worktree_path)
        if current_dir.startswith(worktree_abs):
            # Get repo root for recovery instructions
            repo_root = Path(__file__).parent.parent.resolve()
            print("❌ BLOCKED: Cannot delete worktree you're currently in!")
            print(f"   Your shell CWD: {current_dir}")
            print(f"   Worktree path:  {worktree_abs}")
            print()
            print("   This would break your shell. First run:")
            print(f"   cd {repo_root}")
            print("   Then retry the removal.")
            return False
    except OSError:
        # getcwd() can fail if CWD is already invalid
        pass

    # Check for active claims or recent session marker (Plan #52: Worktree Session Tracking)
    # Extended with ownership check (Plan #115: Worktree Ownership Enforcement)
    block, reason, info = should_block_removal(worktree_path, force)

    # Ownership block is the strongest - you should NEVER remove someone else's worktree
    if block and reason == "ownership" and info:
        cc_id = info.get("cc_id", "unknown")
        task = info.get("task", "")[:50]
        plan = info.get("plan")
        print(f"❌ BLOCKED: Worktree owned by another CC instance!")
        print(f"   Owner: {cc_id}")
        if plan:
            print(f"   Plan: #{plan}")
        print(f"   Task: {task}")
        print()
        print("   You cannot remove worktrees you don't own.")
        print("   The owner's shell will break if you remove their worktree.")
        print()
        print("   This worktree belongs to another Claude Code instance.")
        print("   Let the OWNER clean up their own worktree (from main).")
        print()
        print("   If the owner is gone and cleanup is needed:")
        print(f"   1. Have the owner run: cd /path/to/main && make finish BRANCH=... PR=...")
        print(f"   2. Or release their claim: python scripts/check_claims.py --release --id {cc_id}")
        print(f"   3. Then force remove (DANGEROUS): python scripts/safe_worktree_remove.py --force {worktree_path}")
        return False

    if block and reason == "claim" and info:
        cc_id = info.get("cc_id", "unknown")
        task = info.get("task", "")[:50]
        plan = info.get("plan")
        print(f"❌ BLOCKED: Worktree has an active claim!")
        print(f"   Claimed by: {cc_id}")
        if plan:
            print(f"   Plan: #{plan}")
        print(f"   Task: {task}")
        print()
        print("   A Claude session may be actively using this worktree.")
        print("   Removing it will break their shell (CWD becomes invalid).")
        print()
        print("   Options:")
        print(f"   1. Release the claim first: python scripts/check_claims.py --release --id {cc_id}")
        print(f"   2. Force remove (BREAKS SESSION): python scripts/safe_worktree_remove.py --force {worktree_path}")
        return False

    if block and reason == "session_marker" and info:
        marker_time = info.get("marker_time")
        if marker_time:
            age = datetime.now(timezone.utc) - marker_time
            age_str = f"{age.seconds // 3600}h {(age.seconds % 3600) // 60}m ago"
        else:
            age_str = "recently"
        print(f"❌ BLOCKED: Session marker is recent!")
        print(f"   Last activity: {age_str}")
        print()
        print("   A Claude session may be actively using this worktree.")
        print("   The session marker is updated on every Edit/Write operation.")
        print()
        print("   Options:")
        print(f"   1. Wait until marker is > {SESSION_STALENESS_HOURS}h old")
        print(f"   2. Delete the marker: rm {worktree_path}/{SESSION_MARKER_FILE}")
        print(f"   3. Force remove (BREAKS SESSION): python scripts/safe_worktree_remove.py --force {worktree_path}")
        return False

    # Check for uncommitted changes
    has_changes, details = has_uncommitted_changes(worktree_path)

    if has_changes and not force:
        branch = get_worktree_branch(worktree_path) or "unknown"
        print(f"❌ BLOCKED: Worktree '{worktree_path}' has uncommitted changes!")
        print(f"   Branch: {branch}")
        print(f"   Changes:")
        for line in details.split("\n")[:10]:  # Show first 10 changes
            print(f"      {line}")
        if details.count("\n") > 10:
            print(f"      ... and {details.count(chr(10)) - 10} more")
        print()
        print("   Options:")
        print(f"   1. Commit changes: cd {worktree_path} && git add -A && git commit -m 'WIP'")
        print(f"   2. Discard changes: cd {worktree_path} && git checkout -- .")
        print(f"   3. Force remove (LOSES CHANGES): python scripts/safe_worktree_remove.py --force {worktree_path}")
        return False

    # Remove the worktree
    success, output = run_cmd(["git", "worktree", "remove", worktree_path])

    if success:
        print(f"✅ Worktree removed: {worktree_path}")
        return True
    else:
        # Try with --force if regular remove failed (e.g., untracked files)
        if force:
            success, output = run_cmd(["git", "worktree", "remove", "--force", worktree_path])
            if success:
                print(f"✅ Worktree force-removed: {worktree_path}")
                return True

        print(f"❌ Failed to remove worktree: {output}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Safely remove a git worktree, checking for uncommitted changes first."
    )
    parser.add_argument(
        "worktree_path",
        help="Path to the worktree to remove (e.g., worktrees/plan-46-review-fix)"
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Force removal even if there are uncommitted changes (DATA LOSS WARNING)"
    )

    args = parser.parse_args()

    if args.force:
        print("⚠️  WARNING: Force mode - uncommitted changes will be LOST!")

    success = remove_worktree(args.worktree_path, force=args.force)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

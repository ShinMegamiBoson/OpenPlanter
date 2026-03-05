#!/usr/bin/env python3
"""Merge PR via GitHub CLI.

Usage:
    python scripts/merge_pr.py 123           # Merge PR #123
    python scripts/merge_pr.py 123 --dry-run # Check without merging

Note: Branch protection rules ensure:
- PRs require passing CI checks before merge
- Direct pushes to main are blocked
- GitHub handles concurrent merge attempts atomically

The previous lock mechanism was removed because branch protection
makes it redundant, and it cannot work (can't push directly to main).
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def run_cmd(
    cmd: list[str], check: bool = True, capture: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run a command, optionally capturing output."""
    env = os.environ.copy()
    env["GIT_CONFIG_NOSYSTEM"] = "1"  # Fix for gh CLI
    return subprocess.run(
        cmd,
        check=check,
        capture_output=capture,
        text=True,
        env=env,
    )


def get_pr_branch(pr_number: int) -> str | None:
    """Get the head branch name for a PR."""
    result = run_cmd(
        ["gh", "pr", "view", str(pr_number), "--json", "headRefName"],
        check=False,
    )
    if result.returncode != 0:
        return None
    data = json.loads(result.stdout)
    return data.get("headRefName")


def find_worktree_for_branch(branch: str) -> Path | None:
    """Find local worktree path for a branch, if it exists."""
    result = run_cmd(["git", "worktree", "list", "--porcelain"], check=False)
    if result.returncode != 0:
        return None

    # Parse porcelain output: worktree path, HEAD sha, branch on separate lines
    current_path = None
    for line in result.stdout.strip().split("\n"):
        if line.startswith("worktree "):
            current_path = Path(line[9:])
        elif line.startswith("branch refs/heads/"):
            worktree_branch = line[18:]
            if worktree_branch == branch:
                return current_path
    return None


def release_claim_for_branch(branch: str) -> bool:
    """Release any claim associated with this branch. PR merged = work done.

    Gracefully degrades if claims system is not installed (worktree-coordination module).
    """
    # Try both script locations (portable: scripts/meta, project: scripts, worktree-coord)
    for script_path in [
        "scripts/worktree-coordination/check_claims.py",
        "scripts/meta/worktree-coordination/check_claims.py",
        "scripts/check_claims.py",
        "scripts/meta/check_claims.py",
    ]:
        if Path(script_path).exists():
            result = run_cmd(
                ["python", script_path, "--release", "--id", branch, "--force"],
                check=False,
            )
            if result.returncode == 0 and "Released" in result.stdout:
                print(f"   Released claim for '{branch}'")
                return True
            return False  # Script exists but no claim - that's fine
    # Claims system not installed - skip silently
    return False


def cleanup_worktree(branch: str) -> bool:
    """Clean up local worktree for a branch. Returns True if successful."""
    worktree_path = find_worktree_for_branch(branch)
    if not worktree_path:
        return True  # No worktree to clean up

    print(f"🧹 Cleaning up local worktree for branch '{branch}'...")

    # First, release any claim for this branch (PR merged = work is complete)
    # This must happen before worktree removal, which is blocked by active claims
    release_claim_for_branch(branch)

    # Use make worktree-remove which has safety checks
    result = run_cmd(
        ["make", "worktree-remove", f"BRANCH={branch}"],
        check=False,
    )

    if result.returncode != 0:
        # Worktree removal failed - warn but don't fail the merge
        print(f"⚠️  Could not auto-cleanup worktree: {result.stderr or result.stdout}")
        print(f"   Run manually: make worktree-remove BRANCH={branch}")
        return False

    print(f"✅ Cleaned up worktree at {worktree_path}")
    return True


def check_pr_mergeable(pr_number: int) -> tuple[bool, str]:
    """Check if PR is mergeable. Returns (mergeable, reason)."""
    result = run_cmd(
        [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--json",
            "mergeable,mergeStateStatus,statusCheckRollup",
        ],
        check=False,
    )

    if result.returncode != 0:
        return False, f"Failed to get PR status: {result.stderr}"

    data = json.loads(result.stdout)

    mergeable = data.get("mergeable", "UNKNOWN")
    state = data.get("mergeStateStatus", "UNKNOWN")

    if mergeable == "CONFLICTING":
        return False, "PR has merge conflicts - needs rebase"

    if state == "BEHIND":
        return False, "PR is behind main - needs rebase"

    if state == "BLOCKED":
        # Check which checks are failing
        checks = data.get("statusCheckRollup", []) or []
        failing = [
            c.get("context", "unknown")
            for c in checks
            if c.get("conclusion") == "FAILURE"
            and c.get("context") != "feature-coverage"
        ]
        if failing:
            return False, f"Required checks failing: {', '.join(failing)}"

        pending = [
            c.get("context", "unknown")
            for c in checks
            if c.get("status") in ("IN_PROGRESS", "QUEUED", "PENDING")
        ]
        if pending:
            return False, f"Checks still running: {', '.join(pending)}"

    return True, "OK"


def merge_pr(pr_number: int, dry_run: bool = False) -> bool:
    """Merge a PR. Returns True if successful."""
    print(f"🔍 Checking PR #{pr_number}...")

    # Get branch name before merge (needed for worktree cleanup)
    branch = get_pr_branch(pr_number)

    # Fetch latest
    print("📥 Fetching latest...")
    run_cmd(["git", "fetch", "origin"], check=False)

    # Check if PR is mergeable
    mergeable, reason = check_pr_mergeable(pr_number)
    if not mergeable:
        print(f"❌ PR #{pr_number} cannot be merged: {reason}")
        return False

    print(f"✅ PR #{pr_number} is mergeable")

    if dry_run:
        print(f"\n🔍 Dry run complete. PR #{pr_number} is ready to merge.")
        return True

    # Merge
    print(f"🚀 Merging PR #{pr_number}...")
    try:
        result = run_cmd(
            ["gh", "pr", "merge", str(pr_number), "--squash", "--delete-branch"],
            check=False,
        )

        if result.returncode != 0:
            # Check for specific errors
            stderr = result.stderr or ""
            if "used by worktree" in stderr:
                # Branch deleted on remote but local worktree exists - this is OK
                print(f"✅ PR #{pr_number} merged (local worktree still exists)")
            else:
                print(f"❌ Merge failed: {stderr}")
                return False
        else:
            print(f"✅ PR #{pr_number} merged successfully")

    except subprocess.CalledProcessError as e:
        print(f"❌ Merge failed: {e}")
        return False

    # Pull latest
    print("📥 Pulling latest main...")
    run_cmd(["git", "pull", "--rebase", "origin", "main"], check=False)

    # Clean up local worktree if it exists
    if branch:
        cleanup_worktree(branch)

    print(f"\n✅ Done! PR #{pr_number} has been merged.")
    return True


def main() -> int:
    # Prevent CWD-in-deleted-worktree issue
    # Always run from project root, not from a worktree that may be deleted
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)

    parser = argparse.ArgumentParser(
        description="Merge PR via GitHub CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("pr", type=int, nargs="?", help="PR number to merge")
    parser.add_argument("--dry-run", action="store_true", help="Check without merging")

    args = parser.parse_args()

    if not args.pr:
        parser.print_help()
        return 1

    return 0 if merge_pr(args.pr, args.dry_run) else 1


if __name__ == "__main__":
    sys.exit(main())

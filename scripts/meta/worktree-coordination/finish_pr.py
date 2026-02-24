#!/usr/bin/env python3
"""Complete PR lifecycle: merge, release claim, cleanup worktree.

MUST be run from main directory, not from a worktree. This prevents the
shell CWD invalidation issue where deleting a worktree breaks the CC's bash.

Usage:
    # From main directory:
    cd /path/to/main && python scripts/finish_pr.py --branch plan-XX --pr N

    # Or via make:
    cd /path/to/main && make finish BRANCH=plan-XX PR=N
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
    return subprocess.run(
        cmd,
        check=check,
        capture_output=capture,
        text=True,
    )


def is_in_worktree() -> bool:
    """Check if current directory is a git worktree (not main repo)."""
    git_path = Path(".git")
    if git_path.is_file():
        # .git is a file pointing to the main repo = we're in a worktree
        return True
    elif git_path.is_dir():
        # .git is a directory = we're in the main repo
        return False
    else:
        # Not in a git repo at all
        return False


def get_main_repo_root() -> Path:
    """Get the main repo root directory."""
    result = run_cmd(["git", "rev-parse", "--git-common-dir"], check=False)
    if result.returncode != 0:
        return Path.cwd()
    git_common = Path(result.stdout.strip())
    return git_common.parent


def check_pr_ci_status(pr_number: int) -> tuple[bool, str]:
    """Check if PR's CI checks have passed."""
    result = run_cmd(
        ["gh", "pr", "view", str(pr_number), "--json", "statusCheckRollup,mergeable,state"],
        check=False,
    )
    if result.returncode != 0:
        return False, f"Failed to get PR status: {result.stderr}"

    data = json.loads(result.stdout)

    if data.get("state") == "MERGED":
        return False, "PR is already merged"

    if data.get("state") == "CLOSED":
        return False, "PR is closed"

    if data.get("mergeable") == "CONFLICTING":
        return False, "PR has merge conflicts - needs rebase"

    checks = data.get("statusCheckRollup", []) or []
    failing = [
        c.get("name", c.get("context", "unknown"))
        for c in checks
        if c.get("conclusion") == "FAILURE"
    ]
    if failing:
        return False, f"CI checks failing: {', '.join(failing)}"

    pending = [
        c.get("name", c.get("context", "unknown"))
        for c in checks
        if c.get("status") in ("IN_PROGRESS", "QUEUED", "PENDING")
        or c.get("conclusion") is None
    ]
    if pending:
        return False, f"CI checks still running: {', '.join(pending)}"

    return True, "OK"


def merge_pr(pr_number: int) -> tuple[bool, str]:
    """Merge a PR via GitHub CLI."""
    result = run_cmd(
        ["gh", "pr", "merge", str(pr_number), "--squash", "--delete-branch"],
        check=False,
    )
    if result.returncode != 0:
        return False, result.stderr or result.stdout
    return True, "Merged"


def release_claim(branch: str) -> bool:
    """Release any claim for this branch."""
    result = run_cmd(
        ["python", "scripts/check_claims.py", "--release", "--id", branch, "--force"],
        check=False,
    )
    return result.returncode == 0



def extract_plan_number(branch: str) -> str | None:
    """Extract plan number from branch name like 'plan-113-model-access'."""
    if not branch.startswith("plan-"):
        return None
    parts = branch.split("-")
    if len(parts) >= 2 and parts[1].isdigit():
        return parts[1]
    return None


def complete_plan(plan_number: str) -> tuple[bool, str]:
    """Mark a plan as complete using complete_plan.py."""
    result = run_cmd(
        ["python", "scripts/complete_plan.py", "--plan", plan_number],
        check=False,
    )
    if result.returncode != 0:
        return False, result.stderr or result.stdout or "Unknown error"
    return True, "Completed"

def find_worktree_path(branch: str) -> Path | None:
    """Find the worktree path for a branch."""
    result = run_cmd(["git", "worktree", "list", "--porcelain"], check=False)
    if result.returncode != 0:
        return None

    current_path = None
    for line in result.stdout.strip().split("\n"):
        if line.startswith("worktree "):
            current_path = Path(line[9:])
        elif line.startswith("branch refs/heads/"):
            worktree_branch = line[18:]
            if worktree_branch == branch:
                return current_path
    return None


def remove_worktree(worktree_path: Path) -> tuple[bool, str]:
    """Remove a worktree."""
    result = run_cmd(
        ["git", "worktree", "remove", str(worktree_path)],
        check=False,
    )
    if result.returncode != 0:
        # Try with --force for untracked files
        result = run_cmd(
            ["git", "worktree", "remove", "--force", str(worktree_path)],
            check=False,
        )
        if result.returncode != 0:
            return False, result.stderr or result.stdout
    return True, "Removed"


def check_worktree_clean(worktree_path: Path) -> tuple[bool, str]:
    """Check if worktree has uncommitted changes."""
    result = run_cmd(
        ["git", "-C", str(worktree_path), "status", "--porcelain"],
        check=False,
    )
    if result.returncode != 0:
        return True, ""  # Can't check, assume clean
    if result.stdout.strip():
        return False, result.stdout.strip()
    return True, ""


def finish_pr(branch: str, pr_number: int, check_ci: bool = False) -> bool:
    """Complete the full PR lifecycle."""

    # Step 0: Verify we're in main, not a worktree
    if is_in_worktree():
        print("❌ ERROR: Cannot run from a worktree!")
        print()
        print("Running 'finish' from a worktree will break your shell when the")
        print("worktree is deleted (CWD becomes invalid).")
        print()
        print("Run from main instead:")
        main_root = get_main_repo_root()
        print(f"  cd {main_root} && make finish BRANCH={branch} PR={pr_number}")
        return False

    print(f"🏁 Finishing PR #{pr_number} (branch: {branch})")
    print()

    # Step 1: Check CI status (disabled by default - CI is optional)
    if check_ci:
        print("📋 Checking CI status...")
        ci_ok, ci_msg = check_pr_ci_status(pr_number)
        if not ci_ok:
            print(f"❌ CI check failed: {ci_msg}")
            return False
        print("✅ CI checks passed")

    # Step 2: Remove worktree FIRST (before merge, so branch can be deleted)
    worktree_path = find_worktree_path(branch)
    if worktree_path:
        # Check for uncommitted changes
        clean, changes = check_worktree_clean(worktree_path)
        if not clean:
            print(f"❌ Worktree has uncommitted changes:")
            for line in changes.split("\n")[:5]:
                print(f"   {line}")
            print()
            print("Commit or stash changes first, then retry.")
            return False

        print(f"🧹 Removing worktree at {worktree_path}...")
        # Remove session marker if present (we're the owner finishing our own work)
        session_marker = worktree_path / ".claude_session"
        if session_marker.exists():
            session_marker.unlink()
        remove_ok, remove_msg = remove_worktree(worktree_path)
        if remove_ok:
            print("✅ Worktree removed")
        else:
            print(f"⚠️  Could not remove worktree: {remove_msg}")
            print(f"   Remove manually: git worktree remove --force {worktree_path}")
            print("   Then retry: make finish ...")
            return False

    # Step 3: Merge PR (now safe - branch not in use by worktree)
    print(f"🔀 Merging PR #{pr_number}...")
    merge_ok, merge_msg = merge_pr(pr_number)
    if not merge_ok:
        print(f"❌ Merge failed: {merge_msg}")
        return False
    print("✅ PR merged")

    # Step 4: Mark plan as complete (if this is a plan branch)
    plan_num = extract_plan_number(branch)
    if plan_num:
        print(f"📋 Marking Plan #{plan_num} as complete...")
        complete_ok, complete_msg = complete_plan(plan_num)
        if complete_ok:
            print(f"✅ Plan #{plan_num} marked complete")
        else:
            print(f"⚠️  Could not mark plan complete: {complete_msg}")
            print("   Run manually: python scripts/complete_plan.py --plan", plan_num)

    # Step 5: Release claim
    print(f"🔓 Releasing claim for {branch}...")
    if release_claim(branch):
        print("✅ Claim released")
    else:
        print("⚠️  No claim to release (or already released)")

    # Step 6: Pull main
    print("📥 Pulling latest main...")
    run_cmd(["git", "pull", "--rebase", "origin", "main"], check=False)
    print("✅ Main updated")

    print()
    print(f"🎉 Done! PR #{pr_number} is complete.")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Complete PR lifecycle: merge, release claim, cleanup worktree.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--branch", "-b",
        required=True,
        help="Branch name (e.g., plan-98-robust-worktree)"
    )
    parser.add_argument(
        "--pr", "-p",
        type=int,
        required=True,
        help="PR number"
    )
    parser.add_argument(
        "--check-ci",
        action="store_true",
        help="Enable CI status check before merge (disabled by default)"
    )

    args = parser.parse_args()

    success = finish_pr(args.branch, args.pr, args.check_ci)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())

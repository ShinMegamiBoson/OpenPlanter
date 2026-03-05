#!/usr/bin/env python3
"""Meta-process status aggregator for Claude Code coordination.

Gathers claims, PRs, plan progress, and worktree status into a single
view. Claude Code reads this output and provides analysis/recommendations.

Usage:
    python scripts/meta_status.py          # Full status
    python scripts/meta_status.py --brief  # One-line summary
"""

import argparse
import subprocess
import sys
import yaml
from datetime import datetime, timezone
from pathlib import Path


def run_cmd(cmd: list[str], cwd: str | None = None) -> tuple[bool, str]:
    """Run command and return (success, output)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            env={**subprocess.os.environ, "GIT_CONFIG_NOSYSTEM": "1"},
        )
        return result.returncode == 0, result.stdout.strip()
    except Exception as e:
        return False, str(e)


def get_git_toplevel() -> Path | None:
    """Get the top-level git directory (main repo, not worktree)."""
    success, output = run_cmd(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"])
    if success and output:
        # --git-common-dir returns path like /repo/.git for main, /repo/.git for worktrees
        git_dir = Path(output)
        if git_dir.name == ".git":
            return git_dir.parent
    return None


def get_claims() -> list[dict]:
    """Get active claims from .claude/active-work.yaml.

    Always reads from the main repo (not worktree) to ensure consistent view.
    """
    # Try to find main repo first
    main_repo = get_git_toplevel()
    if main_repo:
        claims_file = main_repo / ".claude" / "active-work.yaml"
    else:
        # Fallback to relative path
        claims_file = Path(".claude/active-work.yaml")

    if not claims_file.exists():
        return []

    try:
        with open(claims_file) as f:
            data = yaml.safe_load(f) or {}
        return data.get("claims", [])
    except Exception:
        return []


def get_open_prs() -> list[dict]:
    """Get open PRs from GitHub."""
    success, output = run_cmd([
        "gh", "pr", "list", 
        "--state", "open",
        "--json", "number,title,headRefName,createdAt,author"
    ])
    
    if not success or not output:
        return []
    
    try:
        import json
        return json.loads(output)
    except Exception:
        return []


def get_plan_progress() -> dict:
    """Get plan completion statistics."""
    plans_dir = Path("docs/plans")
    if not plans_dir.exists():
        return {"total": 0, "complete": 0, "in_progress": 0, "planned": 0}
    
    stats = {"total": 0, "complete": 0, "in_progress": 0, "planned": 0, "plans": []}
    
    for plan_file in sorted(plans_dir.glob("[0-9]*_*.md")):
        content = plan_file.read_text()
        plan_num = plan_file.name.split("_")[0]
        
        stats["total"] += 1
        
        if "✅ Complete" in content:
            stats["complete"] += 1
            status = "complete"
        elif "🚧 In Progress" in content:
            stats["in_progress"] += 1
            status = "in_progress"
        elif "📋 Planned" in content:
            stats["planned"] += 1
            status = "planned"
        else:
            status = "unknown"
        
        # Extract title from first heading
        title = "Unknown"
        for line in content.split("\n"):
            if line.startswith("# "):
                title = line[2:].strip()
                break
        
        stats["plans"].append({
            "number": plan_num,
            "title": title,
            "status": status,
            "file": plan_file.name,
        })
    
    return stats


def extract_worktree_dir_name(path: str) -> str | None:
    """Extract the directory name from a worktree path.

    For /path/to/repo/worktrees/plan-91-foo, returns 'plan-91-foo'.
    For main repo path, returns None.
    """
    if "/worktrees/" in path:
        return path.split("/worktrees/")[-1]
    return None


def extract_plan_from_name(name: str) -> str | None:
    """Extract plan number from a branch or directory name.

    'plan-91-foo' -> '91'
    'temporal-network-viz' -> None
    """
    import re
    match = re.match(r"plan-(\d+)", name)
    return match.group(1) if match else None


def get_worktrees() -> list[dict]:
    """Get git worktree information.

    Returns list of dicts with:
        - path: Full filesystem path
        - branch: Git branch name
        - dir_name: Worktree directory name (None for main repo)
        - dir_plan: Plan number extracted from directory name
        - branch_plan: Plan number extracted from branch name
    """
    success, output = run_cmd(["git", "worktree", "list", "--porcelain"])
    if not success:
        return []

    worktrees = []
    current: dict = {}

    for line in output.split("\n"):
        if line.startswith("worktree "):
            if current:
                worktrees.append(current)
            path = line[9:]
            dir_name = extract_worktree_dir_name(path)
            current = {
                "path": path,
                "dir_name": dir_name,
                "dir_plan": extract_plan_from_name(dir_name) if dir_name else None,
            }
        elif line.startswith("HEAD "):
            current["head"] = line[5:]
        elif line.startswith("branch "):
            branch = line[7:].replace("refs/heads/", "")
            current["branch"] = branch
            current["branch_plan"] = extract_plan_from_name(branch)
        elif line == "bare":
            current["bare"] = True
        elif line == "detached":
            current["detached"] = True

    if current:
        worktrees.append(current)

    return worktrees


def get_current_branch() -> str:
    """Get the current branch name (to identify self)."""
    success, output = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    return output if success else ""


def remote_branch_exists(branch: str) -> bool:
    """Check if a branch exists on the remote."""
    success, output = run_cmd(["git", "ls-remote", "--heads", "origin", branch])
    return success and bool(output.strip())


def get_my_identity() -> dict:
    """Determine the current CC instance's identity for ownership checks.

    Returns a dict with:
      - branch: Current git branch
      - is_main: True if on main branch (coordination mode, not implementation)
      - cc_id: The CC-ID if we're in a worktree with a claim
    """
    branch = get_current_branch()
    is_main = branch == "main"

    # Try to find matching claim for current branch
    claims = get_claims()
    cc_id = None
    for claim in claims:
        if claim.get("branch") == branch:
            cc_id = claim.get("cc_id")
            break

    return {"branch": branch, "is_main": is_main, "cc_id": cc_id}


def get_recent_commits(limit: int = 5) -> list[dict]:
    """Get recent commits on main."""
    success, output = run_cmd([
        "git", "log", 
        "-n", str(limit),
        "--format=%H|%s|%ar|%an",
        "main"
    ])
    
    if not success:
        return []
    
    commits = []
    for line in output.split("\n"):
        if "|" in line:
            parts = line.split("|")
            if len(parts) >= 4:
                commits.append({
                    "hash": parts[0][:7],
                    "message": parts[1],
                    "when": parts[2],
                    "author": parts[3],
                })
    
    return commits


def get_review_status() -> list[dict]:
    """Get PR review status from CLAUDE.md Awaiting Review table."""
    import re
    claude_md = Path("CLAUDE.md")
    if not claude_md.exists():
        return []

    try:
        content = claude_md.read_text()
        # Find the Awaiting Review table
        match = re.search(
            r"\*\*Awaiting Review:\*\*.*?\n\|.*?\n\|[-|\s]+\n((?:\|.*?\n)*)",
            content,
            re.DOTALL
        )
        if not match:
            return []

        reviews = []
        for line in match.group(1).strip().split("\n"):
            if not line.strip() or not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) >= 4:
                pr_num = cells[0].replace("#", "").strip()
                if not pr_num or pr_num == "-":
                    continue
                reviews.append({
                    "pr": pr_num,
                    "title": cells[1] if len(cells) > 1 else "",
                    "reviewer": cells[2] if len(cells) > 2 else "",
                    "started": cells[3] if len(cells) > 3 else "",
                    "status": cells[4] if len(cells) > 4 else "Awaiting",
                })
        return reviews
    except Exception:
        return []


def format_time_ago(iso_time: str) -> str:
    """Convert ISO timestamp to 'X ago' format."""
    try:
        dt = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = now - dt
        
        if delta.days > 0:
            return f"{delta.days}d ago"
        elif delta.seconds >= 3600:
            return f"{delta.seconds // 3600}h ago"
        elif delta.seconds >= 60:
            return f"{delta.seconds // 60}m ago"
        else:
            return "just now"
    except Exception:
        return iso_time


def identify_issues(claims: list, prs: list, plans: dict, worktrees: list, my_identity: dict | None = None) -> list[str]:
    """Identify potential issues needing attention.

    Args:
        claims: List of active claims
        prs: List of open PRs
        plans: Plan progress dict
        worktrees: List of worktree info dicts
        my_identity: Current CC's identity (from get_my_identity())
    """
    import re
    issues = []

    # Build lookup sets for claims (both cc_id and branch can be used)
    claimed_cc_ids = {claim.get("cc_id") for claim in claims}
    claimed_plans = {str(claim.get("plan")) for claim in claims if claim.get("plan")}

    # Build mappings for ownership checks
    # Map worktree dir_name -> claim owner cc_id
    worktree_to_owner: dict[str, str] = {}
    for claim in claims:
        cc_id = claim.get("cc_id", "")
        # The cc_id often matches the worktree dir name
        if cc_id:
            worktree_to_owner[cc_id] = cc_id
        # Also check worktree_path if present
        wt_path = claim.get("worktree_path", "")
        if wt_path:
            from pathlib import Path
            dir_name = Path(wt_path).name
            worktree_to_owner[dir_name] = cc_id

    # Stale claims (> 4 hours with no corresponding PR)
    for claim in claims:
        claimed_at = claim.get("claimed_at", "")
        plan_num = claim.get("plan")

        # Check if there's a PR for this plan
        has_pr = any(
            f"Plan #{plan_num}" in pr.get("title", "") or
            f"plan-{plan_num}" in pr.get("headRefName", "")
            for pr in prs
        )

        if not has_pr and claimed_at:
            try:
                dt = datetime.fromisoformat(claimed_at.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                hours = (now - dt).total_seconds() / 3600
                if hours > 4:
                    issues.append(f"Claim on Plan #{plan_num} is {hours:.0f}h old with no PR")
            except Exception:
                pass

    # PRs that might conflict (same plan number)
    plan_prs: dict[str, list] = {}
    for pr in prs:
        title = pr.get("title", "")
        branch = pr.get("headRefName", "")

        # Extract plan number
        match = re.search(r"Plan #(\d+)", title) or re.search(r"plan-(\d+)", branch)
        if match:
            plan_num = match.group(1)
            if plan_num not in plan_prs:
                plan_prs[plan_num] = []
            plan_prs[plan_num].append(pr.get("number"))

    for plan_num, pr_nums in plan_prs.items():
        if len(pr_nums) > 1:
            issues.append(f"Plan #{plan_num} has multiple PRs: {pr_nums} - may conflict")

    # Worktree issues: orphaned and directory/branch mismatches
    for wt in worktrees:
        dir_name = wt.get("dir_name")
        branch = wt.get("branch", "")
        dir_plan = wt.get("dir_plan")
        branch_plan = wt.get("branch_plan")

        # Skip main worktree (has no dir_name)
        if dir_name is None:
            continue

        # Check for directory/branch plan mismatch (different plan numbers)
        if dir_plan and branch_plan and dir_plan != branch_plan:
            issues.append(
                f"Worktree mismatch: dir '{dir_name}' (Plan #{dir_plan}) "
                f"contains branch '{branch}' (Plan #{branch_plan}) - reused worktree?"
            )

        # Check for merged worktrees (detached HEAD or remote branch deleted)
        is_detached = wt.get("detached", False)
        remote_exists = remote_branch_exists(branch) if branch and not is_detached else True

        if is_detached or not remote_exists:
            reason = "detached HEAD" if is_detached else "branch deleted from remote (likely merged)"

            # Check ownership - only safe to cleanup if YOU own it
            owner = worktree_to_owner.get(dir_name) or worktree_to_owner.get(branch, "")
            my_cc_id = my_identity.get("cc_id") if my_identity else None
            my_branch = my_identity.get("branch") if my_identity else None

            # Determine if this is "yours"
            is_yours = (
                (owner and my_cc_id and owner == my_cc_id) or
                (owner and my_branch and owner == my_branch) or
                (not owner and my_branch == "main")  # Unclaimed worktrees can be cleaned from main
            )

            if is_yours or not owner:
                # Safe to cleanup - you own it or it's unclaimed
                issues.append(
                    f"🧹 Merged worktree: '{dir_name}' ({reason}) - safe to cleanup with: "
                    f"make worktree-remove BRANCH={dir_name}"
                )
            else:
                # NOT yours - leave it alone
                issues.append(
                    f"🧹 Merged worktree: '{dir_name}' ({reason})\n"
                    f"      Owner: {owner} (NOT YOURS) - leave alone, owner should cleanup"
                )
            continue  # Skip other orphan checks for merged worktrees

        # Check for orphaned worktrees
        # A worktree is NOT orphaned if ANY of these are true:
        # 1. Branch has an open PR
        # 2. cc_id matches dir_name (claim by directory name)
        # 3. cc_id matches branch (claim by branch name)
        # 4. Plan number has an active claim
        has_pr = any(pr.get("headRefName") == branch for pr in prs)
        has_claim_by_dir = dir_name in claimed_cc_ids
        has_claim_by_branch = branch in claimed_cc_ids
        has_claim_by_plan = (
            (dir_plan and dir_plan in claimed_plans) or
            (branch_plan and branch_plan in claimed_plans)
        )

        if not has_pr and not has_claim_by_dir and not has_claim_by_branch and not has_claim_by_plan:
            issues.append(
                f"Orphaned worktree: '{dir_name}' (branch: {branch}) has no PR or claim"
            )

    # Old PRs (> 24h)
    for pr in prs:
        created = pr.get("createdAt", "")
        if created:
            try:
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                hours = (now - dt).total_seconds() / 3600
                if hours > 24:
                    issues.append(f"PR #{pr.get('number')} is {hours:.0f}h old - needs merge or review?")
            except Exception:
                pass

    # Count merged/orphaned worktrees and suggest batch cleanup
    merged_count = sum(1 for i in issues if "Merged worktree:" in i or "Orphaned worktree:" in i)
    if merged_count > 1:
        issues.append(
            f"💡 Multiple orphaned worktrees ({merged_count}) - run 'make clean-worktrees' for batch cleanup"
        )

    return issues


def print_status(brief: bool = False) -> None:
    """Print meta-process status."""
    claims = get_claims()
    prs = get_open_prs()
    reviews = get_review_status()
    plans = get_plan_progress()
    worktrees = get_worktrees()
    commits = get_recent_commits()
    my_identity = get_my_identity()
    issues = identify_issues(claims, prs, plans, worktrees, my_identity)

    if brief:
        # One-line summary
        in_review = len([r for r in reviews if r.get("status") == "In Review"])
        print(f"Claims: {len(claims)} | PRs: {len(prs)} | Reviews: {in_review} active | Plans: {plans['complete']}/{plans['total']} | Issues: {len(issues)}")
        return

    print("=" * 60)
    print("META-PROCESS STATUS")
    print("=" * 60)
    print()

    # Show current identity
    if my_identity["is_main"]:
        print("📍 You are on: main (coordination mode - read/review only)")
    else:
        print(f"📍 You are on: {my_identity['branch']}")
    print()
    
    # Claims
    print("## Active Claims")
    if claims:
        print()
        print("| CC-ID | Plan | Task | Yours? |")
        print("|-------|------|------|--------|")
        for claim in claims:
            cc_id = claim.get("cc_id", "-")
            plan = claim.get("plan", "-")
            task = claim.get("task", "-")[:35]

            # Determine if this claim is "ours"
            is_mine = cc_id == my_identity["cc_id"] or cc_id == my_identity["branch"]
            ownership = "✓ YOURS" if is_mine else "NOT YOURS"

            print(f"| {cc_id[:20]} | #{plan} | {task} | {ownership} |")
    else:
        print("No active claims.")
    print()
    
    # Open PRs
    print("## Open PRs")
    if prs:
        print()
        print("| # | Title | Owner | Yours? |")
        print("|---|-------|-------|--------|")
        for pr in prs:
            num = pr.get("number", "?")
            title = pr.get("title", "?")[:40]
            author = pr.get("author", {})
            owner = author.get("login", "?") if isinstance(author, dict) else "?"
            branch = pr.get("headRefName", "")

            # Determine if this PR is "ours"
            is_mine = branch == my_identity["branch"]
            ownership = "✓ YOURS" if is_mine else "NOT YOURS"

            print(f"| {num} | {title} | {owner} | {ownership} |")
    else:
        print("No open PRs.")
    print()

    # Review Status
    print("## Review Status")
    if reviews:
        print()
        print("| PR | Title | Reviewer | Status |")
        print("|----|-------|----------|--------|")
        for r in reviews:
            pr_num = r.get("pr", "?")
            title = r.get("title", "?")[:35]
            reviewer = r.get("reviewer", "-") or "-"
            status = r.get("status", "Awaiting") or "Awaiting"
            print(f"| #{pr_num} | {title} | {reviewer} | {status} |")
    else:
        print("No PRs in review queue.")
    print()

    # Plan Progress
    print("## Plan Progress")
    print()
    total = plans["total"]
    complete = plans["complete"]
    pct = (complete / total * 100) if total > 0 else 0
    bar_len = 30
    filled = int(bar_len * pct / 100)
    bar = "█" * filled + "░" * (bar_len - filled)
    print(f"[{bar}] {pct:.0f}% ({complete}/{total})")
    print()
    print(f"- Complete: {plans['complete']}")
    print(f"- In Progress: {plans['in_progress']}")
    print(f"- Planned: {plans['planned']}")
    print()
    
    # In-progress plans detail
    in_progress = [p for p in plans.get("plans", []) if p["status"] == "in_progress"]
    if in_progress:
        print("**In Progress:**")
        for p in in_progress:
            print(f"  - Plan #{p['number']}: {p['title']}")
        print()
    
    # Worktrees
    print("## Worktrees")
    if worktrees:
        print()
        for wt in worktrees:
            dir_name = wt.get("dir_name")
            branch = wt.get("branch", "detached")
            dir_plan = wt.get("dir_plan")
            branch_plan = wt.get("branch_plan")

            # Main worktree (no dir_name)
            if dir_name is None:
                print(f"  - main")
                continue

            # Check for mismatch
            if dir_plan and branch_plan and dir_plan != branch_plan:
                print(f"  - {dir_name} -> {branch} ⚠️ MISMATCH")
            elif dir_name != branch:
                print(f"  - {dir_name} -> {branch}")
            else:
                print(f"  - {branch}")
    print()
    
    # Recent commits
    print("## Recent Commits (main)")
    if commits:
        print()
        for c in commits:
            print(f"  - {c['hash']} {c['message'][:50]} ({c['when']})")
    print()
    
    # Issues
    print("## Needs Attention")
    if issues:
        print()
        for issue in issues:
            print(f"  ⚠️  {issue}")
    else:
        print("No issues detected.")
    print()
    
    print("=" * 60)
    print("Run 'python scripts/meta_status.py --brief' for one-line summary")


def main() -> None:
    parser = argparse.ArgumentParser(description="Meta-process status for CC coordination")
    parser.add_argument("--brief", action="store_true", help="One-line summary")
    args = parser.parse_args()
    
    print_status(brief=args.brief)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Parse plan files for enforcement hooks.

Extracts structured data from plan markdown files:
- Files Affected section (what files the plan declares it will touch)
- References Reviewed section (what code/docs were reviewed before planning)

Usage:
    # Get active plan's file scope
    python scripts/parse_plan.py --files-affected

    # Get active plan's references
    python scripts/parse_plan.py --references-reviewed

    # Check if a file is in scope
    python scripts/parse_plan.py --check-file src/world/ledger.py

    # Parse a specific plan file
    python scripts/parse_plan.py --plan 15 --files-affected

    # JSON output for hooks
    python scripts/parse_plan.py --json --files-affected
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


def get_main_repo_root() -> Path:
    """Get the main repo root (not worktree)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
        )
        git_dir = Path(result.stdout.strip())
        return git_dir.parent
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd()


def get_current_branch() -> str:
    """Get current git branch name."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def get_plan_number_from_branch(branch: str) -> int | None:
    """Extract plan number from branch name like 'plan-15-feature'."""
    match = re.match(r"plan-(\d+)", branch)
    if match:
        return int(match.group(1))
    return None


def get_active_plan_number() -> int | None:
    """Get the plan number for the current work context.

    Tries in order:
    1. Branch name (plan-NN-xxx)
    2. Active claim from .claude/active-work.yaml
    """
    # Try branch name first
    branch = get_current_branch()
    plan_num = get_plan_number_from_branch(branch)
    if plan_num:
        return plan_num

    # Try active claims
    main_root = get_main_repo_root()
    claims_file = main_root / ".claude/active-work.yaml"

    if claims_file.exists():
        try:
            import yaml
            with open(claims_file) as f:
                data = yaml.safe_load(f) or {}

            claims = data.get("claims", [])
            for claim in claims:
                if claim.get("cc_id") == branch and claim.get("plan"):
                    return claim["plan"]
        except Exception:
            pass

    return None


def find_plan_file(plan_number: int) -> Path | None:
    """Find the plan file for a given plan number.

    Checks current worktree first, then main repo.
    This allows worktree-specific plan updates to be found before they're merged.
    """
    # Check locations in order of preference - worktree first
    locations = [
        Path.cwd() / "docs/plans",  # Current worktree (may have uncommitted changes)
        get_main_repo_root() / "docs/plans",  # Main repo (shared)
    ]

    # Dedupe while preserving order
    seen = set()
    unique_locations = []
    for loc in locations:
        resolved = loc.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique_locations.append(loc)

    # Try both formats: 01_name.md and 1_name.md
    for plans_dir in unique_locations:
        if not plans_dir.exists():
            continue
        for pattern in [f"{plan_number:02d}_*.md", f"{plan_number}_*.md"]:
            matches = list(plans_dir.glob(pattern))
            if matches:
                return matches[0]

    return None


def parse_files_affected(content: str) -> list[dict[str, Any]]:
    """Parse the Files Affected section from plan content.

    Expected format:
    ## Files Affected
    - src/world/executor.py (modify)
    - src/world/rate_limiter.py (create)
    - tests/test_rate_limiter.py (create)

    Returns list of dicts with 'path' and 'action' keys.
    """
    files = []

    # Find Files Affected section
    match = re.search(
        r"##\s*Files?\s*Affected\s*\n(.*?)(?=\n##|\n---|\Z)",
        content,
        re.IGNORECASE | re.DOTALL
    )

    if not match:
        return files

    section = match.group(1)

    # Parse each line
    for line in section.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Remove leading bullet/dash
        line = re.sub(r"^[-*]\s*", "", line)

        # Extract path and action
        # Format: path (action) or just path
        path_match = re.match(r"([^\s(]+)\s*(?:\((\w+)\))?", line)
        if path_match:
            path = path_match.group(1).strip()
            action = path_match.group(2) or "modify"

            # Skip comments and empty paths
            if path and not path.startswith("#"):
                files.append({
                    "path": path,
                    "action": action.lower(),
                })

    return files


def parse_references_reviewed(content: str) -> list[dict[str, Any]]:
    """Parse the References Reviewed section from plan content.

    Expected format:
    ## References Reviewed
    - src/world/executor.py:45-89 - existing action handling
    - docs/architecture/current/actions.md - action design

    Returns list of dicts with 'path', 'lines', and 'description' keys.
    """
    refs = []

    # Find References Reviewed section
    match = re.search(
        r"##\s*References?\s*Reviewed\s*\n(.*?)(?=\n##|\n---|\Z)",
        content,
        re.IGNORECASE | re.DOTALL
    )

    if not match:
        return refs

    section = match.group(1)

    # Parse each line
    for line in section.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Remove leading bullet/dash
        line = re.sub(r"^[-*]\s*", "", line)

        # Extract path, optional line range, and description
        # Format: path:start-end - description
        #     or: path - description
        #     or: path
        ref_match = re.match(
            r"([^\s:]+)(?::(\d+)(?:-(\d+))?)?(?:\s*[-–]\s*(.+))?",
            line
        )

        if ref_match:
            path = ref_match.group(1).strip()
            start_line = ref_match.group(2)
            end_line = ref_match.group(3)
            description = ref_match.group(4) or ""

            if path and not path.startswith("#"):
                ref_entry: dict[str, Any] = {"path": path}

                if start_line:
                    ref_entry["lines"] = {
                        "start": int(start_line),
                        "end": int(end_line) if end_line else int(start_line),
                    }

                if description:
                    ref_entry["description"] = description.strip()

                refs.append(ref_entry)

    return refs


def check_file_in_scope(file_path: str, files_affected: list[dict[str, Any]]) -> tuple[bool, str]:
    """Check if a file is in the plan's declared scope.

    Returns (in_scope, reason).
    """
    # Normalize the file path
    normalized = str(Path(file_path))

    for entry in files_affected:
        declared_path = str(Path(entry["path"]))

        # Exact match
        if normalized == declared_path:
            return True, f"Declared as ({entry['action']})"

        # Check if declared path is a directory prefix
        if normalized.startswith(declared_path + "/"):
            return True, f"Under declared directory {declared_path}"

    return False, "Not in Files Affected"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parse plan files for enforcement hooks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--plan", "-p",
        type=int,
        help="Plan number (default: detect from branch/claims)"
    )
    parser.add_argument(
        "--files-affected", "-f",
        action="store_true",
        help="Output the Files Affected section"
    )
    parser.add_argument(
        "--references-reviewed", "-r",
        action="store_true",
        help="Output the References Reviewed section"
    )
    parser.add_argument(
        "--check-file", "-c",
        type=str,
        help="Check if a file is in the plan's scope"
    )
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output as JSON (for hooks)"
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress informational messages"
    )

    args = parser.parse_args()

    # Determine plan number
    plan_number = args.plan or get_active_plan_number()

    if not plan_number:
        if not args.quiet:
            print("Could not determine active plan.", file=sys.stderr)
            print("Use --plan N or work from a plan-NN-xxx branch.", file=sys.stderr)
        if args.json:
            print(json.dumps({"error": "no_active_plan"}))
        return 1

    # Find plan file
    plan_file = find_plan_file(plan_number)

    if not plan_file or not plan_file.exists():
        if not args.quiet:
            print(f"Plan file not found for plan #{plan_number}", file=sys.stderr)
        if args.json:
            print(json.dumps({"error": "plan_not_found", "plan": plan_number}))
        return 1

    # Read plan content
    content = plan_file.read_text()

    # Handle --check-file
    if args.check_file:
        files_affected = parse_files_affected(content)
        in_scope, reason = check_file_in_scope(args.check_file, files_affected)

        if args.json:
            print(json.dumps({
                "file": args.check_file,
                "in_scope": in_scope,
                "reason": reason,
                "plan": plan_number,
            }))
        else:
            status = "✓ IN SCOPE" if in_scope else "✗ NOT IN SCOPE"
            print(f"{status}: {args.check_file}")
            print(f"  Reason: {reason}")
            print(f"  Plan: #{plan_number}")

        return 0 if in_scope else 2

    # Handle --files-affected
    if args.files_affected:
        files_affected = parse_files_affected(content)

        if args.json:
            print(json.dumps({
                "plan": plan_number,
                "files_affected": files_affected,
            }))
        else:
            if not files_affected:
                print(f"Plan #{plan_number}: No Files Affected section found")
                return 1

            print(f"Plan #{plan_number} - Files Affected:")
            for entry in files_affected:
                print(f"  {entry['path']} ({entry['action']})")

        return 0

    # Handle --references-reviewed
    if args.references_reviewed:
        refs = parse_references_reviewed(content)

        if args.json:
            print(json.dumps({
                "plan": plan_number,
                "references_reviewed": refs,
            }))
        else:
            if not refs:
                print(f"Plan #{plan_number}: No References Reviewed section found")
                return 1

            print(f"Plan #{plan_number} - References Reviewed:")
            for ref in refs:
                lines = ref.get("lines", {})
                line_str = f":{lines['start']}-{lines['end']}" if lines else ""
                desc = f" - {ref['description']}" if ref.get("description") else ""
                print(f"  {ref['path']}{line_str}{desc}")

        return 0

    # Default: show both
    files_affected = parse_files_affected(content)
    refs = parse_references_reviewed(content)

    if args.json:
        print(json.dumps({
            "plan": plan_number,
            "plan_file": str(plan_file),
            "files_affected": files_affected,
            "references_reviewed": refs,
        }, indent=2))
    else:
        print(f"Plan #{plan_number}: {plan_file.name}")
        print()

        print("Files Affected:")
        if files_affected:
            for entry in files_affected:
                print(f"  {entry['path']} ({entry['action']})")
        else:
            print("  (none declared)")

        print()
        print("References Reviewed:")
        if refs:
            for ref in refs:
                lines = ref.get("lines", {})
                line_str = f":{lines['start']}-{lines['end']}" if lines else ""
                desc = f" - {ref['description']}" if ref.get("description") else ""
                print(f"  {ref['path']}{line_str}{desc}")
        else:
            print("  (none declared)")

    return 0


if __name__ == "__main__":
    sys.exit(main())

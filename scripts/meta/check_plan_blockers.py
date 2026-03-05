#!/usr/bin/env python3
"""Check for stale blockers in plan files.

Validates that no plan is marked "Blocked" by a plan that is already Complete.
This prevents dependency chains from going stale when blockers are resolved.

Usage:
    python scripts/check_plan_blockers.py           # Report stale blockers
    python scripts/check_plan_blockers.py --strict  # Fail if stale blockers found
    python scripts/check_plan_blockers.py --fix     # Suggest fixes (dry-run)
    python scripts/check_plan_blockers.py --apply   # Apply fixes automatically

Exit codes:
    0 - No issues found
    1 - Stale blockers found (strict mode) or error
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


PLANS_DIR = Path("docs/plans")

# Status patterns
STATUS_COMPLETE = "Complete"
STATUS_BLOCKED = "Blocked"


@dataclass
class PlanInfo:
    """Information extracted from a plan file."""

    number: int
    title: str
    status: str
    blocked_by: list[int]
    file_path: Path

    @property
    def is_complete(self) -> bool:
        return STATUS_COMPLETE.lower() in self.status.lower()

    @property
    def is_blocked(self) -> bool:
        return STATUS_BLOCKED.lower() in self.status.lower()


def parse_plan_file(file_path: Path) -> PlanInfo | None:
    """Parse a plan file to extract status and blockers."""
    if not file_path.exists():
        return None

    content = file_path.read_text()

    # Extract plan number from filename (e.g., 07_single_id_namespace.md -> 7)
    match = re.match(r"(\d+)_", file_path.name)
    if not match:
        return None

    plan_num = int(match.group(1))

    # Extract title from first heading
    title_match = re.search(r"^#\s*(?:Gap\s*\d+[:\s]*)?(.+?)(?:\n|$)", content, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else file_path.stem

    # Extract status
    status_match = re.search(r"\*\*Status:\*\*\s*(.+?)(?:\n|$)", content)
    status = status_match.group(1).strip() if status_match else "Unknown"

    # Extract blocked by (e.g., "**Blocked By:** #6" or "**Blocked By:** #6, #7")
    blocked_by: list[int] = []
    blocked_match = re.search(r"\*\*Blocked By:\*\*\s*(.+?)(?:\n|$)", content)
    if blocked_match:
        blocked_text = blocked_match.group(1).strip()
        if blocked_text.lower() not in ("none", "-", "n/a", ""):
            # Find all #N patterns
            blockers = re.findall(r"#(\d+)", blocked_text)
            blocked_by = [int(b) for b in blockers]

    return PlanInfo(
        number=plan_num,
        title=title,
        status=status,
        blocked_by=blocked_by,
        file_path=file_path,
    )


def load_all_plans(plans_dir: Path) -> dict[int, PlanInfo]:
    """Load all plan files from the plans directory."""
    plans: dict[int, PlanInfo] = {}

    for plan_file in plans_dir.glob("[0-9]*.md"):
        plan = parse_plan_file(plan_file)
        if plan:
            plans[plan.number] = plan

    return plans


def find_stale_blockers(plans: dict[int, PlanInfo]) -> list[tuple[PlanInfo, int, PlanInfo]]:
    """Find plans that are blocked by completed plans.

    Returns list of (blocked_plan, blocker_number, blocker_plan).
    """
    stale: list[tuple[PlanInfo, int, PlanInfo]] = []

    for plan in plans.values():
        if not plan.is_blocked:
            continue

        for blocker_num in plan.blocked_by:
            if blocker_num not in plans:
                # Blocker doesn't exist - might be superseded
                continue

            blocker = plans[blocker_num]
            if blocker.is_complete:
                stale.append((plan, blocker_num, blocker))

    return stale


def suggest_new_status(plan: PlanInfo) -> str:
    """Suggest what status a plan should have if its blockers are resolved."""
    content = plan.file_path.read_text()

    # Check if plan has design work
    if "Needs design work" in content or "*Needs design work*" in content:
        return "Needs Plan"

    # Check if plan has implementation steps
    if "## Steps" in content or "## Implementation" in content or "## Plan" in content:
        # Has steps defined - could be "Planned"
        return "Planned"

    # Default to needs plan
    return "Needs Plan"


def update_plan_status(plan: PlanInfo, new_status: str) -> None:
    """Update a plan file's status."""
    content = plan.file_path.read_text()

    # Status emoji mapping
    status_emoji = {
        "Planned": "📋",
        "In Progress": "🚧",
        "Blocked": "⏸️",
        "Needs Plan": "❌",
        "Complete": "✅",
    }

    emoji = status_emoji.get(new_status, "❓")
    new_status_line = f"**Status:** {emoji} {new_status}"

    # Replace the status line
    updated = re.sub(
        r"\*\*Status:\*\*\s*.+?(?=\n)",
        new_status_line,
        content,
    )

    # Clear the Blocked By field since we're unblocking
    updated = re.sub(
        r"\*\*Blocked By:\*\*\s*.+?(?=\n)",
        "**Blocked By:** None",
        updated,
    )

    plan.file_path.write_text(updated)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check for stale blockers in plan files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/check_plan_blockers.py           # Report only
    python scripts/check_plan_blockers.py --strict  # Fail if issues found
    python scripts/check_plan_blockers.py --fix     # Show suggested fixes
    python scripts/check_plan_blockers.py --apply   # Apply fixes
        """,
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with error if stale blockers found",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Show suggested fixes (dry-run)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply fixes automatically",
    )
    parser.add_argument(
        "--plans-dir",
        type=Path,
        default=PLANS_DIR,
        help=f"Plans directory (default: {PLANS_DIR})",
    )

    args = parser.parse_args()

    if not args.plans_dir.exists():
        print(f"ERROR: Plans directory not found: {args.plans_dir}")
        return 1

    # Load all plans
    plans = load_all_plans(args.plans_dir)
    print(f"Loaded {len(plans)} plan files\n")

    # Find stale blockers
    stale = find_stale_blockers(plans)

    if not stale:
        print("No stale blockers found.")
        return 0

    # Report stale blockers
    print("=" * 70)
    print("STALE BLOCKERS FOUND")
    print("=" * 70)
    print()
    print("These plans are marked 'Blocked' but their blockers are Complete:\n")

    for blocked_plan, blocker_num, blocker_plan in stale:
        print(f"  Plan #{blocked_plan.number}: {blocked_plan.title}")
        print(f"    Status: {blocked_plan.status}")
        print(f"    Blocked by: #{blocker_num} ({blocker_plan.title})")
        print(f"    Blocker status: {blocker_plan.status}")

        if args.fix or args.apply:
            suggested = suggest_new_status(blocked_plan)
            print(f"    Suggested new status: {suggested}")

        print()

    # Show summary
    print("-" * 70)
    print(f"Total stale blockers: {len(stale)}")
    print()

    # Apply fixes if requested
    if args.apply:
        print("Applying fixes...")
        for blocked_plan, _, _ in stale:
            new_status = suggest_new_status(blocked_plan)
            print(f"  Plan #{blocked_plan.number}: Blocked -> {new_status}")
            update_plan_status(blocked_plan, new_status)
        print("\nFixes applied. Run 'python scripts/sync_plan_status.py --sync' to update index.")
        return 0

    if args.fix:
        print("To apply these fixes, run with --apply")
        print()

    if args.strict:
        print("FAILED: Stale blockers detected (--strict mode)")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

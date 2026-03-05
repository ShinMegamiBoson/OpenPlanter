#!/usr/bin/env python3
"""Enforce plan completion requirements.

Mandatory script for marking plans as complete. Runs verification tests
and records evidence before updating plan status.

Usage:
    # Complete a plan (runs tests, records evidence, updates status)
    python scripts/complete_plan.py --plan 35

    # Dry run - check without updating
    python scripts/complete_plan.py --plan 35 --dry-run

    # Skip all E2E tests (for documentation-only plans)
    python scripts/complete_plan.py --plan 35 --skip-e2e

    # Skip only real E2E tests (actual LLM calls) but run smoke tests
    python scripts/complete_plan.py --plan 35 --skip-real-e2e

    # Re-verify an already-complete plan
    python scripts/complete_plan.py --plan 35 --force

    # Complete a plan that requires human review
    # (after manual verification of checklist items)
    python scripts/complete_plan.py --plan 40 --human-verified

Plans with a "## Human Review Required" section cannot be completed
without the --human-verified flag. This ensures humans verify things
that automated tests cannot check (visual correctness, UX, etc.).

See meta/patterns/17_verification-enforcement.md for the full pattern.
"""

import argparse
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Plan #136: Timeout for test subprocess calls to prevent hanging forever
TEST_TIMEOUT_SECONDS = 300  # 5 minutes


def find_plan_file(plan_number: int, plans_dir: Path) -> Path | None:
    """Find a plan file by number."""
    patterns = [
        f"{plan_number:02d}_*.md",
        f"{plan_number}_*.md",
    ]
    for pattern in patterns:
        matches = list(plans_dir.glob(pattern))
        if matches:
            return matches[0]
    return None


def get_plan_status(plan_file: Path) -> str:
    """Extract current status from plan file."""
    content = plan_file.read_text()
    match = re.search(r"\*\*Status:\*\*\s*(.+)", content)
    return match.group(1).strip() if match else "Unknown"


def get_human_review_section(plan_file: Path) -> str | None:
    """Extract the Human Review Required section from plan file.

    Returns the section content if present, None otherwise.
    """
    content = plan_file.read_text()

    # Look for ## Human Review Required section
    match = re.search(
        r"##\s*Human Review Required\s*\n(.*?)(?=\n##|\Z)",
        content,
        re.DOTALL | re.IGNORECASE
    )

    if match:
        return match.group(1).strip()
    return None


def print_human_review_instructions(
    plan_number: int,
    section_content: str,
    plan_file: Path,
) -> None:
    """Print human review instructions and checklist."""
    print(f"\n{'='*60}")
    print("HUMAN REVIEW REQUIRED")
    print(f"{'='*60}")
    print(f"\nPlan #{plan_number} requires manual verification before completion.")
    print(f"\nFrom {plan_file.name}:")
    print(f"\n{'-'*40}")
    print(section_content)
    print(f"{'-'*40}")
    print(f"\nAfter verifying all items above, run:")
    print(f"\n  python scripts/complete_plan.py --plan {plan_number} --human-verified")
    print(f"\nThis confirms a human has checked things automated tests cannot verify.")


def run_unit_tests(project_root: Path, verbose: bool = True) -> tuple[bool, str]:
    """Run unit/component tests (excluding E2E).

    Returns (success, summary).
    """
    if verbose:
        print("\n[1/4] Running unit tests...")

    try:
        result = subprocess.run(
            ["pytest", "tests/", "--ignore=tests/e2e/", "-v", "--tb=short"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        if verbose:
            print(f"    TIMEOUT: Tests did not complete within {TEST_TIMEOUT_SECONDS}s")
        return False, f"timeout after {TEST_TIMEOUT_SECONDS}s"

    # Extract summary from output
    output = result.stdout + result.stderr
    summary_match = re.search(r"=+ (.+ passed.*) =+", output)
    summary = summary_match.group(1) if summary_match else "unknown result"

    if verbose:
        if result.returncode == 0:
            print(f"    PASSED: {summary}")
        else:
            print(f"    FAILED: {summary}")
            print(output[-2000:])  # Last 2000 chars of output

    return result.returncode == 0, summary


def run_e2e_tests(project_root: Path, verbose: bool = True) -> tuple[bool, str]:
    """Run E2E smoke tests.

    Returns (success, summary).
    """
    e2e_dir = project_root / "tests" / "e2e"
    smoke_test = e2e_dir / "test_smoke.py"

    if not e2e_dir.exists():
        if verbose:
            print("\n[2/4] E2E smoke tests... SKIPPED (tests/e2e/ not found)")
        return True, "skipped (no e2e directory)"

    if not smoke_test.exists():
        if verbose:
            print("\n[2/4] E2E smoke tests... SKIPPED (test_smoke.py not found)")
        return True, "skipped (no smoke test)"

    if verbose:
        print("\n[2/4] Running E2E smoke tests...")

    try:
        result = subprocess.run(
            ["pytest", "tests/e2e/test_smoke.py", "-v", "--tb=short"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        if verbose:
            print(f"    TIMEOUT: Tests did not complete within {TEST_TIMEOUT_SECONDS}s")
        return False, f"timeout after {TEST_TIMEOUT_SECONDS}s"

    output = result.stdout + result.stderr

    # Extract timing
    time_match = re.search(r"in (\d+\.\d+)s", output)
    timing = time_match.group(1) if time_match else "?"

    if result.returncode == 0:
        summary = f"PASSED ({timing}s)"
    else:
        summary = f"FAILED ({timing}s)"

    if verbose:
        if result.returncode == 0:
            print(f"    PASSED ({timing}s)")
        else:
            print(f"    FAILED")
            print(output[-2000:])

    return result.returncode == 0, summary


def run_real_e2e_tests(project_root: Path, verbose: bool = True) -> tuple[bool, str]:
    """Run real E2E tests (actual LLM calls).

    Returns (success, summary).
    """
    e2e_dir = project_root / "tests" / "e2e"
    real_e2e = e2e_dir / "test_real_e2e.py"

    if not e2e_dir.exists():
        if verbose:
            print("\n[3/4] Real E2E tests... SKIPPED (tests/e2e/ not found)")
        return True, "skipped (no e2e directory)"

    if not real_e2e.exists():
        if verbose:
            print("\n[3/4] Real E2E tests... SKIPPED (test_real_e2e.py not found)")
        return True, "skipped (no real e2e test)"

    if verbose:
        print("\n[3/4] Running real E2E tests (actual LLM calls)...")

    try:
        result = subprocess.run(
            ["pytest", "tests/e2e/test_real_e2e.py", "-v", "--tb=short", "--run-external"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        if verbose:
            print(f"    TIMEOUT: Tests did not complete within {TEST_TIMEOUT_SECONDS}s")
        return False, f"timeout after {TEST_TIMEOUT_SECONDS}s"

    output = result.stdout + result.stderr

    # Extract timing
    time_match = re.search(r"in (\d+\.\d+)s", output)
    timing = time_match.group(1) if time_match else "?"

    if result.returncode == 0:
        summary = f"PASSED ({timing}s)"
    else:
        summary = f"FAILED ({timing}s)"

    if verbose:
        if result.returncode == 0:
            print(f"    PASSED ({timing}s)")
        else:
            print(f"    FAILED")
            print(output[-2000:])

    return result.returncode == 0, summary


def check_doc_coupling(project_root: Path, verbose: bool = True) -> tuple[bool, str]:
    """Check doc-code coupling.

    Returns (success, summary).
    """
    if verbose:
        print("\n[4/4] Checking doc-code coupling...")

    try:
        result = subprocess.run(
            ["python", "scripts/check_doc_coupling.py", "--strict"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=60,  # Doc coupling check should be quick
        )
    except subprocess.TimeoutExpired:
        if verbose:
            print("    TIMEOUT: Doc coupling check did not complete within 60s")
        return False, "timeout after 60s"

    if "VIOLATIONS" in result.stdout or "VIOLATIONS" in result.stderr:
        if verbose:
            print("    FAILED: Doc-coupling violations found")
            print(result.stdout[-1000:])
        return False, "violations found"

    if verbose:
        print("    PASSED")

    return True, "passed"


def get_git_info(project_root: Path) -> tuple[str, str]:
    """Get current git commit and branch.

    Returns (commit_hash, branch_name).
    """
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
        ).stdout.strip()

        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
        ).stdout.strip()

        return commit, branch
    except Exception:
        return "unknown", "unknown"


def update_plan_file(
    plan_file: Path,
    unit_summary: str,
    e2e_smoke_summary: str,
    e2e_real_summary: str,
    doc_summary: str,
    commit: str,
    dry_run: bool = False,
) -> bool:
    """Update plan file with verification evidence and complete status.

    Returns True if updated successfully.
    """
    content = plan_file.read_text()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Build verification evidence block
    evidence = f"""
**Verified:** {timestamp}
**Verification Evidence:**
```yaml
completed_by: scripts/complete_plan.py
timestamp: {timestamp}
tests:
  unit: {unit_summary}
  e2e_smoke: {e2e_smoke_summary}
  e2e_real: {e2e_real_summary}
  doc_coupling: {doc_summary}
commit: {commit}
```
"""

    # Update status line
    new_content = re.sub(
        r"\*\*Status:\*\*\s*.+",
        f"**Status:** \u2705 Complete",  # ✅
        content
    )

    # Check if already has verification section
    if "**Verified:**" in new_content:
        # Update existing verification
        new_content = re.sub(
            r"\*\*Verified:\*\*.*?```\n",
            evidence.strip() + "\n",
            new_content,
            flags=re.DOTALL
        )
    else:
        # Add verification after status line
        new_content = re.sub(
            r"(\*\*Status:\*\*\s*.+\n)",
            f"\\1{evidence}",
            new_content
        )

    if dry_run:
        print(f"\n[DRY RUN] Would update {plan_file.name}:")
        print(f"  Status: \u2705 Complete")
        print(f"  Verified: {timestamp}")
        print(f"  Commit: {commit}")
        return True

    plan_file.write_text(new_content)
    return True


def update_plan_index(
    plan_number: int,
    plans_dir: Path,
    dry_run: bool = False,
) -> bool:
    """Update plan status in CLAUDE.md index.

    Returns True if updated successfully.
    """
    index_file = plans_dir / "CLAUDE.md"
    if not index_file.exists():
        return False

    content = index_file.read_text()

    # Find and update the plan row
    # Pattern: | N | [Name](file.md) | Priority | Status | Blocks |
    pattern = rf"(\|\s*{plan_number}\s*\|[^|]+\|[^|]+\|)\s*[^|]+(\s*\|)"

    # Use literal checkmark to avoid regex escape issues
    checkmark = "\u2705"  # ✅
    replacement = f"\\1 {checkmark} Complete \\2"
    new_content = re.sub(pattern, replacement, content)

    if new_content == content:
        print(f"  WARNING: Could not find plan #{plan_number} in index")
        return False

    if dry_run:
        print(f"[DRY RUN] Would update plans/CLAUDE.md index")
        return True

    index_file.write_text(new_content)
    return True


def complete_plan(
    plan_number: int,
    project_root: Path,
    dry_run: bool = False,
    skip_e2e: bool = False,
    skip_real_e2e: bool = False,
    force: bool = False,
    human_verified: bool = False,
    verbose: bool = True,
) -> bool:
    """Complete a plan with full verification.

    Returns True if plan was completed successfully.
    """
    plans_dir = project_root / "docs" / "plans"
    plan_file = find_plan_file(plan_number, plans_dir)

    if not plan_file:
        print(f"Error: Plan #{plan_number} not found in {plans_dir}")
        return False

    current_status = get_plan_status(plan_file)

    if verbose:
        print(f"\n{'='*60}")
        print(f"Completing Plan #{plan_number}")
        print(f"{'='*60}")
        print(f"File: {plan_file.name}")
        print(f"Current Status: {current_status}")

    if ("\u2705" in current_status or "Complete" in current_status) and not force:
        print(f"\nPlan #{plan_number} is already marked complete.")
        print("Use --force to re-verify and update evidence.")
        return True

    if force and verbose:
        print(f"  (--force: re-verifying already-complete plan)")

    # Check for human review requirements
    human_review_section = get_human_review_section(plan_file)
    if human_review_section and not human_verified:
        # Human review required but not confirmed
        print_human_review_instructions(plan_number, human_review_section, plan_file)
        print(f"\n❌ Cannot complete: human review required but --human-verified not provided")
        return False

    if human_review_section and human_verified and verbose:
        print(f"  (--human-verified: human review confirmed)")

    # Run verification steps
    all_passed = True

    # 1. Unit tests
    unit_passed, unit_summary = run_unit_tests(project_root, verbose)
    if not unit_passed:
        all_passed = False

    # 2. E2E smoke tests
    if skip_e2e:
        e2e_smoke_passed, e2e_smoke_summary = True, "skipped (--skip-e2e)"
        if verbose:
            print("\n[2/4] E2E smoke tests... SKIPPED (--skip-e2e flag)")
    else:
        e2e_smoke_passed, e2e_smoke_summary = run_e2e_tests(project_root, verbose)
        if not e2e_smoke_passed:
            all_passed = False

    # 3. Real E2E tests (actual LLM calls)
    if skip_e2e or skip_real_e2e:
        e2e_real_passed, e2e_real_summary = True, "skipped (--skip-real-e2e)"
        if verbose:
            print("\n[3/4] Real E2E tests... SKIPPED (--skip-real-e2e flag)")
    else:
        e2e_real_passed, e2e_real_summary = run_real_e2e_tests(project_root, verbose)
        if not e2e_real_passed:
            all_passed = False

    # 4. Doc coupling
    doc_passed, doc_summary = check_doc_coupling(project_root, verbose)
    if not doc_passed:
        all_passed = False

    # Summary
    if verbose:
        print(f"\n{'='*60}")
        print("VERIFICATION SUMMARY")
        print(f"{'='*60}")
        print(f"  Unit tests:      {'PASS' if unit_passed else 'FAIL'}")
        print(f"  E2E smoke:       {'PASS' if e2e_smoke_passed else 'FAIL'}")
        print(f"  E2E real (LLM):  {'PASS' if e2e_real_passed else 'FAIL'}")
        print(f"  Doc coupling:    {'PASS' if doc_passed else 'FAIL'}")

    if not all_passed:
        print(f"\nFAILED: Plan #{plan_number} cannot be marked complete.")
        print("Fix the issues above and try again.")
        return False

    # All passed - update plan file
    commit, branch = get_git_info(project_root)

    if verbose:
        print(f"\nAll checks passed!")

    update_plan_file(
        plan_file,
        unit_summary,
        e2e_smoke_summary,
        e2e_real_summary,
        doc_summary,
        commit,
        dry_run,
    )

    update_plan_index(plan_number, plans_dir, dry_run)

    if not dry_run:
        print(f"\n\u2705 Plan #{plan_number} marked COMPLETE")
        print(f"   Verification evidence recorded in {plan_file.name}")
        print(f"\nNext steps:")
        print(f"   1. Commit changes: git add {plan_file}")

    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enforce plan completion requirements",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        "--plan", "-p",
        type=int,
        required=True,
        help="Plan number to complete (e.g., 35)"
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Check without updating files"
    )
    parser.add_argument(
        "--skip-e2e",
        action="store_true",
        help="Skip all E2E tests (for documentation-only plans)"
    )
    parser.add_argument(
        "--skip-real-e2e",
        action="store_true",
        help="Skip real E2E tests (actual LLM calls) but run smoke tests"
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Re-verify and update evidence for already-complete plans"
    )
    parser.add_argument(
        "--human-verified",
        action="store_true",
        help="Confirm human review has been done (for plans with '## Human Review Required')"
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Minimal output"
    )

    args = parser.parse_args()

    project_root = Path.cwd()

    success = complete_plan(
        plan_number=args.plan,
        project_root=project_root,
        dry_run=args.dry_run,
        skip_e2e=args.skip_e2e,
        skip_real_e2e=args.skip_real_e2e,
        force=args.force,
        human_verified=args.human_verified,
        verbose=not args.quiet,
    )

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())

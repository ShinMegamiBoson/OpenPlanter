#!/usr/bin/env python3
"""Check for modifications to locked sections in feature files.

Locked sections (acceptance_criteria with locked: true) should not be modified
after initial commit. This script detects such modifications in PRs.

Exit codes:
- 0: No locked sections modified
- 1: Locked sections were modified

Usage:
    # Check against main branch (for PRs)
    python scripts/check_locked_files.py --base main

    # Check against specific commit
    python scripts/check_locked_files.py --base abc123

    # Check specific feature file
    python scripts/check_locked_files.py --base main --file meta/acceptance_gates/escrow.yaml
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


class LockedSectionViolation:
    """Represents a violation of locked section."""

    def __init__(self, feature: str, section: str, details: str):
        self.feature = feature
        self.section = section
        self.details = details

    def __str__(self) -> str:
        return f"[LOCKED] {self.feature}: {self.section} - {self.details}"


def run_git_command(args: list[str]) -> str:
    """Run a git command and return output."""
    result = subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def get_file_at_ref(filepath: str, ref: str) -> str | None:
    """Get file contents at a specific git ref."""
    try:
        return run_git_command(["show", f"{ref}:{filepath}"])
    except subprocess.CalledProcessError:
        return None  # File doesn't exist at that ref


def load_yaml_content(content: str) -> dict[str, Any] | None:
    """Parse YAML content."""
    try:
        return yaml.safe_load(content)
    except yaml.YAMLError:
        return None


def extract_locked_criteria(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Extract acceptance criteria that are marked as locked."""
    locked: dict[str, dict[str, Any]] = {}

    ac_list = data.get("acceptance_criteria", [])
    for criterion in ac_list:
        if criterion.get("locked", False):
            ac_id = criterion.get("id", criterion.get("scenario", "unknown"))
            locked[ac_id] = criterion

    return locked


def compare_locked_criteria(
    base_locked: dict[str, dict[str, Any]],
    current_locked: dict[str, dict[str, Any]],
    feature_name: str,
) -> list[LockedSectionViolation]:
    """Compare locked criteria between base and current."""
    violations: list[LockedSectionViolation] = []

    # Check for modifications to existing locked criteria
    for ac_id, base_criterion in base_locked.items():
        if ac_id not in current_locked:
            violations.append(
                LockedSectionViolation(
                    feature_name,
                    f"acceptance_criteria/{ac_id}",
                    "Locked criterion was removed",
                )
            )
        else:
            current_criterion = current_locked[ac_id]
            # Compare relevant fields (not including 'locked' flag itself)
            for field in ["scenario", "given", "when", "then"]:
                base_val = base_criterion.get(field)
                current_val = current_criterion.get(field)
                if base_val != current_val:
                    violations.append(
                        LockedSectionViolation(
                            feature_name,
                            f"acceptance_criteria/{ac_id}/{field}",
                            f"Locked field was modified",
                        )
                    )

    return violations


def check_feature_file(
    filepath: Path, base_ref: str
) -> list[LockedSectionViolation]:
    """Check a single feature file for locked section violations."""
    violations: list[LockedSectionViolation] = []
    feature_name = filepath.stem
    relative_path = str(filepath)

    # Get base version
    base_content = get_file_at_ref(relative_path, base_ref)
    if base_content is None:
        # File is new, no locked sections to violate
        return []

    base_data = load_yaml_content(base_content)
    if base_data is None:
        return []

    # Get current version
    try:
        with open(filepath) as f:
            current_content = f.read()
    except FileNotFoundError:
        # File was deleted - if it had locked sections, that's a violation
        base_locked = extract_locked_criteria(base_data)
        if base_locked:
            violations.append(
                LockedSectionViolation(
                    feature_name,
                    "file",
                    f"File with {len(base_locked)} locked criteria was deleted",
                )
            )
        return violations

    current_data = load_yaml_content(current_content)
    if current_data is None:
        violations.append(
            LockedSectionViolation(
                feature_name, "file", "Current file has invalid YAML"
            )
        )
        return violations

    # Extract and compare locked sections
    base_locked = extract_locked_criteria(base_data)
    current_locked = extract_locked_criteria(current_data)

    violations.extend(
        compare_locked_criteria(base_locked, current_locked, feature_name)
    )

    return violations


def get_changed_feature_files(base_ref: str, features_dir: Path) -> list[Path]:
    """Get list of feature files that changed since base ref.

    Uses rename detection to handle directory renames properly.
    Returns only files that exist in the current directory.
    """
    try:
        # Use -M for rename detection and --diff-filter to exclude pure deletes
        # We only care about files that exist now (M=modified, A=added, R=renamed)
        diff_output = run_git_command(
            ["diff", "-M", "--name-only", "--diff-filter=MAR", base_ref, "--", str(features_dir)]
        )
        changed = [
            Path(f.strip())
            for f in diff_output.strip().split("\n")
            if f.strip() and (f.endswith(".yaml") or f.endswith(".yml"))
        ]
        # Filter to only files that actually exist (handles renames)
        return [p for p in changed if p.exists()]
    except subprocess.CalledProcessError:
        return []


def find_all_feature_files(features_dir: Path) -> list[Path]:
    """Find all feature files in directory."""
    if not features_dir.exists():
        return []
    return list(features_dir.glob("*.yaml")) + list(features_dir.glob("*.yml"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check for modifications to locked sections in feature files"
    )
    parser.add_argument(
        "--base",
        type=str,
        default="origin/main",
        help="Base ref to compare against (default: origin/main)",
    )
    parser.add_argument(
        "--file",
        type=Path,
        help="Check specific file instead of all changed files",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Check all feature files, not just changed ones",
    )
    parser.add_argument(
        "--features-dir",
        type=Path,
        default=Path("meta/acceptance_gates"),
        help="Directory containing feature files",
    )

    args = parser.parse_args()

    # Determine which files to check
    if args.file:
        files_to_check = [args.file]
    elif args.all:
        files_to_check = find_all_feature_files(args.features_dir)
    else:
        files_to_check = get_changed_feature_files(args.base, args.features_dir)

    if not files_to_check:
        print("No feature files to check")
        return 0

    # Check each file
    all_violations: list[LockedSectionViolation] = []
    for filepath in files_to_check:
        violations = check_feature_file(filepath, args.base)
        all_violations.extend(violations)

    # Print results
    for violation in all_violations:
        print(violation)

    if all_violations:
        print(f"\n✗ {len(all_violations)} locked section violation(s) found")
        print("\nLocked sections cannot be modified after initial commit.")
        print("If changes are intentional, the spec must be unlocked first.")
        return 1

    print(f"✓ No locked section violations in {len(files_to_check)} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

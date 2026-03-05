#!/usr/bin/env python3
"""Check that documentation is updated when coupled source files change.

Usage:
    python scripts/check_doc_coupling.py [--base BASE_REF] [--suggest]
    python scripts/check_doc_coupling.py --staged  # For pre-commit hook

Compares current branch against BASE_REF (default: origin/main) to find
changed files, then checks if coupled docs were also updated.

The --staged option checks only staged files, suitable for pre-commit hooks.
If source files are staged AND their coupled docs are also staged, it passes.

Exit codes:
    0 - All couplings satisfied (or no coupled changes)
    1 - Missing doc updates (strict violations)
"""

import argparse
import fnmatch
import subprocess
import sys
from pathlib import Path

import yaml


def get_changed_files(base_ref: str) -> set[str]:
    """Get files changed between base_ref and HEAD."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", base_ref, "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return set(result.stdout.strip().split("\n")) - {""}
    except subprocess.CalledProcessError:
        # Fallback: compare against HEAD~1 for local testing
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            )
            return set(result.stdout.strip().split("\n")) - {""}
        except subprocess.CalledProcessError:
            return set()


def get_staged_files() -> set[str]:
    """Get files staged for commit."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            check=True,
        )
        return set(result.stdout.strip().split("\n")) - {""}
    except subprocess.CalledProcessError:
        return set()


def load_couplings(config_path: Path) -> list[dict]:
    """Load coupling definitions from YAML."""
    with open(config_path) as f:
        data = yaml.safe_load(f)
    return data.get("couplings", [])


def validate_config(couplings: list[dict]) -> list[str]:
    """Validate that all referenced files in config exist.

    Returns list of warnings for missing files.
    """
    warnings = []
    for coupling in couplings:
        for doc in coupling.get("docs", []):
            if not Path(doc).exists():
                warnings.append(f"Coupled doc doesn't exist: {doc}")
        # Don't validate source patterns - they're globs
    return warnings


def matches_any_pattern(filepath: str, patterns: list[str]) -> bool:
    """Check if filepath matches any glob pattern."""
    for pattern in patterns:
        if fnmatch.fnmatch(filepath, pattern):
            return True
        # Also check without leading path for simple patterns
        if fnmatch.fnmatch(Path(filepath).name, pattern):
            return True
    return False


def check_couplings(
    changed_files: set[str], couplings: list[dict]
) -> tuple[list[dict], list[dict]]:
    """Check which couplings have source changes without doc changes.

    Returns tuple of (strict_violations, soft_warnings).
    """
    strict_violations = []
    soft_warnings = []

    for coupling in couplings:
        sources = coupling.get("sources", [])
        docs = coupling.get("docs", [])
        description = coupling.get("description", "")
        is_soft = coupling.get("soft", False)

        # Find which source patterns matched
        matched_sources = []
        for changed in changed_files:
            if matches_any_pattern(changed, sources):
                matched_sources.append(changed)

        if not matched_sources:
            continue  # No source files changed for this coupling

        # Check if any coupled doc was updated
        docs_updated = any(doc in changed_files for doc in docs)

        if not docs_updated:
            violation = {
                "description": description,
                "changed_sources": matched_sources,
                "expected_docs": docs,
                "soft": is_soft,
            }
            if is_soft:
                soft_warnings.append(violation)
            else:
                strict_violations.append(violation)

    return strict_violations, soft_warnings


def print_suggestions(changed_files: set[str], couplings: list[dict]) -> None:
    """Print which docs should be updated based on changed files."""
    print("Based on your changes, consider updating:\n")

    suggestions: dict[str, list[str]] = {}  # doc -> [reasons]

    for coupling in couplings:
        sources = coupling.get("sources", [])
        docs = coupling.get("docs", [])
        description = coupling.get("description", "")

        for changed in changed_files:
            if matches_any_pattern(changed, sources):
                for doc in docs:
                    if doc not in changed_files:
                        if doc not in suggestions:
                            suggestions[doc] = []
                        suggestions[doc].append(f"{changed} ({description})")

    if not suggestions:
        print("  No documentation updates needed.")
        return

    for doc, reasons in sorted(suggestions.items()):
        print(f"  {doc}")
        for reason in reasons[:3]:  # Limit to 3 reasons
            print(f"    <- {reason}")
        if len(reasons) > 3:
            print(f"    ... and {len(reasons) - 3} more")
        print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check doc-code coupling")
    parser.add_argument(
        "--base",
        default="origin/main",
        help="Base ref to compare against (default: origin/main)",
    )
    parser.add_argument(
        "--config",
        default="scripts/doc_coupling.yaml",
        help="Path to coupling config (default: scripts/doc_coupling.yaml)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with error code on strict violations (default: warn only)",
    )
    parser.add_argument(
        "--suggest",
        action="store_true",
        help="Show which docs to update based on changes",
    )
    parser.add_argument(
        "--validate-config",
        action="store_true",
        help="Validate that all docs in config exist",
    )
    parser.add_argument(
        "--staged",
        action="store_true",
        help="Check staged files only (for pre-commit hook)",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Config not found: {config_path}")
        return 1

    couplings = load_couplings(config_path)

    # Validate config if requested
    if args.validate_config:
        warnings = validate_config(couplings)
        if warnings:
            print("Config validation warnings:")
            for w in warnings:
                print(f"  - {w}")
            return 1
        print("Config validation passed.")
        return 0

    # Get changed files based on mode
    if args.staged:
        changed_files = get_staged_files()
        if not changed_files:
            # No staged files = nothing to check
            return 0
    else:
        changed_files = get_changed_files(args.base)
        if not changed_files:
            print("No changed files detected.")
            return 0

    # Suggest mode
    if args.suggest:
        print_suggestions(changed_files, couplings)
        return 0

    strict_violations, soft_warnings = check_couplings(changed_files, couplings)

    if not strict_violations and not soft_warnings:
        print("Doc-code coupling check passed.")
        return 0

    # Print violations
    if strict_violations:
        print("=" * 60)
        print("DOC-CODE COUPLING VIOLATIONS (must fix)")
        print("=" * 60)
        print()
        for v in strict_violations:
            print(f"  {v['description']}")
            print(f"    Changed: {', '.join(v['changed_sources'][:3])}")
            if len(v['changed_sources']) > 3:
                print(f"             ... and {len(v['changed_sources']) - 3} more")
            print(f"    Update:  {', '.join(v['expected_docs'])}")
            print()

    if soft_warnings:
        print("=" * 60)
        print("DOC-CODE COUPLING WARNINGS (consider updating)")
        print("=" * 60)
        print()
        for v in soft_warnings:
            print(f"  {v['description']}")
            print(f"    Changed: {', '.join(v['changed_sources'][:3])}")
            if len(v['changed_sources']) > 3:
                print(f"             ... and {len(v['changed_sources']) - 3} more")
            print(f"    Consider: {', '.join(v['expected_docs'])}")
            print()

    print("=" * 60)
    print("If docs are already accurate, update 'Last verified' date.")
    print("=" * 60)

    return 1 if (args.strict and strict_violations) else 0


if __name__ == "__main__":
    sys.exit(main())

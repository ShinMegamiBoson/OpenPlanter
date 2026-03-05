#!/usr/bin/env python3
"""Sync governance headers in source files.

This script reads governance.yaml and ensures source files have correct
GOVERNANCE blocks listing their governing ADRs.

Usage:
    python scripts/sync_governance.py           # Dry-run (default)
    python scripts/sync_governance.py --check   # Check only, exit 1 if out of sync
    python scripts/sync_governance.py --apply   # Apply changes
    python scripts/sync_governance.py --apply --backup  # Apply with backups

Safeguards:
    - Dry-run by default (must use --apply to modify)
    - Only modifies content between GOVERNANCE START/END markers
    - Validates Python syntax after modification
    - Refuses to run on dirty git working tree (use --force to override)
    - Atomic writes (temp file, validate, then replace)
    - Optional backup creation
"""

from __future__ import annotations

import argparse
import os
import py_compile
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

# Markers that delimit the governance block in source files
GOVERNANCE_START = "# --- GOVERNANCE START (do not edit) ---"
GOVERNANCE_END = "# --- GOVERNANCE END ---"

# Pattern to match existing governance block
GOVERNANCE_PATTERN = re.compile(
    rf"{re.escape(GOVERNANCE_START)}.*?{re.escape(GOVERNANCE_END)}",
    re.DOTALL,
)


@dataclass
class GovernanceConfig:
    """Parsed governance configuration."""

    files: dict[str, dict]
    adrs: dict[int, dict]

    @classmethod
    def load(cls, path: Path) -> "GovernanceConfig":
        """Load governance config from YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)

        return cls(
            files=data.get("files", {}),
            adrs=data.get("adrs", {}),
        )

    def get_adr_title(self, adr_num: int) -> str:
        """Get title for an ADR number."""
        adr = self.adrs.get(adr_num)
        if adr:
            return adr.get("title", f"ADR-{adr_num:04d}")
        return f"ADR-{adr_num:04d}"

    def validate(self, adr_dir: Path) -> list[str]:
        """Validate config, return list of errors."""
        errors = []

        # Check all referenced ADRs exist
        for file_path, config in self.files.items():
            for adr_num in config.get("adrs", []):
                if adr_num not in self.adrs:
                    errors.append(f"{file_path}: references unknown ADR {adr_num}")
                else:
                    adr_file = adr_dir / self.adrs[adr_num]["file"]
                    if not adr_file.exists():
                        errors.append(f"ADR-{adr_num:04d}: file not found: {adr_file}")

        # Check all governed files exist
        for file_path in self.files:
            if not Path(file_path).exists():
                errors.append(f"Governed file not found: {file_path}")

        return errors


def generate_governance_block(config: GovernanceConfig, file_path: str) -> str:
    """Generate the governance block content for a file."""
    file_config = config.files.get(file_path, {})
    adr_nums = file_config.get("adrs", [])
    context = file_config.get("context", "").strip()

    lines = [GOVERNANCE_START]

    for adr_num in sorted(adr_nums):
        title = config.get_adr_title(adr_num)
        lines.append(f"# ADR-{adr_num:04d}: {title}")

    if context:
        lines.append("#")
        for line in context.split("\n"):
            lines.append(f"# {line}" if line.strip() else "#")

    lines.append(GOVERNANCE_END)

    return "\n".join(lines)


def find_docstring_end(content: str) -> Optional[int]:
    """Find the end position of the module docstring.

    Returns the position after the closing quotes, or None if no docstring.
    """
    # Skip any leading whitespace/comments
    stripped = content.lstrip()
    offset = len(content) - len(stripped)

    # Check for docstring
    for quote in ['"""', "'''"]:
        if stripped.startswith(quote):
            # Find closing quote
            end_pos = stripped.find(quote, len(quote))
            if end_pos != -1:
                return offset + end_pos + len(quote)

    return None


def update_file_content(content: str, governance_block: str) -> tuple[str, bool]:
    """Update file content with governance block.

    Returns (new_content, was_changed).

    Strategy:
    1. If GOVERNANCE markers exist, replace content between them
    2. If no markers, insert after module docstring (if exists)
    3. If no docstring, insert at top after any initial comments
    """
    # Case 1: Markers already exist - replace between them
    if GOVERNANCE_START in content:
        match = GOVERNANCE_PATTERN.search(content)
        if match:
            old_block = match.group(0)
            if old_block == governance_block:
                return content, False  # No change needed
            new_content = content[: match.start()] + governance_block + content[match.end() :]
            return new_content, True

    # Case 2: No markers - need to insert
    # Find insertion point (after docstring if exists)
    docstring_end = find_docstring_end(content)

    if docstring_end is not None:
        # Insert governance block right after docstring
        before = content[:docstring_end]
        after = content[docstring_end:]

        # Check if docstring ends with newline
        if not before.endswith("\n"):
            before += "\n"

        new_content = before + "\n" + governance_block + "\n" + after.lstrip("\n")
        return new_content, True
    else:
        # No docstring - insert at top (after shebang/encoding if present)
        lines = content.split("\n")
        insert_at = 0

        for i, line in enumerate(lines):
            if line.startswith("#!") or line.startswith("# -*-") or line.startswith("# coding"):
                insert_at = i + 1
            else:
                break

        before = "\n".join(lines[:insert_at])
        after = "\n".join(lines[insert_at:])

        if before:
            new_content = before + "\n\n" + governance_block + "\n\n" + after
        else:
            new_content = governance_block + "\n\n" + after

        return new_content, True


def validate_python_syntax(path: Path) -> bool:
    """Validate Python syntax of a file. Returns True if valid."""
    try:
        py_compile.compile(str(path), doraise=True)
        return True
    except py_compile.PyCompileError:
        return False


def is_git_dirty() -> bool:
    """Check if git working tree has uncommitted changes."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        )
        return bool(result.stdout.strip())
    except subprocess.CalledProcessError:
        return False  # Not a git repo, allow


def sync_file(
    file_path: Path,
    config: GovernanceConfig,
    apply: bool = False,
    backup: bool = False,
) -> tuple[bool, str]:
    """Sync governance for a single file.

    Returns (needs_change, message).
    """
    if not file_path.exists():
        return False, f"SKIP: {file_path} not found"

    # Read current content
    content = file_path.read_text()

    # Generate expected governance block
    governance_block = generate_governance_block(config, str(file_path))

    # Update content
    new_content, changed = update_file_content(content, governance_block)

    if not changed:
        return False, f"OK: {file_path}"

    if not apply:
        return True, f"WOULD UPDATE: {file_path}"

    # Apply mode - write changes with safeguards

    # Create backup if requested
    if backup:
        backup_path = file_path.with_suffix(file_path.suffix + ".bak")
        shutil.copy2(file_path, backup_path)

    # Write to temp file first
    fd, temp_path = tempfile.mkstemp(suffix=".py", dir=file_path.parent)
    try:
        os.write(fd, new_content.encode())
        os.close(fd)

        # Validate syntax
        if file_path.suffix == ".py" and not validate_python_syntax(Path(temp_path)):
            os.unlink(temp_path)
            return True, f"ERROR: {file_path} - syntax error after modification, original unchanged"

        # Atomic replace
        os.replace(temp_path, file_path)
        return True, f"UPDATED: {file_path}"

    except Exception as e:
        # Clean up temp file on error
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        return True, f"ERROR: {file_path} - {e}"


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Sync governance headers in source files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check only, exit 1 if files are out of sync",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes (default is dry-run)",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Create .bak files before modifying (requires --apply)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip git dirty check",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("scripts/governance.yaml"),
        help="Path to governance.yaml",
    )

    args = parser.parse_args()

    # Validate arguments
    if args.backup and not args.apply:
        parser.error("--backup requires --apply")

    # Check git status
    if args.apply and not args.force and is_git_dirty():
        print("ERROR: Git working tree has uncommitted changes.")
        print("Commit or stash first, so you can easily revert if needed.")
        print("Use --force to override this check.")
        return 1

    # Load config
    if not args.config.exists():
        print(f"ERROR: Config file not found: {args.config}")
        return 1

    config = GovernanceConfig.load(args.config)

    # Validate config
    adr_dir = Path("docs/adr")
    errors = config.validate(adr_dir)
    if errors:
        print("Configuration errors:")
        for error in errors:
            print(f"  {error}")
        return 1

    # Process files
    if not args.apply and not args.check:
        print("DRY RUN (use --apply to modify files, --check to verify)\n")

    changes_needed = 0
    results = []

    for file_path in sorted(config.files.keys()):
        needs_change, message = sync_file(
            Path(file_path),
            config,
            apply=args.apply,
            backup=args.backup,
        )
        results.append(message)
        if needs_change:
            changes_needed += 1

    # Print results
    for message in results:
        print(message)

    # Summary
    print()
    if changes_needed == 0:
        print("All files in sync.")
        return 0
    elif args.check:
        print(f"FAILED: {changes_needed} file(s) out of sync.")
        return 1
    elif args.apply:
        print(f"Updated {changes_needed} file(s).")
        return 0
    else:
        print(f"{changes_needed} file(s) would be updated.")
        print("Run with --apply to make changes.")
        return 0


if __name__ == "__main__":
    sys.exit(main())

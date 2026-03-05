#!/usr/bin/env python3
"""Detect and report mock usage in tests.

Helps prevent "green CI, broken production" by flagging suspicious mock patterns.

Usage:
    python scripts/check_mock_usage.py           # Report mock usage
    python scripts/check_mock_usage.py --strict  # Fail on suspicious patterns
    python scripts/check_mock_usage.py --list    # Just list files with mocks
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

# Patterns that are suspicious - mocking internal code instead of testing it
SUSPICIOUS_PATTERNS = [
    # Mocking our own code (not external APIs)
    r"@patch\(['\"]src\.",
    r"patch\(['\"]src\.",
    # Mocking memory/agent internals (should use real GEMINI_API_KEY)
    r"@patch.*Memory",
    r"@patch.*Agent",
    r"@patch.*get_memory",
    # MagicMock used as return value for our code
    r"return_value\s*=\s*MagicMock",
]

# Patterns that are OK - external dependencies, time, network errors
OK_PATTERNS = [
    r"@patch.*time\.",
    r"@patch.*datetime",
    r"@patch.*sleep",
    r"@patch.*requests\.",
    r"@patch.*httpx\.",
    r"@patch.*aiohttp\.",
]


def find_mock_usage(test_dir: Path) -> dict[str, list[tuple[int, str]]]:
    """Find all mock usage in test files.

    Returns dict mapping file path to list of (line_number, line_content).
    """
    results: dict[str, list[tuple[int, str]]] = {}

    for test_file in test_dir.glob("test_*.py"):
        content = test_file.read_text()
        lines = content.split("\n")

        mock_lines: list[tuple[int, str]] = []

        for i, line in enumerate(lines, 1):
            # Check for mock imports
            if "unittest.mock" in line or "from mock import" in line:
                mock_lines.append((i, line.strip()))
            # Check for @patch decorators
            elif "@patch" in line:
                mock_lines.append((i, line.strip()))
            # Check for MagicMock/AsyncMock usage
            elif "MagicMock" in line or "AsyncMock" in line:
                if "import" not in line:  # Skip import lines
                    mock_lines.append((i, line.strip()))

        if mock_lines:
            results[str(test_file)] = mock_lines

    return results


def check_suspicious(mock_usage: dict[str, list[tuple[int, str]]]) -> list[str]:
    """Check for suspicious mock patterns.

    Returns list of warnings.
    """
    warnings: list[str] = []

    for file_path, lines in mock_usage.items():
        # Read full file to check for mock-ok comments
        try:
            full_content = Path(file_path).read_text()
            full_lines = full_content.split("\n")
        except Exception:
            full_content = ""
            full_lines = []

        # Check for file-level mock-ok comment (in first 20 lines, typically in docstring)
        file_has_blanket_justification = any(
            "# mock-ok:" in line for line in full_lines[:20]
        )

        for line_num, line in lines:
            # Check against suspicious patterns
            for pattern in SUSPICIOUS_PATTERNS:
                if re.search(pattern, line):
                    # Check if it matches an OK pattern
                    is_ok = any(re.search(ok, line) for ok in OK_PATTERNS)
                    if is_ok:
                        continue

                    # Check for file-level justification
                    if file_has_blanket_justification:
                        continue

                    # Check for mock-ok comment on this line or previous line
                    has_justification = False
                    if "# mock-ok:" in line:
                        has_justification = True
                    elif line_num >= 2 and line_num <= len(full_lines):
                        prev_line = full_lines[line_num - 2]  # -2 because 0-indexed
                        if "# mock-ok:" in prev_line:
                            has_justification = True

                    if not has_justification:
                        warnings.append(f"{file_path}:{line_num}: {line}")

    return warnings


def main() -> int:
    test_dir = Path("tests")

    if not test_dir.exists():
        print("ERROR: tests/ directory not found")
        return 1

    mock_usage = find_mock_usage(test_dir)

    if "--list" in sys.argv:
        print("Files with mock usage:")
        for f in sorted(mock_usage.keys()):
            print(f"  {f} ({len(mock_usage[f])} occurrences)")
        return 0

    # Report all mock usage
    total = sum(len(v) for v in mock_usage.values())
    print(f"Found {total} mock usage(s) in {len(mock_usage)} file(s)\n")

    # Check for suspicious patterns
    warnings = check_suspicious(mock_usage)

    if warnings:
        print("=" * 60)
        print("SUSPICIOUS MOCK PATTERNS (may hide real failures)")
        print("=" * 60)
        for w in warnings:
            print(f"  {w}")
        print()
        print("These patterns mock internal code instead of external APIs.")
        print("Consider:")
        print("  1. Using real implementations with GEMINI_API_KEY in CI")
        print("  2. Adding # mock-ok: <reason> comment if mock is justified")
        print()

        if "--strict" in sys.argv:
            print("FAILED: Suspicious mock patterns detected (--strict mode)")
            return 1
    else:
        print("No suspicious mock patterns detected.")

    # Summary
    if mock_usage and "--quiet" not in sys.argv:
        print("\nMock usage by file:")
        for f in sorted(mock_usage.keys()):
            print(f"  {f}: {len(mock_usage[f])} occurrence(s)")

    return 0


if __name__ == "__main__":
    sys.exit(main())

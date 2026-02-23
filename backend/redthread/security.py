"""Data security utilities for PII handling.

BSA/AML data contains PII subject to 31 USC 5318(g)(2).
These utilities enforce restrictive file/directory permissions
and sanitize log entries to prevent PII leakage.
"""

import os
from pathlib import Path


def secure_directory(path: Path, mode: int = 0o700) -> None:
    """Create directory with restrictive permissions. Creates parent dirs if needed."""
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, mode)


def secure_file(path: Path, mode: int = 0o600) -> None:
    """Set restrictive permissions on a file."""
    if path.exists():
        os.chmod(path, mode)


def sanitize_log_entry(tool_name: str, duration_ms: float, success: bool) -> str:
    """Create a sanitized log entry for agent tool calls.

    Logs tool name and timing but NOT input/output content
    containing entity names or financial data.
    """
    status = "OK" if success else "FAIL"
    return f"[tool] {tool_name} {status} {duration_ms:.1f}ms"

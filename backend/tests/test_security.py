"""Tests for data security utilities (Section 12: Data Security & PII Handling)."""

import re
import stat
from pathlib import Path

from redthread.security import sanitize_log_entry, secure_directory, secure_file


def test_secure_directory_creates_with_permissions(tmp_path: Path) -> None:
    """secure_directory creates a directory with 0o700 permissions."""
    target = tmp_path / "secure_data" / "nested"
    secure_directory(target)

    assert target.exists()
    assert target.is_dir()
    actual_mode = stat.S_IMODE(target.stat().st_mode)
    assert actual_mode == 0o700, f"Expected 0o700, got {oct(actual_mode)}"


def test_secure_file_sets_permissions(tmp_path: Path) -> None:
    """secure_file sets a file to 0o600 permissions."""
    target = tmp_path / "secret.json"
    target.write_text('{"key": "value"}')

    secure_file(target)

    actual_mode = stat.S_IMODE(target.stat().st_mode)
    assert actual_mode == 0o600, f"Expected 0o600, got {oct(actual_mode)}"


def test_sanitize_log_entry_success() -> None:
    """sanitize_log_entry returns formatted string with OK status and no PII."""
    entry = sanitize_log_entry("entity_search", 42.5, success=True)

    assert entry == "[tool] entity_search OK 42.5ms"
    # Must not contain any placeholder for user-supplied data
    assert "entity_search" in entry
    assert "42.5ms" in entry
    assert "OK" in entry


def test_sanitize_log_entry_failure() -> None:
    """sanitize_log_entry includes FAIL status for unsuccessful calls."""
    entry = sanitize_log_entry("ingest_sar", 150.0, success=False)

    assert entry == "[tool] ingest_sar FAIL 150.0ms"
    assert "FAIL" in entry


def test_docker_compose_binds_localhost() -> None:
    """docker-compose.yml port bindings must use 127.0.0.1 (not 0.0.0.0)."""
    compose_path = Path(__file__).resolve().parents[2] / "docker-compose.yml"
    assert compose_path.exists(), f"docker-compose.yml not found at {compose_path}"

    content = compose_path.read_text()

    # Match all port mapping lines (e.g., - "127.0.0.1:8000:8000")
    port_pattern = re.compile(r'-\s*"([^"]+)"')
    in_ports_block = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped == "ports:":
            in_ports_block = True
            continue
        if in_ports_block:
            match = port_pattern.match(stripped)
            if match:
                port_str = match.group(1)
                assert port_str.startswith("127.0.0.1:"), (
                    f"Port mapping '{port_str}' must bind to 127.0.0.1"
                )
            elif stripped and not stripped.startswith("#"):
                # Left the ports block
                in_ports_block = False

#!/usr/bin/env python3
"""Dead code sensor for meta-process framework.

Wraps vulture (Python) and knip (TypeScript) to detect unused code.
Reads config from meta-process.yaml quality.dead_code section.
Outputs JSON findings for consumption by ecosystem_sweep and task_planner.

Portable: no import dependencies beyond stdlib. Designed to be copied
into target projects via install.sh.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Finding:
    """A single dead code finding from vulture or knip."""

    file: str
    line: int
    name: str
    kind: str
    confidence: int


@dataclass
class Result:
    """Aggregated result of dead code detection."""

    passed: bool
    findings: list[Finding] = field(default_factory=list)
    tool_output: str = ""
    tool_available: bool = True
    error: str = ""


def _load_config(project_root: Path) -> dict[str, Any]:
    """Load dead_code config from meta-process.yaml.

    Returns the quality.dead_code section, or sensible defaults
    if the file or section doesn't exist.
    """
    config_path = project_root / "meta-process.yaml"
    defaults: dict[str, Any] = {
        "enabled": False,
        "strict": False,
        "min_confidence": 80,
        "paths": [],
        "whitelist": ".vulture_whitelist.py",
    }
    if not config_path.is_file():
        return defaults

    try:
        import yaml
    except ImportError:
        return defaults

    raw = yaml.safe_load(config_path.read_text())
    if not isinstance(raw, dict):
        return defaults

    mp = raw.get("meta_process") or raw.get("meta-process", {})
    quality = mp.get("quality", {}) if isinstance(mp, dict) else {}
    dead_code = quality.get("dead_code", {}) if isinstance(quality, dict) else {}

    for key, default in defaults.items():
        dead_code.setdefault(key, default)
    return dead_code


def _parse_vulture_line(line: str) -> Finding | None:
    """Parse a vulture output line into a Finding.

    Format: path.py:123: unused function 'foo' (90% confidence)
    """
    match = re.match(
        r"(.+?):(\d+): (unused \w+) '(\w+)' \((\d+)% confidence\)", line
    )
    if match:
        return Finding(
            file=match.group(1),
            line=int(match.group(2)),
            kind=match.group(3).replace(" ", "-"),
            name=match.group(4),
            confidence=int(match.group(5)),
        )
    return None


def _run_vulture(
    project_root: Path,
    paths: list[str],
    min_confidence: int,
    whitelist: str,
) -> Result:
    """Run vulture for Python dead code detection."""
    cmd = ["python", "-m", "vulture"]
    if paths:
        cmd.extend(paths)
    else:
        cmd.append(".")
    cmd.extend(["--min-confidence", str(min_confidence)])

    whitelist_path = project_root / whitelist
    if whitelist_path.is_file():
        cmd.append(str(whitelist_path))

    try:
        proc = subprocess.run(
            cmd, cwd=str(project_root), capture_output=True, text=True, timeout=120
        )
    except FileNotFoundError:
        return Result(passed=True, tool_available=False, error="vulture not installed")
    except subprocess.TimeoutExpired:
        return Result(passed=True, error="vulture timed out after 120s")

    findings: list[Finding] = []
    for line in proc.stdout.strip().splitlines():
        f = _parse_vulture_line(line)
        if f:
            findings.append(f)

    return Result(passed=True, findings=findings, tool_output=proc.stdout.strip())


def _run_knip(project_root: Path) -> Result:
    """Run knip for TypeScript dead code detection."""
    try:
        proc = subprocess.run(
            ["npx", "knip", "--reporter", "compact"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        return Result(passed=True, tool_available=False, error="npx/knip not available")
    except subprocess.TimeoutExpired:
        return Result(passed=True, error="knip timed out after 120s")

    return Result(passed=True, tool_output=proc.stdout.strip())


def check_dead_code(project_root: Path) -> Result:
    """Run dead code detection for a project.

    Reads config from meta-process.yaml. Auto-detects language from
    project contents (package.json → TypeScript, *.py → Python).
    In strict mode, findings cause passed=False.
    """
    config = _load_config(project_root)

    # Detect language
    if (project_root / "package.json").is_file():
        result = _run_knip(project_root)
    else:
        result = _run_vulture(
            project_root,
            paths=config.get("paths", []),
            min_confidence=config.get("min_confidence", 80),
            whitelist=config.get("whitelist", ".vulture_whitelist.py"),
        )

    if config.get("strict") and result.findings:
        result.passed = False

    return result


def main() -> None:
    """CLI entry point. Outputs JSON to stdout."""
    project_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    project_root = project_root.resolve()

    config = _load_config(project_root)
    if not config.get("enabled"):
        json.dump({"skipped": True, "reason": "dead_code not enabled in meta-process.yaml"}, sys.stdout)
        print()
        return

    result = check_dead_code(project_root)
    output = {
        "passed": result.passed,
        "findings_count": len(result.findings),
        "findings": [asdict(f) for f in result.findings],
        "tool_available": result.tool_available,
        "error": result.error,
    }
    json.dump(output, sys.stdout, indent=2)
    print()

    if not result.passed:
        sys.exit(1)


if __name__ == "__main__":
    main()

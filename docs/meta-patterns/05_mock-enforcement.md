# Pattern: Mock Enforcement

## Problem

AI coding assistants (and humans) sometimes mock internal code extensively to make tests pass, then declare success. But the real code is broken - mocks hide the failures. Result: green CI, broken production.

## Solution

1. Detect suspicious mock patterns (mocking internal code instead of external APIs)
2. Require explicit justification for each mock via `# mock-ok: reason` comment
3. Fail CI if unjustified mocks detected
4. Ensure real API keys available in CI for integration tests

## Files

| File | Purpose |
|------|---------|
| `scripts/check_mock_usage.py` | Detect suspicious mock patterns |
| `.github/workflows/ci.yml` | CI job that runs `--strict` mode |
| `CLAUDE.md` | Policy documentation for AI assistants |

## Setup

### 1. Create the detection script

```python
#!/usr/bin/env python3
"""Detect and report mock usage in tests."""

import re
import sys
from pathlib import Path

# Patterns that are suspicious - mocking internal code
SUSPICIOUS_PATTERNS = [
    r"@patch\(['\"]src\.",           # Mocking your own src/ code
    r"@patch.*YourCoreClass",        # Mocking core classes
    r"return_value\s*=\s*MagicMock", # MagicMock for internal code
]

# Patterns that are OK - external dependencies
OK_PATTERNS = [
    r"@patch.*time\.",
    r"@patch.*datetime",
    r"@patch.*requests\.",
    r"@patch.*httpx\.",
]

def find_mock_usage(test_dir: Path) -> dict[str, list[tuple[int, str]]]:
    """Find all mock usage in test files."""
    results = {}
    for test_file in test_dir.glob("test_*.py"):
        content = test_file.read_text()
        lines = content.split("\n")
        mock_lines = []
        for i, line in enumerate(lines, 1):
            if "@patch" in line or "MagicMock" in line:
                if "import" not in line:
                    mock_lines.append((i, line.strip()))
        if mock_lines:
            results[str(test_file)] = mock_lines
    return results

def check_suspicious(mock_usage: dict) -> list[str]:
    """Check for suspicious patterns, respecting # mock-ok: comments."""
    warnings = []
    for file_path, lines in mock_usage.items():
        content = Path(file_path).read_text()
        file_lines = content.split("\n")

        # Check for file-level justification in first 20 lines
        file_justified = any("# mock-ok:" in line for line in file_lines[:20])

        for line_num, line in lines:
            for pattern in SUSPICIOUS_PATTERNS:
                if re.search(pattern, line):
                    if any(re.search(ok, line) for ok in OK_PATTERNS):
                        continue
                    if file_justified:
                        continue
                    if "# mock-ok:" in line:
                        continue
                    # Check previous line for justification
                    if line_num >= 2 and "# mock-ok:" in file_lines[line_num - 2]:
                        continue
                    warnings.append(f"{file_path}:{line_num}: {line}")
    return warnings

def main() -> int:
    test_dir = Path("tests")
    mock_usage = find_mock_usage(test_dir)
    warnings = check_suspicious(mock_usage)

    if warnings and "--strict" in sys.argv:
        print("SUSPICIOUS MOCK PATTERNS:")
        for w in warnings:
            print(f"  {w}")
        print("\nAdd '# mock-ok: <reason>' to justify, or use real implementations.")
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

### 2. Add CI job

```yaml
# In .github/workflows/ci.yml
mock-usage:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with:
        python-version: "3.11"
    - name: Check for suspicious mock patterns
      run: python scripts/check_mock_usage.py --strict
```

### 3. Add API keys to CI

```yaml
# In your test job
- name: Run pytest
  env:
    YOUR_API_KEY: ${{ secrets.YOUR_API_KEY }}
  run: pytest tests/ -v
```

### 4. Document the policy

Add to your `CLAUDE.md` or contributing guide:

```markdown
### Mock Policy

CI detects suspicious mock patterns. Mocking internal code hides real failures.

**Allowed mocks:** External APIs (requests, httpx), time/datetime

**Not allowed without justification:** `@patch("src.anything")`

**To justify:** Add `# mock-ok: <reason>` comment
```

## Usage

```bash
# Check for suspicious mocks (report only)
python scripts/check_mock_usage.py

# Fail on suspicious mocks (CI mode)
python scripts/check_mock_usage.py --strict

# List files with any mock usage
python scripts/check_mock_usage.py --list
```

### Justifying a Mock

```python
# Line-level justification
# mock-ok: Testing error handling when API unavailable
@patch("src.external.api_client")
def test_handles_api_failure():
    ...

# File-level justification (in docstring, first 20 lines)
"""Tests for runner orchestration.

# mock-ok: Mocking load_agents avoids LLM API calls - tests focus on orchestration
"""
```

## Customization

### Change suspicious patterns

Edit `SUSPICIOUS_PATTERNS` in the script:

```python
SUSPICIOUS_PATTERNS = [
    r"@patch\(['\"]mypackage\.",  # Your package name
    r"@patch.*Database",          # Your core classes
    r"@patch.*Service",
]
```

### Change allowed patterns

Edit `OK_PATTERNS`:

```python
OK_PATTERNS = [
    r"@patch.*time\.",
    r"@patch.*redis\.",     # If Redis is external
    r"@patch.*boto3\.",     # AWS SDK
]
```

### Adjust file-level justification scope

Change the line limit for file-level `# mock-ok:` detection:

```python
file_justified = any("# mock-ok:" in line for line in file_lines[:20])  # First 20 lines
```

## Limitations

- **Pattern-based detection** - May have false positives/negatives. Tune patterns for your codebase.
- **Justification is honor system** - Anyone can add `# mock-ok:` with a bad reason. Code review still needed.
- **Doesn't verify mock correctness** - A justified mock can still be wrong. This only ensures visibility.

## See Also

- [pytest-mock documentation](https://pytest-mock.readthedocs.io/)
- [unittest.mock best practices](https://docs.python.org/3/library/unittest.mock.html)

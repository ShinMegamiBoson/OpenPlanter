# Pattern: Doc-Code Coupling

## Problem

Documentation drifts from code. AI assistants change code but forget to update docs. Humans do the same. Over time, docs become misleading or useless.

## Solution

1. Define explicit mappings: "when file X changes, doc Y must be updated"
2. CI checks if coupled docs were modified together with their sources
3. Two enforcement levels: strict (CI fails) and soft (CI warns)
4. Escape hatch: update "Last verified" date if docs are already accurate

## Files

| File | Purpose |
|------|---------|
| `scripts/check_doc_coupling.py` | Enforcement logic |
| `scripts/doc_coupling.yaml` | Source-to-doc mappings (can be unified into `relationships.yaml`) |
| `.github/workflows/ci.yml` | CI job |

## Setup

### 1. Create the coupling config

```yaml
# scripts/doc_coupling.yaml
couplings:
  # STRICT - CI fails if violated
  - sources:
      - "src/core/engine.py"
      - "src/core/runner.py"
    docs:
      - "docs/architecture/engine.md"
    description: "Core engine documentation"

  - sources:
      - "src/api/*.py"
    docs:
      - "docs/api-reference.md"
    description: "API documentation"

  # SOFT - CI warns but doesn't fail
  - sources:
      - "src/**/*.py"
    docs:
      - "docs/CHANGELOG.md"
    description: "Consider updating changelog"
    soft: true
```

### 2. Create the check script

```python
#!/usr/bin/env python3
"""Check doc-code coupling."""

import subprocess
import sys
from pathlib import Path
import yaml
import fnmatch

def get_changed_files(base: str) -> set[str]:
    """Get files changed since base branch."""
    result = subprocess.run(
        ["git", "diff", "--name-only", base],
        capture_output=True, text=True
    )
    return set(result.stdout.strip().split("\n")) if result.stdout.strip() else set()

def matches_pattern(file: str, pattern: str) -> bool:
    """Check if file matches glob pattern."""
    return fnmatch.fnmatch(file, pattern)

def check_coupling(config_path: str, base: str, strict: bool) -> int:
    """Check coupling violations."""
    with open(config_path) as f:
        config = yaml.safe_load(f)

    changed = get_changed_files(base)
    violations = []
    warnings = []

    for coupling in config.get("couplings", []):
        sources = coupling["sources"]
        docs = coupling["docs"]
        is_soft = coupling.get("soft", False)
        desc = coupling.get("description", "")

        # Check if any source pattern matches changed files
        source_changed = any(
            matches_pattern(f, pattern)
            for f in changed
            for pattern in sources
        )

        if source_changed:
            # Check if required docs were also changed
            docs_changed = any(d in changed for d in docs)
            if not docs_changed:
                msg = f"{desc}: {docs[0]} not updated"
                if is_soft:
                    warnings.append(msg)
                else:
                    violations.append(msg)

    if warnings:
        print("WARNINGS (soft couplings):")
        for w in warnings:
            print(f"  {w}")

    if violations:
        print("VIOLATIONS (strict couplings):")
        for v in violations:
            print(f"  {v}")
        if strict:
            return 1

    return 0

if __name__ == "__main__":
    base = "origin/main"
    for i, arg in enumerate(sys.argv):
        if arg == "--base" and i + 1 < len(sys.argv):
            base = sys.argv[i + 1]
    strict = "--strict" in sys.argv
    sys.exit(check_coupling("scripts/doc_coupling.yaml", base, strict))
```

### 3. Add CI job

```yaml
# In .github/workflows/ci.yml
doc-coupling:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
      with:
        fetch-depth: 0  # Need full history for git diff
    - uses: actions/setup-python@v5
      with:
        python-version: "3.11"
    - name: Install PyYAML
      run: pip install pyyaml
    - name: Check doc-code coupling
      run: python scripts/check_doc_coupling.py --base origin/main --strict
```

### 4. Add "Last verified" convention

Each doc should have a header:

```markdown
# Engine Architecture

Last verified: 2024-01-15

---

Content here...
```

The escape hatch: if code changed but docs are already accurate, update the date.

## Usage

```bash
# Check for violations (CI mode)
python scripts/check_doc_coupling.py --base origin/main --strict

# See what docs you should update
python scripts/check_doc_coupling.py --suggest

# Validate config file (check all paths exist)
python scripts/check_doc_coupling.py --validate-config

# Check against a different base
python scripts/check_doc_coupling.py --base HEAD~5
```

### Handling Violations

**Option 1: Update the doc** (preferred)
```bash
# Edit the coupled doc
vim docs/architecture/engine.md
# Update "Last verified" date
# Commit both source and doc together
```

**Option 2: Escape hatch** (if doc is already accurate)
```bash
# Just update the "Last verified" date in the doc
# This satisfies the coupling check
```

## Customization

### Coupling types

```yaml
# Strict (default) - CI fails
- sources: ["src/core/*.py"]
  docs: ["docs/core.md"]
  description: "Core module docs"

# Soft - CI warns only
- sources: ["src/**/*.py"]
  docs: ["CHANGELOG.md"]
  description: "Changelog reminder"
  soft: true
```

### Glob patterns

```yaml
sources:
  - "src/api/*.py"           # All .py in api/
  - "src/api/**/*.py"        # All .py in api/ recursively
  - "src/core/engine.py"     # Specific file
  - "config/*.yaml"          # All yaml in config/
```

### Multiple docs per source

```yaml
- sources:
    - "src/public_api.py"
  docs:
    - "docs/api-reference.md"
    - "docs/getting-started.md"
    - "README.md"
  description: "Public API affects multiple docs"
```

### Bidirectional coupling

For docs that should trigger source review:

```yaml
- sources:
    - "docs/api-reference.md"
  docs:
    - "src/public_api.py"
  description: "API doc changes should be reflected in code"
  soft: true  # Usually soft - doc changes don't always need code changes
```

## Limitations

- **Git-based** - Only works with git. Requires `fetch-depth: 0` in CI.
- **File-level granularity** - Can't couple specific functions to specific doc sections.
- **No content validation** - Doesn't check if the doc update is meaningful.
- **Escape hatch can be abused** - Someone can always just update the date without reading.

## See Also

- [Git hooks pattern](06_git-hooks.md) - Can run doc-coupling check pre-commit
- [Plan workflow pattern](15_plan-workflow.md) - Plans are a form of doc-code coupling

# Pattern: Architecture Decision Records (ADR)

## Problem

Architectural decisions get lost. Months later:
- No one remembers WHY something was built a certain way
- New developers (or AI assistants) repeat old mistakes
- Refactoring breaks things because constraints weren't documented
- Debates recur because the original reasoning wasn't recorded

## Solution

1. Record each significant architectural decision as an ADR
2. ADRs are **immutable** - once accepted, never edited
3. If a decision changes, create a new ADR that supersedes the old one
4. Link ADRs to source files via governance headers
5. CI enforces governance sync

## Files

| File | Purpose |
|------|---------|
| `docs/adr/NNNN-title.md` | Individual decision records |
| `docs/adr/README.md` | Index of all ADRs |
| `docs/adr/TEMPLATE.md` | Template for new ADRs |
| `scripts/governance.yaml` | File-to-ADR mappings (can be unified into `relationships.yaml`) |
| `scripts/sync_governance.py` | Sync governance headers to source |

## Setup

### 1. Create ADR directory

```bash
mkdir -p docs/adr
```

### 2. Create README

```markdown
# Architecture Decision Records

| ADR | Title | Status |
|-----|-------|--------|
| [0001](../adr/0001-acceptance-gate-terminology.md) | Example decision | Accepted |

## Statuses

| Status | Meaning |
|--------|---------|
| Proposed | Under discussion |
| Accepted | Decision made, in effect |
| Deprecated | No longer applies |
| Superseded | Replaced by another ADR |
```

### 3. Create template

```markdown
# ADR-NNNN: Title

**Status:** Proposed
**Date:** YYYY-MM-DD

## Context

What is the issue motivating this decision?

## Decision

What is the change we're making?

## Consequences

### Positive
- Benefit 1

### Negative
- Trade-off 1

## Related
- Gap #N (if applicable)
- Other ADRs
```

### 4. Create governance config (optional)

```yaml
# scripts/governance.yaml
governance:
  - files:
      - "src/core/engine.py"
      - "src/core/runner.py"
    adrs:
      - "0001-example"
    description: "Core engine architecture"
```

### 5. Create governance sync script (optional)

```python
#!/usr/bin/env python3
"""Sync ADR governance headers to source files."""

import yaml
from pathlib import Path

def sync_governance(config_path: str, apply: bool = False):
    config = yaml.safe_load(Path(config_path).read_text())

    for mapping in config.get("governance", []):
        header = build_header(mapping["adrs"])
        for file_path in mapping["files"]:
            if apply:
                update_file(file_path, header)
            else:
                check_file(file_path, header)

def build_header(adrs: list[str]) -> str:
    lines = ["# --- GOVERNANCE START (do not edit) ---"]
    for adr in adrs:
        lines.append(f"# {adr}")
    lines.append("# --- GOVERNANCE END ---")
    return "\n".join(lines)
```

### 6. Add CI check (optional)

```yaml
governance-sync:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - run: python scripts/sync_governance.py --check
```

## Usage

### Creating a new ADR

```bash
# 1. Copy template
cp docs/adr/TEMPLATE.md docs/adr/0004-my-decision.md

# 2. Edit the file
# - Fill in Context, Decision, Consequences
# - Set Status: Proposed

# 3. Submit PR for discussion

# 4. After approval, change Status to Accepted
```

### Superseding an ADR

```markdown
# ADR-0005: New approach to X

**Status:** Accepted
**Date:** 2024-01-15
**Supersedes:** ADR-0002

## Context

ADR-0002 decided X, but we've learned Y...
```

Then update ADR-0002:
```markdown
**Status:** Superseded by ADR-0005
```

### Checking governance

```bash
# Check if headers are in sync
python scripts/sync_governance.py --check

# Apply headers to source files
python scripts/sync_governance.py --apply
```

## ADR Content Guidelines

### What to Record

| Decision Type | Example |
|---------------|---------|
| Technology choices | "Use PostgreSQL over MongoDB" |
| Architectural patterns | "Event sourcing for audit log" |
| API design | "REST over GraphQL" |
| Security decisions | "JWT tokens with 1h expiry" |
| Trade-offs | "Favor consistency over availability" |

### What NOT to Record

| Not an ADR | Why |
|------------|-----|
| Bug fixes | Not architectural |
| Feature specs | Use product docs |
| How-to guides | Use regular docs |
| Temporary decisions | Not significant enough |

### Good ADR Characteristics

- **One decision per ADR** - Don't bundle multiple decisions
- **Context explains WHY** - Future readers need the reasoning
- **Consequences are honest** - Include trade-offs and risks
- **Immutable** - Never edit accepted ADRs, supersede instead

## Customization

### Numbering schemes

```bash
# Sequential (default)
0001, 0002, 0003...

# Date-based
2024-01-001, 2024-01-002...

# Category-based
SEC-001 (security), API-001 (API design)...
```

### Governance header style

```python
# Python style
# --- GOVERNANCE START ---
# ADR-0001
# --- GOVERNANCE END ---

// JavaScript style
// --- GOVERNANCE START ---
// ADR-0001
// --- GOVERNANCE END ---

<!-- Markdown style -->
<!-- GOVERNANCE: ADR-0001, ADR-0002 -->
```

### Linking to plans/gaps

```markdown
## Related

- Implements Gap #3 (Docker isolation)
- See also: ADR-0001 (foundational decision)
```

## Limitations

- **Overhead** - Writing ADRs takes time
- **Discovery** - People must know to look for ADRs
- **Staleness** - Index can drift if not maintained
- **Scope creep** - Risk of recording non-architectural decisions

## Best Practices

1. **Write ADRs during design, not after** - Capture reasoning while fresh
2. **Keep Context brief but complete** - Future readers need enough to understand
3. **Be honest about trade-offs** - Negative consequences are valuable
4. **Link bidirectionally** - ADRs reference code, code references ADRs
5. **Review ADRs in PRs** - Architecture decisions deserve review

## See Also

- [Doc-code coupling pattern](10_doc-code-coupling.md) - Related enforcement mechanism
- [Plan workflow pattern](15_plan-workflow.md) - ADRs can link to implementation plans
- [Original ADR proposal](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions) by Michael Nygard

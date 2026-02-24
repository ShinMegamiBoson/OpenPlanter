# Pattern: ADR Governance

> **Note:** This pattern originally referenced `governance.yaml`. That file has been
> unified into `relationships.yaml` (Pattern 09). The concepts remain the same;
> only the config file location changed.

## Problem

AI coding assistants (Claude Code, etc.) lose track of architectural decisions over long sessions. They start ignoring ADRs, drifting from established patterns, and making inconsistent choices. By the time you notice, significant rework may be needed.

The core issue: decisions documented in ADRs are invisible when reading code. Claude must proactively check `docs/adr/` to know what decisions apply - and it often doesn't.

## Solution

Make decisions visible at the point of relevance by embedding governance headers directly in source files:

```python
# --- GOVERNANCE START (do not edit) ---
# ADR-0001: Everything is an artifact
# ADR-0003: Contracts can do anything
#
# Permission checks are the hot path - keep them fast.
# Contracts return decisions; kernel applies state changes.
# --- GOVERNANCE END ---
```

When Claude reads a governed file, it immediately sees which ADRs apply and any context about how they apply to this specific file.

**Key properties:**
- Single source of truth: `relationships.yaml` defines file → ADR mappings (see Pattern 09)
- Headers are generated, not manually maintained
- CI enforces sync between config and headers
- Dry-run by default - no accidental modifications

## Files

| File | Purpose |
|------|---------|
| `docs/adr/` | Architecture Decision Records |
| `docs/adr/TEMPLATE.md` | Template for new ADRs |
| `scripts/relationships.yaml` | Unified doc graph including ADR governance (see Pattern 09) |
| `scripts/sync_governance.py` | Generates headers from config |
| `tests/test_sync_governance.py` | Tests for sync script |

## Setup

1. **Create ADR directory:**
```bash
mkdir -p docs/adr
```

2. **Create template and README:**
```bash
# See docs/adr/TEMPLATE.md and docs/adr/README.md in this project
```

3. **Add governance to relationships.yaml:**
```yaml
# scripts/relationships.yaml (governance section)
governance:
  - source: src/core/module.py
    adrs: [1, 3]
    context: |
      Why these ADRs apply to this file.

adrs:
  1:
    title: "Decision title"
    file: "0001-decision-name.md"
```

4. **Copy sync script:**
```bash
# Copy scripts/sync_governance.py from this project
```

5. **Add CI check:**
```yaml
# .github/workflows/ci.yml
governance-sync:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with:
        python-version: "3.11"
    - run: pip install pyyaml
    - run: python scripts/sync_governance.py --check
```

## Usage

**See what needs updating:**
```bash
python scripts/sync_governance.py
```

**Apply changes (requires clean git tree):**
```bash
python scripts/sync_governance.py --apply
```

**Override dirty tree check:**
```bash
python scripts/sync_governance.py --apply --force
```

**Create backups before modifying:**
```bash
python scripts/sync_governance.py --apply --backup
```

**CI check (exit 1 if out of sync):**
```bash
python scripts/sync_governance.py --check
```

**Adding a new ADR:**
1. Copy `docs/adr/TEMPLATE.md` to `docs/adr/NNNN-title.md`
2. Fill in the template
3. Add to `scripts/relationships.yaml` under `adrs:`
4. Add file mappings under `governance:`
5. Run `--apply` to generate headers

## Customization

**Marker format:** Edit `GOVERNANCE_START` and `GOVERNANCE_END` constants in `sync_governance.py`.

**Header content:** Modify `generate_governance_block()` to change what appears in headers.

**Insertion location:** Modify `update_file_content()` to change where headers are inserted (currently after module docstring).

**File types:** Currently supports Python. Extend `validate_python_syntax()` for other languages or remove validation for non-code files.

## Limitations

- **Python-specific syntax validation:** The script validates Python syntax after modification. For other languages, you'd need to add appropriate validators or disable validation.

- **Doesn't prevent ignoring:** A determined (or confused) Claude can still ignore the headers. This pattern makes decisions visible, not enforced.

- **Manual ADR creation:** ADRs themselves must be written manually. This pattern only handles linking them to code.

- **No reverse lookup:** No easy way to ask "what files does ADR-0001 govern?" without reading the YAML. Could add a `--list-files` command.

- **Header location fixed:** Headers always appear after the module docstring (or at top if no docstring). Some codebases may want different placement.

## Safeguards

The sync script includes multiple safeguards to prevent breaking your codebase:

1. **Dry-run by default** - Must explicitly use `--apply` to modify files
2. **Marker-only modification** - Only changes content between GOVERNANCE markers
3. **Syntax validation** - Validates Python syntax before replacing files
4. **Git dirty check** - Refuses to modify files if working tree is dirty (use `--force` to override)
5. **Atomic writes** - Writes to temp file, validates, then replaces original
6. **Backup option** - Creates `.bak` files before modifying

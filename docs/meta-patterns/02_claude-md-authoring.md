# Pattern: CLAUDE.md Authoring

## Problem

AI coding assistants (Claude Code, Cursor, etc.) start each session without project context. They:
- Don't know your conventions
- Don't know your architecture
- Don't know what terminology you use
- Make assumptions that conflict with your design

Result: Wasted time correcting the AI, inconsistent code, violated principles.

## Solution

Create a `CLAUDE.md` file at project root that AI assistants automatically read. Include:
1. Project overview (what this is, what it's NOT)
2. Key commands (how to build, test, run)
3. Design principles (fail loud, no magic numbers, etc.)
4. Terminology (canonical names for concepts)
5. Coordination protocol (if multiple AI instances)

## Files

| File | Purpose |
|------|---------|
| `CLAUDE.md` | Root context file (always loaded) |
| `*/CLAUDE.md` | Directory-specific context (loaded when working in that directory) |

## Setup

### 1. Create root CLAUDE.md

```markdown
# Project Name - Claude Code Context

This file is always loaded. Keep it lean. Reference other docs for details.

## What This Is

[1-2 sentences: what the project does]

## What This Is NOT

[Common misconceptions to prevent]

## Project Structure

```
project/
  src/           # Source code
  tests/         # Test suite
  docs/          # Documentation
  config/        # Configuration
```

## Key Commands

```bash
pip install -e .              # Install
pytest tests/                 # Test
python -m mypy src/           # Type check
```

## Design Principles

### 1. [Principle Name]
[Brief explanation]

### 2. [Principle Name]
[Brief explanation]

## Terminology

| Use | Not | Why |
|-----|-----|-----|
| `term_a` | `term_b` | Consistency |

## References

| Doc | Purpose |
|-----|---------|
| `docs/architecture/` | How things work |
| `docs/GLOSSARY.md` | Full terminology |
```

### 2. Add directory-specific context (optional)

```markdown
# src/CLAUDE.md

## This Directory

Source code for [component].

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | Entry point |
| `utils.py` | Shared utilities |

## Conventions

- All functions must have type hints
- Use `raise RuntimeError()` not `assert` for runtime checks
```

### 3. Keep it lean

The root CLAUDE.md is **always in context**. Every token counts:
- Reference other docs, don't duplicate
- Use tables for dense information
- Omit obvious things

## Usage

### For AI assistants

The file is automatically loaded. No action needed.

### For humans

Review and update when:
- Adding new conventions
- Changing architecture
- Onboarding reveals missing context

### Maintenance

```bash
# Check if CLAUDE.md references exist
grep -r "See \`" CLAUDE.md | while read line; do
  # Verify referenced files exist
done
```

## Content Guidelines

### DO Include

| Content | Example |
|---------|---------|
| Build/test commands | `pytest tests/ -v` |
| Design principles | "Fail loud, no silent fallbacks" |
| Terminology | "Use 'scrip' not 'credits'" |
| File purposes | "config.yaml has runtime values" |
| Anti-patterns | "Never use `except: pass`" |

### DON'T Include

| Content | Why |
|---------|-----|
| Implementation details | Changes frequently, goes stale |
| Full API docs | Too verbose, use references |
| Tutorial content | Not context, it's documentation |
| Aspirational features | Confuses current vs future |

### Size Guidelines

| Section | Target Size |
|---------|-------------|
| Root CLAUDE.md | 200-400 lines |
| Directory CLAUDE.md | 50-100 lines |
| Any single section | <50 lines |

## Customization

### For multi-AI coordination

Add coordination sections:

```markdown
## Active Work

| Instance | Task | Claimed |
|----------|------|---------|
| - | - | - |

## Coordination Protocol

1. Claim before starting
2. Release when done
3. Check claims before starting
```

### For monorepos

```
monorepo/
  CLAUDE.md           # Repo-wide context
  packages/
    api/CLAUDE.md     # API-specific
    web/CLAUDE.md     # Web-specific
```

### For different AI tools

| Tool | File Name | Notes |
|------|-----------|-------|
| Claude Code | `CLAUDE.md` | Auto-loaded |
| Cursor | `.cursorrules` | Different format |
| GitHub Copilot | No equivalent | Use comments |

## Enforcement (Plan #244)

CLAUDE.md files can be enforced via `check_claude_md.py`:

### Three validation types

| Check | What it catches |
|-------|----------------|
| **Existence** | Directories with 2+ tracked files missing a CLAUDE.md |
| **Coverage** | CLAUDE.md files that don't reference all files in their directory |
| **Phantom** | CLAUDE.md references to files that no longer exist |

### Pre-commit integration (progressive)

```bash
# In pre-commit hook — only checks directories touched by staged files
python scripts/check_claude_md.py --staged --strict
```

Progressive enforcement means existing stale files don't block unrelated commits.
But touching a directory forces you to bring its CLAUDE.md current.

### Full audit

```bash
# CI or periodic audit — checks every directory
python scripts/check_claude_md.py --all --strict

# Human-friendly output
python scripts/check_claude_md.py --suggest
```

### Configuration

Exemptions in `scripts/relationships.yaml` under `claude_md:`:

```yaml
claude_md:
  exempt_dirs:
    - "*/static/*"        # Asset directories
    - ".github/*"         # GitHub config
  exempt_files:
    - "CLAUDE.md"         # Doesn't self-reference
    - ".gitignore"        # Infrastructure
```

## Limitations

- **Token cost** - Large files consume context window
- **Tool-specific** - Different AI tools use different files
- **Not enforced** - AI may still ignore instructions

## Anti-Patterns

| Anti-Pattern | Problem |
|--------------|---------|
| Duplicating docs | Goes stale, wastes tokens |
| Too verbose | Crowds out actual work context |
| Aspirational content | Confuses AI about current state |
| No structure | Hard to scan, find information |

## Examples

### Minimal (small project)

```markdown
# MyApp - Claude Context

Python CLI tool for X.

## Commands
```bash
pip install -e . && pytest
```

## Principles
- Type hints required
- No silent failures
```

### Full (large project)

See this project's [CLAUDE.md](../../CLAUDE.md) for a complete example.

## See Also

- [Claim system pattern](worktree-coordination/18_claim-system.md) - Coordination tables in CLAUDE.md
- [Plan workflow pattern](15_plan-workflow.md) - Linking CLAUDE.md to plans
- [Uncertainty Tracking](29_uncertainty-tracking.md) - Session continuity across sessions

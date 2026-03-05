# Pattern: Plan Status Validation

## Problem

Plan statuses can become inconsistent with their content:
- Someone writes a full plan (## Plan, ## Solution sections) but forgets to update status from "❌ Needs Plan" to "📋 Planned"
- Status shows "Planned" but the plan file is empty (missing content)
- Index table diverges from individual plan files

This causes confusion about which plans are ready to implement vs which still need planning.

## Solution

The `sync_plan_status.py` script validates both:
1. **Index ↔ File consistency** - Status in index table matches status in plan file
2. **Status ↔ Content consistency** - Status matches actual content (e.g., has ## Plan section)

## Files

| File | Purpose |
|------|---------|
| `scripts/sync_plan_status.py` | Validation and sync script |
| `docs/plans/CLAUDE.md` | Index table (Gap Summary) |
| `docs/plans/NN_*.md` | Individual plan files |

## Usage

```bash
# Check for ALL inconsistencies (recommended)
python scripts/sync_plan_status.py --check

# Fix status based on content (Needs Plan → Planned)
python scripts/sync_plan_status.py --fix-content

# Sync index to match plan files
python scripts/sync_plan_status.py --sync

# List all plan statuses
python scripts/sync_plan_status.py --list
```

## What Gets Validated

### Index ↔ File Consistency

| Condition | Issue |
|-----------|-------|
| File has 📋 but index has ❌ | Index out of sync |
| File has ✅ but index has 🚧 | Index out of sync |

**Fix:** `--sync` updates index to match files.

### Status ↔ Content Consistency

| Condition | Issue |
|-----------|-------|
| Status = "❌ Needs Plan" but has `## Plan` section | Should be "📋 Planned" |
| Status = "📋 Planned" but missing `## Plan` section | Incomplete plan |

**Fix:** `--fix-content` updates status based on content.

## CI Integration

The `plan-status-sync` CI job runs `--check` on every PR:

```yaml
# .github/workflows/ci.yml
plan-status-sync:
  steps:
    - run: python scripts/sync_plan_status.py --check
```

This catches status inconsistencies before merge.

## Status Lifecycle

```
❌ Needs Plan     →  📋 Planned        →  🚧 In Progress  →  ✅ Complete
(empty file)        (has ## Plan)        (claimed, WIP)      (verified)
```

Transitions:
- **❌ → 📋**: Add `## Plan` section, run `--fix-content`
- **📋 → 🚧**: Claim work, start implementation
- **🚧 → ✅**: Run `complete_plan.py` (records evidence)

## Best Practices

1. **Write plan before claiming** - Add `## Plan` section, update status to 📋
2. **Run `--check` locally** - Catch issues before CI
3. **Don't manually mark Complete** - Use `complete_plan.py` for verification
4. **Index is secondary** - Plan files are source of truth; `--sync` updates index

## Related

- [Plan Workflow](15_plan-workflow.md) - Full plan lifecycle
- [Verification Enforcement](17_verification-enforcement.md) - How plans are completed
- [Claim System](worktree-coordination/18_claim-system.md) - Coordinating who works on what

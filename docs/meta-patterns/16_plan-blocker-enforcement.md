# Pattern: Plan Blocker Enforcement

## Problem

Without blocker chain validation:
- Plans remain "Blocked" after their blockers complete
- Dependency graphs become stale and misleading
- Teams don't know which plans are actually ready to start
- Coordination overhead increases as people manually check dependencies

## Solution

A CI check that validates plan dependency chains:
1. Parses all plan files for "Blocked By" field
2. Cross-references against plan statuses
3. Fails if any plan is blocked by a completed plan
4. Suggests the appropriate new status (Needs Plan, Planned, etc.)

**Key principle:** When a blocker completes, all plans it blocks should be updated to their next logical status.

## Files

| File | Purpose |
|------|---------|
| `scripts/check_plan_blockers.py` | Enforcement script |
| `.github/workflows/ci.yml` | CI job `plan-blockers` |
| `docs/plans/*.md` | Plan files with status and blockers |

## Usage

### Check for stale blockers

```bash
# Report only
python scripts/check_plan_blockers.py

# Fail if issues found (CI mode)
python scripts/check_plan_blockers.py --strict

# Show suggested fixes
python scripts/check_plan_blockers.py --fix

# Apply fixes automatically
python scripts/check_plan_blockers.py --apply
```

### Example output

```
STALE BLOCKERS FOUND

These plans are marked 'Blocked' but their blockers are Complete:

  Plan #7: Single ID Namespace
    Status: Blocked
    Blocked by: #6 (Unified Artifact Ontology)
    Blocker status: Complete
    Suggested new status: Needs Plan
```

### What happens when `--apply` runs

1. Updates status from "Blocked" to suggested status
2. Clears the "Blocked By" field (sets to "None")
3. You must then run `python scripts/sync_plan_status.py --sync` to update the index

## Status Transition Logic

When unblocking, the script determines the new status:

| Plan Contains | New Status |
|---------------|------------|
| "Needs design work" | `Needs Plan` |
| Implementation steps defined | `Planned` |
| Default | `Needs Plan` |

## CI Integration

The `plan-blockers` job runs on every PR:

```yaml
plan-blockers:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with:
        python-version: "3.11"
    - run: python scripts/check_plan_blockers.py --strict
```

This prevents merging PRs that leave stale blockers in the codebase.

## Workflow Integration

### When completing a plan

1. Mark plan as Complete
2. Run `python scripts/check_plan_blockers.py` to see what it unblocks
3. Update the unblocked plans' statuses
4. Run `python scripts/sync_plan_status.py --sync` to update index

Or automate with:
```bash
python scripts/check_plan_blockers.py --apply
python scripts/sync_plan_status.py --sync
```

### When creating a new plan

Always specify blockers explicitly:
```markdown
**Blocked By:** #6, #11
```

Use `None` if no blockers:
```markdown
**Blocked By:** None
```

## Relationship to Other Patterns

| Pattern | Relationship |
|---------|--------------|
| Plan Status Sync | Blocker check runs after, before sync |
| Doc-Code Coupling | Both enforce documentation accuracy |
| Verification Enforcement | Blocker check is a form of plan verification |
| Claim System | Unblocked plans become claimable |

## Limitations

- Only checks direct blockers (not transitive)
- Doesn't validate that blocker numbers exist
- Doesn't prevent circular dependencies
- Status suggestion is heuristic, not always accurate

## Origin

Created after discovering 5 plans marked "Blocked" by already-completed plans during a codebase audit. The enforcement gap meant teams didn't know which plans were ready to start.

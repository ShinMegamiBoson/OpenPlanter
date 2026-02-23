# Pattern: Human-in-the-Loop Verification

## Problem

AI agents can run automated tests, but some things require human verification:
- Visual correctness (dashboards, charts, UI)
- User experience quality
- Integration with external systems the agent can't access
- Subjective quality judgments

Without a formal process, agents may declare work "complete" when they can only verify part of it.

## Solution

Plans can specify a `## Human Review Required` section that:
1. Lists specific items a human must verify
2. Provides step-by-step instructions
3. Blocks automated completion until human confirms

## Plan Format

Add this section to any plan requiring human verification:

```markdown
## Human Review Required

Before marking complete, a human must verify:
- [ ] Dashboard loads at http://localhost:8080
- [ ] Charts render correctly with sample data
- [ ] Navigation between tabs works
- [ ] Responsive layout on mobile viewport

**To verify:**
1. Run `python run.py --dashboard`
2. Open http://localhost:8080 in browser
3. Check each item above
4. Confirm with: `python scripts/complete_plan.py --plan NN --human-verified`
```

## How It Works

### During Automated Completion

When `complete_plan.py` runs on a plan with human review:

1. Runs all automated tests first (unit, E2E, doc-coupling)
2. Detects `## Human Review Required` section
3. Prints the checklist and instructions
4. Exits without marking complete
5. Requires `--human-verified` flag to proceed

```bash
$ python scripts/complete_plan.py --plan 40

============================================================
Completing Plan #40
============================================================
...
============================================================
HUMAN REVIEW REQUIRED
============================================================

Plan #40 requires manual verification before completion.

From 40_dashboard.md:
----------------------------------------
Before marking complete, a human must verify:
- [ ] Dashboard loads at http://localhost:8080
- [ ] Charts render correctly with sample data
...
----------------------------------------

After verifying all items above, run:

  python scripts/complete_plan.py --plan 40 --human-verified

This confirms a human has checked things automated tests cannot verify.

❌ Cannot complete: human review required but --human-verified not provided
```

### After Human Verification

Once a human has verified the checklist:

```bash
$ python scripts/complete_plan.py --plan 40 --human-verified

============================================================
Completing Plan #40
============================================================
...
  (--human-verified: human review confirmed)

[1/3] Running unit tests...
    PASSED: ...

✅ Plan #40 marked COMPLETE
```

## When to Use

Add human review when the plan involves:

| Category | Examples |
|----------|----------|
| **Visual** | Dashboards, charts, CSS styling, responsive design |
| **UX** | Navigation flows, form usability, error messages |
| **External** | Third-party API integrations, email delivery |
| **Subjective** | Documentation quality, naming conventions |

## When NOT to Use

Skip human review for:
- Pure backend logic (testable with unit tests)
- API contracts (testable with integration tests)
- Data transformations (testable with property tests)
- CLI tools (testable with E2E tests)

## Best Practices

1. **Be specific** - List exact URLs, commands, and expected outcomes
2. **Keep it short** - 3-5 items max, human attention is limited
3. **Include setup** - Tell the human how to run/access the feature
4. **Chain items** - Order matters for verification steps

## Example: Dashboard Plan

```markdown
# Plan #40: Agent Balance Dashboard

**Status:** 🚧 In Progress

## Problem
Need to visualize agent balances over time.

## Required Tests
- tests/unit/test_dashboard.py::test_data_endpoint
- tests/integration/test_dashboard.py::test_server_starts

## Human Review Required

Before marking complete, a human must verify:
- [ ] Dashboard loads at http://localhost:8080
- [ ] Balance chart shows correct agent data
- [ ] Legend toggles work to show/hide agents
- [ ] Timerange selector updates the chart

**To verify:**
1. Start simulation: `python run.py --agents 3 --ticks 10`
2. Start dashboard: `python -m src.dashboard.server`
3. Open http://localhost:8080
4. Verify each checkbox above
5. Confirm: `python scripts/complete_plan.py --plan 40 --human-verified`

## Solution
...
```

## Related

- [Verification Enforcement](17_verification-enforcement.md) - Overall completion requirements
- [Plan Workflow](15_plan-workflow.md) - Full plan lifecycle
- [Testing Strategy](03_testing-strategy.md) - Test types and when to use each

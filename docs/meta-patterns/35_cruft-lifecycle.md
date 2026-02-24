# Pattern 35: Cruft Lifecycle

## Problem

Projects accumulate cruft over time — dead code, stale docs, patches on patches,
abstractions that fight the problem. Without a systematic way to detect and
respond to cruft, the codebase degrades until a painful rewrite is needed.

## Solution

Use quantitative and qualitative signals to detect cruft, then decide:
iterate (fix incrementally) or converge (restructure/rebuild).

### Quantitative Signals

| Signal | Tool | Threshold |
|--------|------|-----------|
| Dead code % | vulture / knip | >5% of codebase |
| Test failure rate | pytest --tb=no | >10% of test suite |
| Churn rate | git log --numstat | Same files changed >3x in 2 weeks |
| Doc staleness | file mtime | CLAUDE.md >30 days old |
| Unused dependencies | pip-audit / depcheck | >3 unused deps |

### Qualitative Signals

- **Abstraction fighting the problem**: The code structure doesn't match the domain.
  You're working around the architecture, not with it.
- **Fixes on fixes**: Each bug fix introduces a new edge case. The fix graph is growing.
- **Copy-paste divergence**: Similar code in multiple places that's drifted apart.
- **Fear of touching**: "Don't change that, it'll break everything."

### Decision Framework

1. **1 red signal** → Note it. Continue working.
2. **2+ red signals** → Convergence check. Ask:
   - Is the current approach still sound? (If yes → iterate, fix signals)
   - Has the problem changed? (If yes → redesign the affected component)
3. **3+ red signals sustained over 2 weeks** → Full rebuild evaluation.
   Write a plan comparing iterate-cost vs rebuild-cost.

### Integration with Beach Mode

The `ecosystem_sweep.py` script detects quantitative signals automatically.
The `task_planner.py` uses sweep output to generate hygiene tasks (30% of budget).
Decisions about iterate vs rebuild are recorded in `decision_log.py` with
confidence scores for Brian's review.

## Files

- `scripts/ecosystem_sweep.py` — Quantitative signal detection
- `meta-process/scripts/check_dead_code.py` — Dead code detection
- `ops/openclaw/task_planner.py` — Generates tasks from signals

## Requires

- Pattern 15 (Plan Workflow) — for tracking rebuild plans
- Pattern 29 (Uncertainty Tracking) — for recording iterate/rebuild uncertainty

## Limitations

- Qualitative signals require human judgment (LLM can flag but not decide)
- Churn rate calculation requires git history access
- The 2-signal threshold is a heuristic, not a formula

# Pattern: Ownership Respect

Prevent Claude Code instances from interfering with each other's work.

## Problem

When multiple CC instances work in parallel:
1. Instance A sees Instance B's blocked PR and offers to "fix" it
2. Instance A doesn't know B's context, uncommitted changes, or intent
3. A's "fix" may break B's work or duplicate effort
4. B returns to find their work modified unexpectedly

Root cause: CC instances default to being helpful by fixing problems they see, without checking if it's their problem to fix.

## Solution

**Priority 0: Check ownership before acting.** Before recommending any action on a PR or claimed work:

1. Run `python scripts/meta_status.py` and check the "Yours?" column
2. Only act on items marked "✓ YOURS"
3. For "NOT YOURS" items: note status only, do not fix/merge/modify

**What's allowed on others' work:**
- Read code and understand changes
- Review and provide feedback
- Run tests locally to understand behavior
- Note status in recommendations

**What's NOT allowed on others' work:**
- Fix CI failures
- Resolve merge conflicts
- Push commits
- Merge PRs
- Complete or release claims

## Files

| File | Purpose |
|------|---------|
| `scripts/meta_status.py` | Shows "Yours?" column for PRs and claims |
| `CLAUDE.md` | Priority 0 ownership check in Work Priorities |
| `.claude/commands/proceed.md` | /proceed skill includes ownership verification |

## Setup

1. Add Priority 0 to CLAUDE.md Work Priorities section
2. Ensure meta_status.py shows owner/yours info
3. Update /proceed skill to require ownership check
4. Add this pattern doc to meta-process/patterns/

## Usage

**When starting any task:**
```bash
python scripts/meta_status.py
```

Look at output - each PR and claim shows:
- **Owner**: Who created/claimed it
- **Yours?**: "✓ YOURS" or "NOT YOURS"

**In /proceed recommendations:**
```
> **Recommended:** [action]
> **Ownership:** ✓ YOURS / NOT YOURS
> **Alignment:** Priority #N
```

If NOT YOURS, use Status format instead:
```
> **Status:** PR #X is blocked on CI
> **Ownership:** NOT YOURS (owned by: plan-X-feature)
> **Action:** Review/feedback allowed; do not fix or merge
```

## Customization

The ownership check uses:
- Current git branch to identify "self"
- Claims file to match cc_id to branch
- PR author from GitHub API

For projects without claims system, use PR author comparison only.

## Limitations

- Doesn't prevent deliberate override (CC can still force)
- Requires honest self-identification via branch
- Handoff requires explicit coordination in claims table
- Session continuity may need re-claiming after context loss

## Origin

Created after repeated observations of CC instances offering to "help" fix other instances' blocked PRs, leading to confusion, duplicate work, and ownership violations. Plan #71 implemented this enforcement pattern.

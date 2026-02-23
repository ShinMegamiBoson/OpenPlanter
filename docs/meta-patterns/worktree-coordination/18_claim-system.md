# Pattern: Claim System

## Problem

When multiple AI instances (or developers) work in parallel:
- Two instances start the same work
- Neither knows the other is working
- Merge conflicts, wasted effort, confusion

## Solution: Structured Scope Claims

Claims must specify a **scope** - either a plan number or a feature name:

```bash
# Claim a feature (recommended for most work)
python scripts/check_claims.py --claim --feature ledger --task "Fix transfer bug"

# Claim a plan (for gap implementations)
python scripts/check_claims.py --claim --plan 3 --task "Docker isolation"

# Claim both (for plan work that touches specific features)
python scripts/check_claims.py --claim --feature escrow --plan 8 --task "Agent rights"
```

**Scopes are mutually exclusive** - if CC-2 claims `--feature ledger`, CC-3 cannot claim the same feature until CC-2 releases.

## Scope Types

| Scope | Source | Example |
|-------|--------|---------|
| **Feature** | `acceptance_gates/*.yaml` | `--feature ledger`, `--feature escrow` |
| **Plan** | `docs/plans/*.md` | `--plan 3`, `--plan 21` |

### Feature Scopes

Features are defined in `acceptance_gates/*.yaml`. Each feature lists its code files:

```yaml
# acceptance_gates/ledger.yaml
feature: ledger
code:
  - src/world/ledger.py
  - src/world/rate_tracker.py
```

When you claim `--feature ledger`, you're claiming ownership of those files.

### Plan Scopes

Plans are numbered implementation tasks in `docs/plans/`. Claiming `--plan 3` means you're working on Plan #3.

## Commands

### List available features

```bash
python scripts/check_claims.py --list-features

# Output:
# Available features:
#   - contracts
#   - escrow
#   - ledger
#   - meta-process-tooling
# Files mapped to features: 9
```

### Claim work

```bash
# Feature claim (recommended)
python scripts/check_claims.py --claim --feature ledger --task "Fix transfer bug"

# Plan claim
python scripts/check_claims.py --claim --plan 3 --task "Docker isolation"

# Both
python scripts/check_claims.py --claim --feature escrow --plan 8 --task "Agent rights"
```

### Check for conflicts before claiming

```bash
# List current claims to see what's taken
python scripts/check_claims.py --list
```

### Check if files are covered by claims

```bash
# CI mode - verify files are claimed
python scripts/check_claims.py --check-files src/world/ledger.py src/world/executor.py

# Output if unclaimed:
# ❌ Files not covered by claims:
#   - src/world/ledger.py
# To fix, claim the feature that owns these files:
#   python scripts/check_claims.py --claim --feature ledger --task '...'
```

### Release claim

```bash
python scripts/check_claims.py --release

# With TDD validation
python scripts/check_claims.py --release --validate
```

### CI verification

```bash
# Verify current branch has a claim
python scripts/check_claims.py --verify-claim
```

## Enforcement

### At Claim Time

When you claim, the system blocks if:
- **Same plan** is already claimed by another instance
- **Same feature** is already claimed by another instance

```bash
$ python scripts/check_claims.py --claim --feature ledger --task "My work"

============================================================
❌ SCOPE CONFLICT - CLAIM BLOCKED
============================================================

  Feature 'ledger' already claimed by: other-branch
  Their task: Fix transfer bug

------------------------------------------------------------
Each plan/feature can only be claimed by one instance.
Coordinate with the other instance before proceeding.

Use --force to claim anyway (NOT recommended).
```

### In CI

CI checks that PR branches were claimed. Currently informational, will become strict.

## Files

| File | Purpose |
|------|---------|
| `.claude/active-work.yaml` | Machine-readable claim storage (local, not git-tracked) |
| `scripts/check_claims.py` | Claim management script |
| `acceptance_gates/*.yaml` | Feature definitions with code mappings |

## Workflow

1. **Check what's claimed**: `python scripts/check_claims.py --list`
2. **Check available features**: `python scripts/check_claims.py --list-features`
3. **Claim your scope**: `python scripts/check_claims.py --claim --feature NAME --task "..."`
4. **Create worktree**: `make worktree BRANCH=my-feature`
5. **Do work**: Edit files in the claimed feature's scope
6. **Release**: `python scripts/check_claims.py --release`

## Best Practices

1. **Always specify a scope** - Use `--feature` or `--plan` when claiming
2. **Check claims first** - `--list` before starting any work
3. **One scope at a time** - Don't claim more than you need
4. **Release promptly** - Don't hold claims overnight
5. **Use features for code work** - Plans are for gap implementations

## Special Scopes

### Shared Scope

Cross-cutting files that many features use (config, fixtures, types) are in the `shared` scope:

```yaml
# acceptance_gates/shared.yaml
feature: shared
code:
  - src/config.py
  - tests/conftest.py
  - tests/fixtures/
```

**Shared files have no claim conflicts** - any plan can modify them without claiming the shared feature. This prevents false conflicts on common infrastructure.

### Trivial Changes

Changes with `[Trivial]` prefix don't require claims:
- Typo fixes
- Comment updates
- Formatting changes
- Changes < 20 lines not touching `src/`

```bash
git commit -m "[Trivial] Fix typo in README"
# No plan or claim required
```

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Claim granularity | **Feature-level** | File-level is over-restrictive; git handles merges fine. Feature-level prevents duplicate work without blocking valid parallel changes. |
| File lists in plans | **Not required** | Impractical to maintain; files derived from feature's `code:` section instead. |
| Shared scope | **No claim conflicts** | Cross-cutting files shouldn't block anyone; tests are the quality gate. |
| Trivial exemption | **`[Trivial]` prefix** | Reduces friction for tiny fixes; CI validates size limits. |

**Evidence considered:**
- DORA research: deployment frequency > process rigor
- Trunk-based development: small changes + trust git
- Google/Spotify: anyone can modify common code, tests are the gate

## Limitations

- **CI check is informational** - Currently warns but doesn't block (will be strict later)
- **Force override exists** - `--force` can bypass conflicts (for emergencies only)
- **Files outside features** - Files not in any `acceptance_gates/*.yaml` aren't tracked
- **Shared scope honor system** - Anyone can modify shared files; abuse visible in git history

## Alternative: Messaging

For direct communication between instances without PR workflows:

```bash
# Send a message to another instance
python scripts/send_message.py --to plan-83-feature --type suggestion --subject "Review feedback" --content "..."

# Check your inbox
python scripts/check_messages.py --list
```

**When to use messaging vs claims:**
- **Claims**: Ownership of work scope (prevents conflicts)
- **Messaging**: Suggestions, questions, handoffs, reviews (async communication)

See root `CLAUDE.md` > Multi-Claude Coordination > Inter-CC Messaging for details.

## See Also

- [Worktree Enforcement](19_worktree-enforcement.md) - Worktree + claim workflow
- [PR Coordination](21_pr-coordination.md) - PR workflow with claims
- [Plan Workflow](../15_plan-workflow.md) - Plans that claims reference
- [Acceptance-Gate-Driven Development](../13_acceptance-gate-driven-development.md) - Acceptance gate definitions

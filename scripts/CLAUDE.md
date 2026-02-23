# Scripts Directory

Utility scripts for development and CI. All scripts support `--help` for options.

## Core Scripts

| Script | Purpose |
|--------|---------|
| `check_plan_tests.py` | Verify/run plan test requirements |
| `complete_plan.py` | Mark plan complete |
| `sync_plan_status.py` | Sync plan status |
| `merge_pr.py` | Merge PRs via GitHub CLI |
| `check_doc_coupling.py` | Verify docs updated when source changes |

## Common Commands

```bash
# Plan tests
python scripts/check_plan_tests.py --plan N        # Run tests for plan
python scripts/check_plan_tests.py --plan N --tdd  # See what tests to write

# Plan completion
python scripts/complete_plan.py --plan N           # Mark complete

# Doc coupling
python scripts/check_doc_coupling.py --suggest     # What docs to update
```

## Worktree Coordination Scripts (opt-in)

If using the worktree coordination module, these additional scripts are available
in `scripts/worktree-coordination/`:

| Script | Purpose |
|--------|---------|
| `check_claims.py` | Manage active work claims |
| `meta_status.py` | Dashboard: claims, PRs, progress |
| `finish_pr.py` | Complete PR lifecycle: merge + cleanup |
| `safe_worktree_remove.py` | Safely remove worktrees |
| `check_messages.py` | Inter-CC messaging inbox |
| `send_message.py` | Send messages to other CC instances |

## Configuration

Edit config files in repo root to customize behavior:
- `meta-process.yaml` - Meta-process settings
- `scripts/relationships.yaml` - Doc-code mappings

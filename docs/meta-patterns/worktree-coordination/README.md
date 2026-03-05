# Worktree Coordination Module

Optional module for teams running **multiple AI coding instances concurrently** on the same codebase.

## When to Use This

Enable this module when:
- 3+ AI instances work on the same repo simultaneously
- You experience merge conflicts from parallel work
- Instances start the same task without knowing about each other

**Most projects don't need this.** A simple branch-based workflow (one instance at a time) is simpler and sufficient.

## What It Provides

**Claims** — Branch-based coordination that prevents two instances from working on the same plan:
- See [18_claim-system.md](18_claim-system.md)

**Worktree Enforcement** — File isolation via git worktrees so each instance has its own working directory:
- See [19_worktree-enforcement.md](19_worktree-enforcement.md)

**Rebase Workflow** — Prevents "reverted" changes when worktrees get stale:
- See [20_rebase-workflow.md](20_rebase-workflow.md)

**PR Coordination** — Tracks review requests between instances:
- See [21_pr-coordination.md](21_pr-coordination.md)

## CWD Safety

When using worktrees, **never cd into a worktree directory**. The AI instance's working directory must always be the main repo root. If a worktree is deleted while the shell is inside it, all subsequent commands fail silently.

Use `git -C worktrees/plan-N-foo` for git operations instead of changing directories.

The `block-cd-worktree.sh` hook (in `hooks/claude/worktree-coordination/`) enforces this automatically.

## Setup

1. Enable claims in `meta-process.yaml`:
   ```yaml
   claims:
     enabled: true
   ```

2. Register worktree hooks in `.claude/settings.json` (see hook files in `hooks/claude/worktree-coordination/`)

3. Add worktree targets to your Makefile (see `templates/Makefile.meta` for examples)

## Related Scripts

Located in `scripts/worktree-coordination/`:
- `check_claims.py` — Claim management (create, release, list, validate)
- `safe_worktree_remove.py` — Safe worktree removal with checks
- `finish_pr.py` — PR merge + worktree cleanup + claim release
- `check_messages.py` — Inter-instance inbox checking
- `send_message.py` — Send messages between instances

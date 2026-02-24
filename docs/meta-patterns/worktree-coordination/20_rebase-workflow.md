# Pattern: Rebase Workflow for Worktrees

## Problem

When multiple Claude Code instances work in parallel using worktrees:

1. Worktree A is created from `main` at commit X
2. Worktree B is created, does work, creates PR, merges to `main` (now at commit Y)
3. Worktree A creates PR but:
   - PR is based on outdated commit X
   - May conflict with changes from B
   - Merging may accidentally revert B's work
   - CLAUDE.md or other shared files appear "reverted"

This isn't actually a revert - it's that A's branch never had B's changes.

## Solution

Three-part solution:

1. **Start fresh**: `make worktree` auto-fetches and bases on latest `origin/main`
2. **Before PR**: `make pr-ready` rebases onto current `origin/main` and pushes safely
3. **GitHub enforcement**: Branch protection requires PRs to be up-to-date before merge

### GitHub Branch Protection (Enforcement)

Branch protection on `main` with `strict: true` means GitHub will **block merge** if your branch is behind `origin/main`. This catches cases where developers forget to run `make pr-ready`.

```bash
# Check current protection settings
gh api repos/OWNER/REPO/branches/main/protection --jq '.required_status_checks.strict'
# Should return: true

# Enable if not set (requires admin)
gh api repos/OWNER/REPO/branches/main/protection -X PUT --input - <<'EOF'
{
  "required_status_checks": {"strict": true, "contexts": ["test"]},
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null
}
EOF
```

When strict mode is enabled, GitHub shows "This branch is out-of-date with the base branch" and the merge button is disabled until you rebase.

## Files

| File | Purpose |
|------|---------|
| `Makefile` | `worktree`, `rebase`, `pr-ready` targets |
| `CLAUDE.md` | Workflow documentation (step 6) |

## Setup

The targets are already in the Makefile:

```makefile
worktree:  ## Create worktree for parallel CC work (usage: make worktree BRANCH=feature-name)
	@if [ -z "$(BRANCH)" ]; then echo "Usage: make worktree BRANCH=feature-name"; exit 1; fi
	git fetch origin
	git worktree add ../ecology-$(BRANCH) -b $(BRANCH) origin/main
	@echo ""
	@echo "Worktree created at ../ecology-$(BRANCH) (based on latest origin/main)"
	@echo "To use: cd ../ecology-$(BRANCH) && claude"
	@echo "To remove when done: git worktree remove ../ecology-$(BRANCH)"

rebase:  ## Rebase current branch onto latest origin/main
	git fetch origin
	git rebase origin/main

pr-ready:  ## Rebase and push (run before creating PR)
	git fetch origin
	git rebase origin/main
	git push --force-with-lease
```

## Usage

### Creating a Worktree (Always Fresh)

```bash
# In main directory
make worktree BRANCH=plan-03-docker

# Automatically:
# 1. Fetches latest from remote
# 2. Creates worktree based on origin/main (not local main)
# 3. Shows path and usage instructions
```

### Before Creating PR

```bash
# In your worktree
make pr-ready

# Automatically:
# 1. Fetches latest from remote
# 2. Rebases your branch onto origin/main
# 3. Pushes with --force-with-lease (safe force push)
```

### Just Rebase (No Push)

```bash
# In your worktree
make rebase

# Rebases but doesn't push - useful for:
# - Checking for conflicts before you're ready
# - Getting latest changes during long-running work
```

## Conflict Resolution

If rebase finds conflicts:

```bash
# 1. Git will stop and show conflicted files
Auto-merging CLAUDE.md
CONFLICT (content): Merge conflict in CLAUDE.md

# 2. Fix conflicts in your editor
# Look for <<<<<<< HEAD, =======, >>>>>>> markers

# 3. Stage resolved files
git add CLAUDE.md

# 4. Continue rebase
git rebase --continue

# 5. If you want to abort and try again later
git rebase --abort
```

### Common Conflict Scenarios

| Scenario | Resolution |
|----------|------------|
| CLAUDE.md Active Work table | Keep remote's table, add your entry |
| Same file modified | Keep both changes if independent, merge if overlapping |
| File deleted vs modified | Usually keep the modification |

## Understanding `--force-with-lease`

Regular `git push --force` overwrites remote unconditionally. This is dangerous if someone else pushed while you were rebasing.

`--force-with-lease` is safer:
- Checks that remote ref hasn't changed since you fetched
- If someone else pushed in between, it fails instead of overwriting
- You then fetch again, rebase, and retry

```bash
# Safe: fails if remote changed
git push --force-with-lease

# Dangerous: overwrites unconditionally (avoid)
git push --force
```

## Workflow Integration

The full workflow from CLAUDE.md:

1. **Claim** - `make claim TASK="..." PLAN=N`
2. **Worktree** - `make worktree BRANCH=plan-NN-description` (auto-fetches)
3. **Update plan status** - Mark "In Progress"
4. **Implement** - Do work, write tests first (TDD)
5. **Verify** - Run all checks
6. **Rebase** - `make pr-ready` (rebase onto latest main, push)
7. **PR** - Create PR from worktree
8. **Review** - Another CC instance reviews
9. **Complete** - Merge PR, remove worktree

Step 6 is critical for preventing "reverted" changes.

## Limitations

- **Requires conflict resolution skills** - Rebasing can produce conflicts that need manual resolution
- **Force push required** - After rebase, history changes, requiring force push
- **Not for shared branches** - Only use for personal feature branches, never for branches others are working on

## Related Patterns

- [Worktree Enforcement](19_worktree-enforcement.md) - Blocks edits in main directory
- [PR Coordination](21_pr-coordination.md) - Tracks PRs and claims
- [Claim System](18_claim-system.md) - Coordinates which instance works on what

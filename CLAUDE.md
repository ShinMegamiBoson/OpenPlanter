## Stop Checklist

Before completing a task, check each item:

- Did you take advantage of ALL applicable skills?
- Did you take advantage of ALL applicable subagents?
- Don't guess about the state of the code or any APIs unless explicitly asked to
- If something doesn't work, your first priority must always be determine WHY it doesn't work unless doing so is impossible
- If you have written or modified code, ensure all components have been deterministically validated to be functioning as intended via breaking up any given process or change into the most granular steps possible and validating the conditions at the entry and exit of each of those steps
- Do not ask the user to perform an action to validate the correctness of your work, you need to validate it yourself
- If the feature is functionally complete, create a temporary commit now. We'll squash the commits later as needed.


## Multi-Agent Coordination

This repo uses worktree-based isolation for concurrent AI instances.

**Before starting work:**
1. Check existing claims: `python scripts/meta/worktree-coordination/check_claims.py --list`
2. Claim your work: `python scripts/meta/worktree-coordination/check_claims.py --claim --feature <name> --task "description"`
3. Create a worktree: `make worktree` (or `git worktree add worktrees/plan-N-desc`)
4. Work in the worktree, not the main directory

**Before committing:**
- Commits must use prefixes: `[Plan #N]`, `[Trivial]`, or `[Unplanned]`
- Release claims when done: `python scripts/meta/worktree-coordination/check_claims.py --release`

**Check for messages from other instances:**
`python scripts/meta/worktree-coordination/check_messages.py`


# Pattern: Worktree Enforcement

## Problem

Multiple Claude Code instances working in the same directory causes:
- Uncommitted changes from one instance overwritten by another
- Branch switches mid-edit
- Merge conflicts from parallel uncommitted work
- Lost work when instances don't coordinate
- **Unclaimed worktrees** - Work happens without other instances knowing who's working on what

Git worktrees solve the isolation problem by giving each instance its own working directory, but there's no enforcement - instances can still accidentally edit the main directory or work in worktrees without claiming them.

## Solution

Three-part enforcement:

1. **`make worktree` requires claiming** - The worktree creation script prompts for task description and plan number, creating a claim before the worktree. This ensures all instances can see what others are working on.

2. **PreToolUse hook blocks edits in main** - A hook blocks Edit/Write operations when the target file is in the main repository directory (not a worktree).

3. **PreToolUse hook blocks edits in unclaimed worktrees** - The same hook verifies that worktrees have an active claim before allowing edits. This prevents the "orphan work" problem where an instance edits files without claiming, leaving other instances unable to tell who's working there.

## Creating a Worktree (with mandatory claim)

```bash
make worktree
```

This runs an interactive script that:
1. Shows existing claims
2. Prompts for task description (required)
3. Prompts for plan number (optional)
4. Suggests branch name based on plan
5. Creates the claim
6. Creates the worktree

See [Claim System](18_claim-system.md) for details on the claim system.

## Hook-Based Enforcement

The PreToolUse hook blocks Edit/Write operations in the main directory.

### Files

| File | Purpose |
|------|---------|
| `.claude/settings.json` | Hook configuration |
| `.claude/hooks/protect-main.sh` | Blocks Edit/Write operations in main directory |
| `.claude/hooks/block-worktree-remove.sh` | Blocks `git worktree remove` Bash commands |

## Setup

1. **Create hooks directory:**
   ```bash
   mkdir -p .claude/hooks
   ```

2. **Create the protection script** (`.claude/hooks/protect-main.sh`):
   ```bash
   #!/bin/bash
   MAIN_DIR="/path/to/your/main/repo"

   INPUT=$(cat)
   FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

   if [[ -z "$FILE_PATH" ]]; then
       exit 0
   fi

   if [[ "$FILE_PATH" == "$MAIN_DIR"/* ]]; then
       echo "BLOCKED: Cannot edit files in main directory" >&2
       echo "Create a worktree: git worktree add ../feature -b feature" >&2
       exit 2
   fi

   exit 0
   ```

3. **Make it executable:**
   ```bash
   chmod +x .claude/hooks/protect-main.sh
   ```

4. **Create settings.json** (`.claude/settings.json`):
   ```json
   {
     "hooks": {
       "PreToolUse": [
         {
           "matcher": "Edit|Write",
           "hooks": [
             {
               "type": "command",
               "command": "bash .claude/hooks/protect-main.sh",
               "timeout": 5000
             }
           ]
         }
       ]
     }
   }
   ```

5. **Update .gitignore** to track these files:
   ```
   # Track enforcement hooks
   !.claude/settings.json
   !.claude/hooks/
   ```

## Usage

Once installed, Claude Code instances in the main directory will see:

```
BLOCKED: Cannot edit files in main directory (/path/to/repo)

You're in the main directory. Create a worktree first:
  make worktree BRANCH=plan-NN-description

Or use an existing worktree:
  make worktree-list
```

The Edit/Write operation will be blocked, forcing the instance to use a worktree.

## Claim Enforcement in Worktrees

The hook also enforces that worktrees have active claims. If you try to edit a file in a worktree that has no matching claim in `.claude/active-work.yaml`:

```
BLOCKED: Worktree has no active claim

Branch 'plan-64-impl' has no claim in .claude/active-work.yaml

Create a claim first:
  python scripts/check_claims.py --claim --task 'description' --id plan-64-impl

Or if this is abandoned work, remove the worktree:
  make worktree-remove BRANCH=plan-64-impl

File: /path/to/file.py
```

### Why This Matters

Without claim enforcement, a CC instance could:
1. Use `git worktree add` directly (bypassing `make worktree`)
2. Start editing files
3. Other instances see "ACTIVE (no claim)" in `check_claims.py --list`
4. No one knows who's working there or on what task

With claim enforcement:
- Edits are blocked until a claim exists
- The instance must declare what they're working on
- Other instances can see the task description
- Coordination is maintained

### How Claims Are Matched

The hook matches the worktree's branch name against `cc_id` values in `.claude/active-work.yaml`:

```yaml
claims:
- cc_id: plan-64-impl          # Must match branch name
  task: Implement dependency graph
  claimed_at: '2026-01-18T00:39:00Z'
```

If the worktree branch is `plan-64-impl`, the hook looks for `cc_id: plan-64-impl` in the claims file.

## Coordination Files (Whitelisted)

The hook allows editing **coordination files** even in main directory:

| Pattern | Files | Why Allowed |
|---------|-------|-------------|
| `*/.claude/*` | `.claude/active-work.yaml` | Claims tracking |
| `CLAUDE.md` | All `CLAUDE.md` files | Coordination tables, plan status |
| `meta-process/patterns/*.md` | Meta-process patterns | Process docs, not implementation |

This enables the "Reviews, quick reads, coordination only" workflow in main while blocking implementation work.

## Plan File Exception

The hook allows **creating new plan files** from main directory:

| Pattern | Condition | Why Allowed |
|---------|-----------|-------------|
| `docs/plans/[0-9]+_*.md` | File does NOT exist | Plans are coordination artifacts, not implementation |

**What's allowed:**
- Creating `docs/plans/85_inter_cc_messaging.md` (new file)
- Creating any new plan file matching the `NN_name.md` pattern

**What's still blocked:**
- Modifying existing plan files (could conflict with claiming instance)
- Modifying `docs/plans/CLAUDE.md` (the index file)
- Any other implementation files in main

**Rationale:** Creating a new plan is coordination work - it documents intended work and enables other instances to see what's planned. Requiring a worktree just to create a markdown planning file adds friction without meaningful benefit. However, modifying existing plans could conflict with an instance that has claimed that plan, so modifications still require a worktree.

### Example

```bash
# In main directory - ALLOWED (new file)
# CC instance can create docs/plans/85_new_feature.md

# In main directory - BLOCKED (existing file)
# CC instance cannot modify docs/plans/65_continuous_execution_primary.md
# Error: "BLOCKED: Cannot edit files in main directory"
```

## Customization

**Change the main directory path:**
Edit `MAIN_DIR` in `protect-main.sh` to match your repository location.

**Add more exceptions:**
Add patterns to skip enforcement for specific files:
```bash
# Example: Allow a specific config file
if [[ "$BASENAME" == "special-config.yaml" ]]; then
    exit 0
fi
```

**Different branch naming:**
Adjust the error message to match your branch naming convention.

## Limitations

- **Requires jq:** The script uses `jq` to parse JSON input
- **Git-based detection:** Uses `.git` file vs directory to detect worktrees
- **Claim matching by branch name:** The `cc_id` in claims must match the worktree's branch name exactly
- **Read operations allowed:** Only blocks Edit/Write, not Read (intentional - reviewing is fine)
- **Most Bash operations allowed:** Only `git worktree remove` is blocked (prevents shell breakage)
- **Claims file location:** Reads claims from main repo's `.claude/active-work.yaml`, not worktree's copy

## Plan Enforcement Hooks

Two additional hooks enforce plan discipline when working in worktrees.

### File Scope Enforcement

The `check-file-scope.sh` hook blocks edits to files not declared in the plan's `## Files Affected` section.

**Behavior:**
- Extracts plan number from branch name (e.g., `plan-89-hooks` → Plan #89)
- Reads the plan file's `## Files Affected` section
- Blocks edits to undeclared files with helpful error message

**Example block message:**
```
BLOCKED: File not in plan's declared scope

Plan #89 does not list this file in 'Files Affected':
  src/world/ledger.py

To fix, update your plan file:
  docs/plans/89_*.md

Add to '## Files Affected' section:
  - src/world/ledger.py (modify)

This ensures all changes are planned and traceable.
```

**Exceptions (always allowed):**
- `.claude/*` - Coordination files
- `CLAUDE.md` files
- `docs/plans/*` - Plan files themselves
- Main branch (review only)
- Branches without plan numbers (trivial work)

### References Reviewed Warning

The `check-references-reviewed.sh` hook warns (doesn't block) if the plan lacks exploration documentation.

**Behavior:**
- Only triggers on `src/` or `tests/` file edits
- Checks for `## References Reviewed` section with at least 2 entries
- Shows warning once per session (not on every edit)

**Example warning:**
```
========================================
⚠️  EXPLORATION WARNING
========================================

Plan #89 has insufficient 'References Reviewed' (0/2 minimum)

Before implementing, you should:
  1. Explore the existing codebase
  2. Document what you reviewed in the plan

Add to your plan file (docs/plans/89_*.md):

  ## References Reviewed
  - src/relevant/file.py:10-50 - description of what you learned
  - docs/architecture/current/relevant.md - relevant design context

This ensures you understand the codebase before changing it.
(This warning appears once per session)
========================================
```

### Hook Configuration

Both hooks are registered in `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {"type": "command", "command": "bash .claude/hooks/protect-main.sh"},
          {"type": "command", "command": "bash .claude/hooks/check-file-scope.sh"},
          {"type": "command", "command": "bash .claude/hooks/check-references-reviewed.sh"}
        ]
      }
    ]
  }
}
```

### Supporting Script

Both hooks use `scripts/parse_plan.py` to extract plan sections:

```bash
# Check if file is in plan scope
python scripts/parse_plan.py --plan 89 --check-file src/world/ledger.py --json

# Get references reviewed
python scripts/parse_plan.py --plan 89 --references-reviewed --json
```

## Related Patterns

- [Rebase Workflow](20_rebase-workflow.md) - Keeps worktrees up-to-date before creating PRs
- [Claim System](18_claim-system.md) - Coordinates which instance works on what
- [Git Hooks](../06_git-hooks.md) - Pre-commit validation before pushing
- [PR Coordination](21_pr-coordination.md) - Tracks review requests across instances
- [Plan Workflow](../15_plan-workflow.md) - Plan template with Files Affected section

## Worktree Removal Protection

A separate hook prevents direct use of `git worktree remove`:

### Problem

When a shell's current working directory is inside a worktree that gets removed:
- The shell's CWD becomes invalid
- All subsequent commands fail with "No such file or directory"
- The Claude Code session becomes unusable

### Solution

The `block-worktree-remove.sh` hook intercepts Bash commands containing `git worktree remove` and blocks them:

```
BLOCKED: Direct 'git worktree remove' is not allowed

Use the safe removal command instead:
  make worktree-remove BRANCH=<branch-name>
```

### Safe Removal

Always use `make worktree-remove BRANCH=...` which:
1. Checks for uncommitted changes (prevents data loss)
2. Checks for active claims (prevents breaking other sessions)
3. Uses `safe_worktree_remove.py` for the actual removal

### Hook Configuration

The hook is registered in `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "bash .claude/hooks/block-worktree-remove.sh",
            "timeout": 5000
          }
        ]
      }
    ]
  }
}
```

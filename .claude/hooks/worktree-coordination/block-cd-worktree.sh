#!/bin/bash
# Block `cd worktrees/...` commands that would change the Bash tool's persistent CWD
#
# Why this matters: The Bash tool maintains a persistent CWD across invocations.
# If you cd into a worktree and that worktree is later deleted (by make finish),
# all subsequent bash commands fail because the CWD no longer exists.
#
# This hook catches the common mistake of using `cd worktrees/... && command`.
# Even though && chains execution, the cd still takes effect and persists.
#
# Exit codes:
#   0 - Allow the operation
#   2 - Block the operation
#
# Configuration:
#   Controlled by hooks.enforce_workflow in meta-process.yaml

set -e

# Check if hook is enabled via config
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/check-hook-enabled.sh"
if ! is_hook_enabled "enforce_workflow"; then
    exit 0  # Hook disabled in config
fi

# Read the tool input from stdin
INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

if [[ -z "$COMMAND" ]]; then
    exit 0  # No command, allow
fi

# Check if command contains `cd` followed by a path containing `worktrees/`
# Patterns to catch:
#   cd worktrees/...
#   cd ./worktrees/...
#   cd /absolute/path/worktrees/...
#   cd "worktrees/..." (quoted)
#
# Patterns to allow (don't change CWD):
#   git -C worktrees/...
#   ls worktrees/...
#   cat worktrees/...

if echo "$COMMAND" | grep -qE '(^|&&|;|\|)\s*cd\s+["\x27]?(\./|/[^ ]*)?worktrees/'; then
    echo "BLOCKED: Never cd into a worktree" >&2
    echo "" >&2
    echo "The Bash tool's CWD persists across invocations. If you cd into a worktree" >&2
    echo "and it gets deleted (by make finish), your shell breaks permanently." >&2
    echo "" >&2
    echo "Even 'cd worktrees/X && command' is dangerous - the cd still takes effect." >&2
    echo "" >&2
    echo "Use instead:" >&2
    echo "  git -C worktrees/plan-X/...   # For git commands" >&2
    echo "  gh pr create                   # Works from any directory" >&2
    echo "  Absolute paths for reads/writes" >&2
    echo "" >&2
    echo "See: meta-process/patterns/worktree-coordination/19_worktree-enforcement.md for why this matters." >&2
    exit 2
fi

exit 0

#!/bin/bash
# Block if Claude Code session CWD is inside a worktree.
#
# If CWD is in a worktree, any 'make finish' will delete that directory
# and permanently break the shell. Fix: cd to main first.
#
# This fires on Read|Glob (the first tools any session uses).
# Bash commands are NOT blocked — so the model can run 'cd' to fix itself.
#
# See meta-process/CWD_INCIDENT_LOG.md (Incident #3) for why this blocks
# instead of warning.
#
# Exit codes:
#   0 - CWD is not in a worktree (allow)
#   2 - CWD is in a worktree (block until model runs cd)
#
# Configuration:
#   Controlled by hooks.warn_worktree_cwd in meta-process.yaml

# Check if hook is enabled via config
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/check-hook-enabled.sh"
if ! is_hook_enabled "warn_worktree_cwd"; then
    exit 0  # Hook disabled in config
fi

# Get current working directory
CWD=$(pwd 2>/dev/null || echo "")

# Check if CWD is inside a worktree
if [[ "$CWD" == */worktrees/* ]]; then
    # Extract main directory
    MAIN_DIR=$(echo "$CWD" | sed 's|/worktrees/.*||')

    echo "BLOCKED: Session CWD is inside a worktree." >&2
    echo "" >&2
    echo "  CWD: $CWD" >&2
    echo "" >&2
    echo "If a worktree is deleted while CWD points into it, the shell" >&2
    echo "breaks permanently. Fix by running this Bash command first:" >&2
    echo "" >&2
    echo "  cd $MAIN_DIR" >&2
    echo "" >&2
    exit 2
fi

exit 0

#!/bin/bash
# Check if shell CWD is valid before running bash commands
# If CWD was deleted (worktree removed), fail gracefully with recovery instructions
#
# Exit codes:
#   0 - CWD is valid, allow operation
#   2 - CWD is invalid, block operation

# Try to get current directory
if ! pwd >/dev/null 2>&1; then
    echo "BLOCKED: Shell working directory is invalid!" >&2
    echo "" >&2
    echo "This usually happens when:" >&2
    echo "  - A worktree you were working in was deleted" >&2
    echo "  - Another CC instance ran 'make finish' on your worktree" >&2
    echo "" >&2
    # Get repo root for recovery instructions
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
    REPO_ROOT="$(dirname "$(dirname "$(dirname "$SCRIPT_DIR")")")"

    echo "Recovery options:" >&2
    echo "  1. Start a new Claude Code session" >&2
    echo "  2. If in terminal: cd $REPO_ROOT" >&2
    echo "" >&2
    echo "To prevent this in the future:" >&2
    echo "  - Always run 'make finish' from main, not from a worktree" >&2
    echo "  - Don't delete worktrees owned by other CC instances" >&2
    exit 2
fi

exit 0

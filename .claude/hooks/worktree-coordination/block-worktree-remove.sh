#!/bin/bash
# Block direct `git worktree` commands that bypass safety checks
# Forces use of `make worktree` (creates claim) and `make worktree-remove` (checks uncommitted)
#
# Exit codes:
#   0 - Allow the operation
#   2 - Block the operation

set -e

# Read the tool input from stdin
INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

if [[ -z "$COMMAND" ]]; then
    exit 0  # No command, allow
fi

# Check if command contains `git worktree add`
if echo "$COMMAND" | grep -qE 'git\s+worktree\s+add'; then
    # Extract branch name from command
    # Format 1: git worktree add -b <new-branch> <path>
    # Format 2: git worktree add <path> <existing-branch>
    BRANCH=""
    if echo "$COMMAND" | grep -qE '\-b\s+\S+'; then
        # New branch with -b flag
        BRANCH=$(echo "$COMMAND" | grep -oE '\-b\s+\S+' | sed 's/-b\s*//')
    else
        # Existing branch - last argument after the path
        # Pattern: git worktree add <path> <branch>
        BRANCH=$(echo "$COMMAND" | sed 's/.*git\s\+worktree\s\+add\s\+\S\+\s\+//' | awk '{print $1}')
    fi

    # Check if this branch has an existing claim
    # Always check main repo's claims file (not worktree's stale copy)
    MAIN_DIR=$(git worktree list | head -1 | awk '{print $1}')
    CLAIMS_FILE="$MAIN_DIR/.claude/active-work.yaml"
    HAS_CLAIM=false
    if [[ -n "$BRANCH" && -f "$CLAIMS_FILE" ]]; then
        if grep -q "cc_id: $BRANCH" "$CLAIMS_FILE"; then
            HAS_CLAIM=true
        fi
    fi

    if [[ "$HAS_CLAIM" == "true" ]]; then
        # Claim exists, allow the worktree creation
        exit 0
    else
        echo "BLOCKED: Direct 'git worktree add' is not allowed" >&2
        echo "" >&2
        echo "This bypasses the claim system - other instances won't know you're working on this." >&2
        echo "" >&2
        echo "Use the proper command instead:" >&2
        echo "  make worktree BRANCH=plan-NN-description" >&2
        echo "" >&2
        echo "This will:" >&2
        echo "  1. Prompt for task description and plan number" >&2
        echo "  2. Create a claim so other instances see your work" >&2
        echo "  3. Create the worktree" >&2
        echo "" >&2
        echo "Or create a claim first, then run git worktree add:" >&2
        echo "  python scripts/check_claims.py --claim --plan N --task 'description' --id <branch-name>" >&2
        exit 2
    fi
fi

# Check if command contains `git worktree remove`
if echo "$COMMAND" | grep -qE 'git\s+worktree\s+remove'; then
    echo "BLOCKED: Direct 'git worktree remove' is not allowed" >&2
    echo "" >&2
    echo "This command can break your shell session and lose uncommitted work." >&2
    echo "" >&2
    echo "Use the safe removal command instead:" >&2
    echo "  make worktree-remove BRANCH=<branch-name>" >&2
    exit 2
fi

exit 0

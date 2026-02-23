#!/bin/bash
# Branch Protection Hook for Claude Code
# Warns when editing files directly on the main/master branch.
# Encourages creating a feature branch first.
#
# This is the CORE version (branch-based workflow).
# For worktree enforcement, see worktree-coordination/protect-main.sh
#
# Exit codes:
#   0 - Allow the operation
#   2 - Block the operation

set -e

# Only applies to Edit/Write operations (file modifications)
INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [[ -z "$FILE_PATH" ]]; then
    exit 0  # No file_path, allow
fi

# Allow coordination files everywhere
BASENAME=$(basename "$FILE_PATH")
if [[ "$FILE_PATH" == *"/.claude/"* ]] || \
   [[ "$BASENAME" == "CLAUDE.md" ]] || \
   [[ "$FILE_PATH" == *"/.git/"* ]] || \
   [[ "$FILE_PATH" == */meta/patterns/*.md ]] || \
   [[ "$FILE_PATH" == */meta-process/*.md ]] || \
   [[ "$BASENAME" == ".claude_session" ]]; then
    exit 0  # Coordination/docs files allowed on any branch
fi

# Check current branch
BRANCH=$(git branch --show-current 2>/dev/null)

if [[ "$BRANCH" == "main" || "$BRANCH" == "master" ]]; then
    echo "WARNING: You're editing files directly on '$BRANCH'" >&2
    echo "" >&2
    echo "Consider creating a feature branch first:" >&2
    echo "  git checkout -b plan-N-description" >&2
    echo "" >&2
    echo "File: $FILE_PATH" >&2
    # Allow but warn - the git hooks will catch direct commits to main
    exit 0
fi

exit 0

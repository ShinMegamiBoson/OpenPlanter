#!/bin/bash
# File Scope Enforcement Hook for Claude Code
# Blocks Edit/Write operations to files not declared in the active plan's Files Affected section.
#
# Exit codes:
#   0 - Allow the operation
#   2 - Block the operation
#
# This hook enforces planning discipline by requiring CC to declare
# which files it will touch before editing them.

# set -e  # Disabled: causes silent exits on non-zero returns

# Debug mode (set DEBUG=1 to enable)
debug() {
    if [[ -n "$DEBUG" ]]; then
        echo "DEBUG: $*" >&2
    fi
}

# Get the main repo root
MAIN_DIR=$(git rev-parse --git-common-dir 2>/dev/null | xargs dirname)
debug "MAIN_DIR=$MAIN_DIR"
if [[ -z "$MAIN_DIR" ]]; then
    debug "Not in git repo, allowing"
    exit 0  # Not in a git repo, allow
fi

# Read tool input to get file path
INPUT=$(cat)
debug "INPUT=$INPUT"
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
debug "FILE_PATH=$FILE_PATH"

if [[ -z "$FILE_PATH" ]]; then
    debug "No file_path, allowing"
    exit 0  # No file_path, allow
fi

# Allow writes to worktree-specific paths
# Match both /worktrees/ and *_worktrees/ patterns (Plan #160 fix)
WORKTREE_BRANCH=""
if [[ "$FILE_PATH" == *"/worktrees/"* ]] || [[ "$FILE_PATH" == *"_worktrees/"* ]]; then
    # Extract the worktree-relative path
    # Handle both /worktrees/branch/ and *_worktrees/branch/ patterns
    WORKTREE_PATH=$(echo "$FILE_PATH" | sed 's|.*/[^/]*worktrees/[^/]*/||')
    # Plan #160: Extract branch name from worktree path for plan detection
    # Path format: .../worktrees/branch-name/... or ..._worktrees/branch-name/...
    WORKTREE_BRANCH=$(echo "$FILE_PATH" | sed 's|.*/[^/]*worktrees/\([^/]*\)/.*|\1|')
    debug "WORKTREE_BRANCH=$WORKTREE_BRANCH"
else
    # Not in a worktree, use path relative to main
    WORKTREE_PATH=$(echo "$FILE_PATH" | sed "s|^$MAIN_DIR/||")
fi
debug "WORKTREE_PATH=$WORKTREE_PATH"

# Allow coordination files without plan declaration
if [[ "$WORKTREE_PATH" == ".claude/"* ]] || \
   [[ "$WORKTREE_PATH" == *"CLAUDE.md" ]] || \
   [[ "$WORKTREE_PATH" == ".git/"* ]] || \
   [[ "$WORKTREE_PATH" == "docs/plans/"* ]]; then
    debug "Coordination file, allowing"
    exit 0  # Coordination/plan files always allowed
fi

# Check if this is a trivial commit context
# (We can't know for sure, but we allow if no plan is active)
# Plan #160: Use worktree branch if available (fixes cross-worktree edits)
if [[ -n "$WORKTREE_BRANCH" ]]; then
    BRANCH="$WORKTREE_BRANCH"
    debug "Using worktree branch: $BRANCH"
else
    BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
    debug "Using git HEAD branch: $BRANCH"
fi

# Skip check for main branch (reviews only, not implementation)
if [[ "$BRANCH" == "main" ]]; then
    debug "Main branch, allowing"
    exit 0
fi

# Try to get active plan number from branch name
PLAN_NUM=""
if [[ "$BRANCH" =~ ^plan-([0-9]+) ]]; then
    PLAN_NUM="${BASH_REMATCH[1]}"
fi
debug "PLAN_NUM=$PLAN_NUM"

# If no plan number in branch, check claims
if [[ -z "$PLAN_NUM" ]]; then
    debug "No plan number, allowing"
    # No plan context - allow (might be trivial work)
    exit 0
fi

# Check if file is in plan's scope using parse_plan.py
# Try worktree first, then main repo
SCRIPT_PATH=""
debug "Looking for parse_plan.py..."
debug "Checking: scripts/parse_plan.py (exists: $(test -f scripts/parse_plan.py && echo yes || echo no))"
debug "Checking: $MAIN_DIR/scripts/parse_plan.py (exists: $(test -f "$MAIN_DIR/scripts/parse_plan.py" && echo yes || echo no))"
if [[ -f "scripts/parse_plan.py" ]]; then
    SCRIPT_PATH="scripts/parse_plan.py"
elif [[ -f "$MAIN_DIR/scripts/parse_plan.py" ]]; then
    SCRIPT_PATH="$MAIN_DIR/scripts/parse_plan.py"
else
    # Parser not available - allow (graceful degradation)
    debug "No parse_plan.py found, allowing"
    exit 0
fi
debug "SCRIPT_PATH=$SCRIPT_PATH"

# Run the check
# Note: parse_plan.py returns exit 0 if in scope, exit 2 if not in scope, exit 1 on error
# We capture stdout regardless of exit code, then check for JSON validity
debug "Running: python $SCRIPT_PATH --plan $PLAN_NUM --check-file $WORKTREE_PATH --json"
RESULT=$(python "$SCRIPT_PATH" --plan "$PLAN_NUM" --check-file "$WORKTREE_PATH" --json 2>/dev/null)
EXIT_CODE=$?
debug "Parse script exit code: $EXIT_CODE"

# If output is not valid JSON, treat as parse failure
if ! echo "$RESULT" | jq . >/dev/null 2>&1; then
    RESULT='{"error": "parse_failed"}'
fi
debug "RESULT=$RESULT"

# Parse result
IN_SCOPE=$(echo "$RESULT" | jq -r '.in_scope // false')
ERROR=$(echo "$RESULT" | jq -r '.error // empty')
debug "IN_SCOPE=$IN_SCOPE"
debug "ERROR=$ERROR"

# Handle errors gracefully (allow on error)
if [[ -n "$ERROR" ]]; then
    if [[ "$ERROR" == "plan_not_found" ]]; then
        # Plan file doesn't exist - allow (might be new plan)
        debug "Plan not found, allowing"
        exit 0
    fi
    # Other errors - allow (graceful degradation)
    debug "Error occurred ($ERROR), allowing"
    exit 0
fi

# Check scope
if [[ "$IN_SCOPE" == "true" ]]; then
    debug "File in scope, allowing"
    exit 0  # File is in scope, allow
fi
debug "File NOT in scope, blocking"

# File not in scope - block with helpful message
echo "BLOCKED: File not in plan's declared scope" >&2
echo "" >&2
echo "Plan #$PLAN_NUM does not list this file in 'Files Affected':" >&2
echo "  $WORKTREE_PATH" >&2
echo "" >&2
echo "To fix, update your plan file:" >&2
echo "  docs/plans/${PLAN_NUM}_*.md" >&2
echo "" >&2
echo "Add to '## Files Affected' section:" >&2
echo "  - $WORKTREE_PATH (modify)" >&2
echo "  or" >&2
echo "  - $WORKTREE_PATH (create)" >&2
echo "" >&2
echo "This ensures all changes are planned and traceable." >&2

exit 2

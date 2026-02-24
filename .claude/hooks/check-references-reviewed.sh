#!/bin/bash
# References Reviewed Enforcement Hook for Claude Code
# Warns (doesn't block) if the active plan lacks a References Reviewed section.
#
# Exit codes:
#   0 - Always (this hook warns but doesn't block)
#
# This hook encourages exploration before coding by checking that the plan
# documents what code/docs were reviewed before planning.

set -e

# Only warn once per session to avoid spam
# Use a temp file to track if we've warned
SESSION_MARKER="/tmp/.claude_refs_warned_$$"

# If we've already warned this session, skip
if [[ -f "$SESSION_MARKER" ]]; then
    exit 0
fi

# Get the main repo root
MAIN_DIR=$(git rev-parse --git-common-dir 2>/dev/null | xargs dirname)
if [[ -z "$MAIN_DIR" ]]; then
    exit 0
fi

# Read tool input to get file path
INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [[ -z "$FILE_PATH" ]]; then
    exit 0
fi

# Only check on source file edits (not docs, config, etc.)
# Handle both absolute paths (/path/to/src/...) and relative paths (src/...)
if [[ "$FILE_PATH" != *"/src/"* ]] && [[ "$FILE_PATH" != *"/tests/"* ]] && \
   [[ "$FILE_PATH" != "src/"* ]] && [[ "$FILE_PATH" != "tests/"* ]]; then
    exit 0
fi

# Get branch name
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")

# Skip for main branch
if [[ "$BRANCH" == "main" ]]; then
    exit 0
fi

# Try to get plan number from branch name
PLAN_NUM=""
if [[ "$BRANCH" =~ ^plan-([0-9]+) ]]; then
    PLAN_NUM="${BASH_REMATCH[1]}"
fi

# If no plan number, skip
if [[ -z "$PLAN_NUM" ]]; then
    exit 0
fi

# Check references using parse_plan.py (check both script locations)
PARSE_PLAN=""
if [[ -f "$MAIN_DIR/scripts/meta/parse_plan.py" ]]; then
    PARSE_PLAN="$MAIN_DIR/scripts/meta/parse_plan.py"
elif [[ -f "$MAIN_DIR/scripts/parse_plan.py" ]]; then
    PARSE_PLAN="$MAIN_DIR/scripts/parse_plan.py"
else
    exit 0
fi

# Get references reviewed
RESULT=$(python "$PARSE_PLAN" --plan "$PLAN_NUM" --references-reviewed --json 2>/dev/null || echo '{"error": "parse_failed"}')

# Parse result
REFS=$(echo "$RESULT" | jq -r '.references_reviewed // []')
REF_COUNT=$(echo "$REFS" | jq 'length')
ERROR=$(echo "$RESULT" | jq -r '.error // empty')

# Skip on errors
if [[ -n "$ERROR" ]]; then
    exit 0
fi

# Check if references are sufficient (at least 2 entries)
MIN_REFS=2

if [[ "$REF_COUNT" -lt "$MIN_REFS" ]]; then
    # Mark that we've warned
    touch "$SESSION_MARKER"

    echo "" >&2
    echo "========================================" >&2
    echo "⚠️  EXPLORATION WARNING" >&2
    echo "========================================" >&2
    echo "" >&2
    echo "Plan #$PLAN_NUM has insufficient 'References Reviewed' ($REF_COUNT/$MIN_REFS minimum)" >&2
    echo "" >&2
    echo "Before implementing, you should:" >&2
    echo "  1. Explore the existing codebase" >&2
    echo "  2. Document what you reviewed in the plan" >&2
    echo "" >&2
    echo "Add to your plan file (docs/plans/${PLAN_NUM}_*.md):" >&2
    echo "" >&2
    echo "  ## References Reviewed" >&2
    echo "  - src/relevant/file.py:10-50 - description of what you learned" >&2
    echo "  - docs/architecture/current/relevant.md - relevant design context" >&2
    echo "" >&2
    echo "This ensures you understand the codebase before changing it." >&2
    echo "(This warning appears once per session)" >&2
    echo "========================================" >&2
    echo "" >&2
fi

# Always allow (warning only)
exit 0

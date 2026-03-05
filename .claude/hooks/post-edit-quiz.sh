#!/bin/bash
# Post-edit quiz — surfaces understanding questions after editing src/ files.
# PostToolUse/Edit hook — shows constraint quiz after successful edits.
#
# This is advisory (exit 0) — it doesn't block, just prompts engagement.
#
# Only triggers for src/ files with governance entries.

set -e

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null || echo "")
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null || echo "")

# Only fire after Edit and Write
if [[ "$TOOL_NAME" != "Edit" && "$TOOL_NAME" != "Write" ]]; then
    exit 0
fi

if [[ -z "$FILE_PATH" ]]; then
    exit 0
fi

# Only for src/ files
if [[ "$FILE_PATH" != *"/src/"* ]] && [[ "$FILE_PATH" != "src/"* ]]; then
    exit 0
fi

# Bypass
if [[ "${SKIP_QUIZ:-}" == "1" ]]; then
    exit 0
fi

# Get repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Normalize path
REL_PATH="$FILE_PATH"
if [[ "$FILE_PATH" == "$REPO_ROOT/"* ]]; then
    REL_PATH="${FILE_PATH#$REPO_ROOT/}"
fi
if [[ "$REL_PATH" == worktrees/* ]]; then
    REL_PATH=$(echo "$REL_PATH" | sed 's|^worktrees/[^/]*/||')
fi

# Find quiz script
QUIZ_SCRIPT="$REPO_ROOT/scripts/generate_quiz.py"
if [[ ! -f "$QUIZ_SCRIPT" ]]; then
    exit 0
fi

# Generate quiz (JSON mode for structured output)
set +e
RESULT=$(cd "$REPO_ROOT" && python "$QUIZ_SCRIPT" "$REL_PATH" --json 2>/dev/null)
QUIZ_EXIT=$?
set -e

if [[ $QUIZ_EXIT -ne 0 ]] || [[ -z "$RESULT" ]] || [[ "$RESULT" == "[]" ]]; then
    exit 0
fi

# Extract just the questions as readable text
QUIZ_TEXT=$(cd "$REPO_ROOT" && python "$QUIZ_SCRIPT" "$REL_PATH" 2>/dev/null)

if [[ -z "$QUIZ_TEXT" ]]; then
    exit 0
fi

QUIZ_ESCAPED=$(echo "$QUIZ_TEXT" | jq -Rs .)

cat << EOF
{
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": $QUIZ_ESCAPED
  }
}
EOF

exit 0

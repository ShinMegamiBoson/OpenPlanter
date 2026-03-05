#!/bin/bash
# Gate edits on required reading.
# PreToolUse/Edit hook — blocks edits to src/ files if coupled docs not read.
#
# Uses relationships.yaml couplings to determine what docs must be read
# and checks the session reads file (populated by track-reads.sh).
#
# Exit codes:
#   0 - Allow (all required docs read, or file not gated)
#   2 - Block (required docs not yet read)
#
# Bypass: SKIP_READ_GATE=1 in environment, or edit non-src files.

set -e

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null || echo "")
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null || echo "")

# Only gate Edit and Write
if [[ "$TOOL_NAME" != "Edit" && "$TOOL_NAME" != "Write" ]]; then
    exit 0
fi

if [[ -z "$FILE_PATH" ]]; then
    exit 0
fi

# Only gate src/ files
if [[ "$FILE_PATH" != *"/src/"* ]] && [[ "$FILE_PATH" != "src/"* ]]; then
    exit 0
fi

# Bypass check
if [[ "${SKIP_READ_GATE:-}" == "1" ]]; then
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

# Find the check script
CHECK_SCRIPT="$REPO_ROOT/scripts/check_required_reading.py"
if [[ ! -f "$CHECK_SCRIPT" ]]; then
    exit 0  # Script not available, allow
fi

READS_FILE="/tmp/.claude_session_reads"

# Run the check
set +e
RESULT=$(cd "$REPO_ROOT" && python "$CHECK_SCRIPT" "$REL_PATH" --reads-file "$READS_FILE" 2>/dev/null)
CHECK_EXIT=$?
set -e

if [[ $CHECK_EXIT -ne 0 ]]; then
    # Escape for JSON output
    RESULT_ESCAPED=$(echo "$RESULT" | jq -Rs .)

    cat << EOF
{
  "decision": "block",
  "reason": $RESULT_ESCAPED
}
EOF
    exit 2
fi

# All required reading done — output constraints as advisory context
if [[ -n "$RESULT" ]]; then
    RESULT_ESCAPED=$(echo "$RESULT" | jq -Rs .)
    cat << EOF
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": $RESULT_ESCAPED
  }
}
EOF
fi

exit 0

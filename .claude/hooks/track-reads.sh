#!/bin/bash
# Track file reads for required-reading enforcement.
# PostToolUse/Read hook — logs each read to a session file.
#
# The session file is checked by gate-edit.sh to verify
# required docs were read before editing source files.
#
# Session tracking: uses repo-specific file in /tmp.
# Reset by deleting /tmp/.claude_session_reads

set -e

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null || echo "")

if [[ -z "$FILE_PATH" ]]; then
    exit 0
fi

# Get repo root for normalization
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "")
if [[ -z "$REPO_ROOT" ]]; then
    exit 0
fi

# Normalize to repo-relative path
REL_PATH="$FILE_PATH"
if [[ "$FILE_PATH" == "$REPO_ROOT/"* ]]; then
    REL_PATH="${FILE_PATH#$REPO_ROOT/}"
fi

# Strip worktree prefix if present
if [[ "$REL_PATH" == worktrees/* ]]; then
    REL_PATH=$(echo "$REL_PATH" | sed 's|^worktrees/[^/]*/||')
fi

# Session reads file — per-repo
REPO_NAME=$(basename "$REPO_ROOT")
READS_FILE="/tmp/.claude_session_reads"

# Append (dedup happens at check time)
echo "$REL_PATH" >> "$READS_FILE"

exit 0

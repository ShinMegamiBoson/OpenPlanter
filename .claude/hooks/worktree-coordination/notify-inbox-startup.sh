#!/bin/bash
# Startup Inbox Notification Hook for Claude Code
# Warns about unread messages on first Read/Glob operation.
#
# Unlike check-inbox.sh which BLOCKS, this just WARNS once per session.
# This ensures CC instances are aware of messages even when just reading.
#
# Uses a session marker file to only warn once per session.
#
# Exit codes:
#   0 - Always allow (this is just a notification)

# Get the main repo root
MAIN_REPO_ROOT=$(git worktree list 2>/dev/null | head -1 | awk '{print $1}')
if [[ -z "$MAIN_REPO_ROOT" ]]; then
    exit 0  # Not in a git repo
fi

# Check if inter-CC messaging is enabled (default: disabled)
CONFIG_FILE="$MAIN_REPO_ROOT/.claude/meta-config.yaml"
if [[ -f "$CONFIG_FILE" ]]; then
    MESSAGING_ENABLED=$(grep "^inter_cc_messaging:" "$CONFIG_FILE" 2>/dev/null | awk '{print $2}')
    if [[ "$MESSAGING_ENABLED" != "true" ]]; then
        exit 0  # Messaging disabled, skip inbox notification
    fi
fi

# Session marker - unique per port or PID
SESSION_ID="${CLAUDE_CODE_SSE_PORT:-$$}"
MARKER_FILE="/tmp/claude-inbox-notified-$SESSION_ID"

# Check if already notified this session
if [[ -f "$MARKER_FILE" ]]; then
    # Check if marker is less than 4 hours old
    if [[ $(find "$MARKER_FILE" -mmin -240 2>/dev/null) ]]; then
        exit 0  # Already notified recently
    fi
fi

# Determine identity from context
get_identity() {
    local cwd=$(pwd)

    # Check if in a worktree
    if [[ "$cwd" == */worktrees/* ]]; then
        echo "$cwd" | sed 's|.*/worktrees/\([^/]*\).*|\1|'
        return
    fi

    # Check port mapping
    if [[ -n "$CLAUDE_CODE_SSE_PORT" ]]; then
        local sessions_file="$MAIN_REPO_ROOT/.claude/sessions.yaml"
        if [[ -f "$sessions_file" ]]; then
            local identity=$(grep "^$CLAUDE_CODE_SSE_PORT:" "$sessions_file" 2>/dev/null | cut -d':' -f2 | tr -d ' ')
            if [[ -n "$identity" ]]; then
                echo "$identity"
                return
            fi
        fi
    fi

    echo "main"
}

# Count unread messages in inbox
count_unread() {
    local inbox_dir="$1"

    if [[ ! -d "$inbox_dir" ]]; then
        echo 0
        return
    fi

    local count=0
    shopt -s nullglob
    for msg_file in "$inbox_dir"/*.md; do
        if [[ -f "$msg_file" ]]; then
            if grep -q "^status: unread" "$msg_file" 2>/dev/null; then
                count=$((count + 1))
            fi
        fi
    done
    shopt -u nullglob

    echo $count
}

# Get identity and check inbox
IDENTITY=$(get_identity)
INBOX_DIR="$MAIN_REPO_ROOT/.claude/messages/inbox/$IDENTITY"
UNREAD_COUNT=$(count_unread "$INBOX_DIR")

# Create marker file (even if no messages, to avoid repeated checks)
touch "$MARKER_FILE"

if [[ "$UNREAD_COUNT" -gt 0 ]]; then
    echo "" >&2
    echo "╔════════════════════════════════════════════════════════════╗" >&2
    echo "║  📬 You have $UNREAD_COUNT unread message(s) from other CC instances  ║" >&2
    echo "╠════════════════════════════════════════════════════════════╣" >&2
    echo "║  View:   python scripts/check_messages.py --list          ║" >&2
    echo "║  Ack:    python scripts/check_messages.py --ack           ║" >&2
    echo "╚════════════════════════════════════════════════════════════╝" >&2
    echo "" >&2
fi

exit 0

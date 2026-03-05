#!/bin/bash
# Inbox Check Hook for Claude Code
# Blocks Edit/Write operations if there are unread messages in inbox.
#
# This ensures coordination messages from other instances are never missed.
# If another instance took the time to send a message, it's important.
#
# Exit codes:
#   0 - Allow the operation (no unread messages)
#   2 - Block the operation (unread messages exist)

set -e

# Get the main repo root
MAIN_REPO_ROOT=$(git worktree list | head -1 | awk '{print $1}')

# Check if inter-CC messaging is enabled (default: disabled)
CONFIG_FILE="$MAIN_REPO_ROOT/.claude/meta-config.yaml"
if [[ -f "$CONFIG_FILE" ]]; then
    MESSAGING_ENABLED=$(grep "^inter_cc_messaging:" "$CONFIG_FILE" 2>/dev/null | awk '{print $2}')
    if [[ "$MESSAGING_ENABLED" != "true" ]]; then
        exit 0  # Messaging disabled, skip inbox check
    fi
fi

# Continue with inbox check

# Determine identity from context
get_identity() {
    local cwd=$(pwd)

    # Check if in a worktree
    if [[ "$cwd" == */worktrees/* ]]; then
        # Extract worktree name from path
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

    # Fallback
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
    # Enable nullglob to handle empty directories without error
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

# Get identity
IDENTITY=$(get_identity)

# Check inbox
INBOX_DIR="$MAIN_REPO_ROOT/.claude/messages/inbox/$IDENTITY"
UNREAD_COUNT=$(count_unread "$INBOX_DIR")

if [[ "$UNREAD_COUNT" -gt 0 ]]; then
    echo "📬 BLOCKED: You have $UNREAD_COUNT unread message(s)" >&2
    echo "" >&2
    echo "Another CC instance sent you message(s) that require attention." >&2
    echo "" >&2
    echo "To view messages:" >&2
    echo "  python scripts/check_messages.py --list" >&2
    echo "" >&2
    echo "To acknowledge and continue:" >&2
    echo "  python scripts/check_messages.py --ack" >&2
    echo "" >&2
    echo "Identity: $IDENTITY" >&2
    echo "Inbox: $INBOX_DIR" >&2
    exit 2
fi

exit 0

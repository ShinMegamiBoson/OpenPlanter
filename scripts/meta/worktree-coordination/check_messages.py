#!/usr/bin/env python3
"""Check and manage messages from other Claude Code instances.

Usage:
    python scripts/check_messages.py --list              # List all messages in inbox
    python scripts/check_messages.py --read <msg-id>     # Read a specific message
    python scripts/check_messages.py --archive <msg-id>  # Archive a message
    python scripts/check_messages.py --ack               # Acknowledge all messages (mark as read)
    python scripts/check_messages.py --count             # Just count unread messages (for hooks)

Identity Resolution:
    1. Worktree name - If in /worktrees/plan-83-foo/, identity is 'plan-83-foo'
    2. Port mapping - Look up $CLAUDE_CODE_SSE_PORT in .claude/sessions.yaml
    3. Fallback - 'main' or 'unknown'
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def get_repo_root() -> Path:
    """Get the main repository root (not worktree root)."""
    result = subprocess.run(
        ["git", "worktree", "list"], capture_output=True, text=True, check=True
    )
    # First line is always the main worktree
    main_line = result.stdout.strip().split("\n")[0]
    return Path(main_line.split()[0])


def get_identity() -> str:
    """Determine current identity from context."""
    cwd = Path.cwd()

    # Check if in a worktree
    if "/worktrees/" in str(cwd):
        # Extract worktree name from path
        parts = str(cwd).split("/worktrees/")
        if len(parts) > 1:
            worktree_name = parts[1].split("/")[0]
            return worktree_name

    # Check port mapping
    port = os.environ.get("CLAUDE_CODE_SSE_PORT")
    if port:
        repo_root = get_repo_root()
        sessions_file = repo_root / ".claude" / "sessions.yaml"
        if sessions_file.exists():
            with open(sessions_file) as f:
                content = f.read().strip()
                for line in content.split("\n"):
                    if line.startswith(f"{port}:"):
                        return line.split(":", 1)[1].strip()

    # Fallback
    return "main"


def parse_message_frontmatter(content: str) -> dict:
    """Parse YAML frontmatter from message content."""
    if not content.startswith("---"):
        return {}

    # Find end of frontmatter
    end_match = content.find("\n---", 3)
    if end_match == -1:
        return {}

    frontmatter = content[4:end_match]
    result = {}

    for line in frontmatter.split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip()

    return result


def get_inbox_path(identity: Optional[str] = None) -> Path:
    """Get inbox path for the given identity."""
    repo_root = get_repo_root()
    if identity is None:
        identity = get_identity()
    return repo_root / ".claude" / "messages" / "inbox" / identity


def get_archive_path(identity: Optional[str] = None) -> Path:
    """Get archive path for the given identity."""
    repo_root = get_repo_root()
    if identity is None:
        identity = get_identity()
    return repo_root / ".claude" / "messages" / "archive" / identity


def list_messages(inbox_path: Path, show_all: bool = False) -> list[dict]:
    """List messages in inbox.

    Args:
        inbox_path: Path to inbox directory
        show_all: If True, show all messages. If False, only unread.

    Returns:
        List of message metadata dicts
    """
    messages = []

    if not inbox_path.exists():
        return messages

    for msg_file in sorted(inbox_path.glob("*.md")):
        content = msg_file.read_text()
        metadata = parse_message_frontmatter(content)
        metadata["_file"] = msg_file.name
        metadata["_path"] = str(msg_file)

        if show_all or metadata.get("status") == "unread":
            messages.append(metadata)

    return messages


def count_unread(inbox_path: Path) -> int:
    """Count unread messages in inbox."""
    return len(list_messages(inbox_path, show_all=False))


def read_message(inbox_path: Path, msg_id: str) -> Optional[str]:
    """Read a specific message by ID."""
    for msg_file in inbox_path.glob("*.md"):
        content = msg_file.read_text()
        metadata = parse_message_frontmatter(content)
        if metadata.get("id") == msg_id or msg_file.name == msg_id:
            return content
    return None


def mark_as_read(inbox_path: Path, msg_id: str) -> bool:
    """Mark a message as read."""
    for msg_file in inbox_path.glob("*.md"):
        content = msg_file.read_text()
        metadata = parse_message_frontmatter(content)
        if metadata.get("id") == msg_id or msg_file.name == msg_id:
            # Update status in file
            new_content = re.sub(
                r"^status:\s*unread\s*$",
                "status: read",
                content,
                flags=re.MULTILINE,
            )
            msg_file.write_text(new_content)
            return True
    return False


def acknowledge_all(inbox_path: Path) -> int:
    """Acknowledge (mark as read) all messages in inbox.

    Returns:
        Number of messages acknowledged
    """
    count = 0
    if not inbox_path.exists():
        return count

    for msg_file in inbox_path.glob("*.md"):
        content = msg_file.read_text()
        if "status: unread" in content:
            new_content = re.sub(
                r"^status:\s*unread\s*$",
                "status: read",
                content,
                flags=re.MULTILINE,
            )
            msg_file.write_text(new_content)
            count += 1

    return count


def archive_message(inbox_path: Path, archive_path: Path, msg_id: str) -> bool:
    """Archive a message (move from inbox to archive)."""
    for msg_file in inbox_path.glob("*.md"):
        content = msg_file.read_text()
        metadata = parse_message_frontmatter(content)
        if metadata.get("id") == msg_id or msg_file.name == msg_id:
            # Ensure archive directory exists
            archive_path.mkdir(parents=True, exist_ok=True)

            # Move file
            dest = archive_path / msg_file.name
            shutil.move(str(msg_file), str(dest))
            return True
    return False


def format_message_list(messages: list[dict]) -> str:
    """Format messages for display."""
    if not messages:
        return "No messages found."

    lines = []
    lines.append(f"{'ID':<40} {'From':<20} {'Type':<15} {'Subject':<30}")
    lines.append("-" * 105)

    for msg in messages:
        msg_id = msg.get("id", "unknown")[:38]
        sender = msg.get("from", "unknown")[:18]
        msg_type = msg.get("type", "unknown")[:13]
        subject = msg.get("subject", "")[:28]
        status = msg.get("status", "")

        status_marker = "📬" if status == "unread" else "  "
        lines.append(f"{status_marker} {msg_id:<38} {sender:<20} {msg_type:<15} {subject:<30}")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check and manage messages from other Claude Code instances",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all messages in inbox",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="With --list, show all messages including read ones",
    )
    parser.add_argument(
        "--read",
        metavar="MSG_ID",
        help="Read a specific message by ID",
    )
    parser.add_argument(
        "--archive",
        metavar="MSG_ID",
        help="Archive a message (move to archive folder)",
    )
    parser.add_argument(
        "--ack",
        action="store_true",
        help="Acknowledge all unread messages (mark as read)",
    )
    parser.add_argument(
        "--count",
        action="store_true",
        help="Just count unread messages (for hooks)",
    )
    parser.add_argument(
        "--inbox",
        metavar="IDENTITY",
        help="Override identity (check a specific inbox)",
    )

    args = parser.parse_args()

    # Determine identity
    identity = args.inbox if args.inbox else get_identity()
    inbox_path = get_inbox_path(identity)
    archive_path = get_archive_path(identity)

    # Handle commands
    if args.count:
        count = count_unread(inbox_path)
        print(count)
        return 0

    if args.list:
        messages = list_messages(inbox_path, show_all=args.all)
        print(f"Inbox for: {identity}")
        print(format_message_list(messages))
        return 0

    if args.read:
        content = read_message(inbox_path, args.read)
        if content:
            print(content)
            # Mark as read
            mark_as_read(inbox_path, args.read)
            return 0
        else:
            print(f"Message not found: {args.read}", file=sys.stderr)
            return 1

    if args.archive:
        if archive_message(inbox_path, archive_path, args.archive):
            print(f"Archived: {args.archive}")
            return 0
        else:
            print(f"Message not found: {args.archive}", file=sys.stderr)
            return 1

    if args.ack:
        count = acknowledge_all(inbox_path)
        print(f"Acknowledged {count} message(s)")
        return 0

    # Default: show unread count and list
    count = count_unread(inbox_path)
    if count > 0:
        print(f"📬 You have {count} unread message(s) in inbox for: {identity}")
        print()
        messages = list_messages(inbox_path, show_all=False)
        print(format_message_list(messages))
        print()
        print("Commands:")
        print("  --read <MSG_ID>     Read a specific message")
        print("  --ack               Acknowledge all messages")
        print("  --archive <MSG_ID>  Archive a message")
    else:
        print(f"No unread messages for: {identity}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Send a message to another Claude Code instance.

Usage:
    python scripts/send_message.py --to <recipient> --type <type> --subject <subject> --content <content>
    python scripts/send_message.py --to <recipient> --type <type> --subject <subject> --content-file <path>

Message Types:
    suggestion      - Code/doc improvements (recipient should integrate or decline)
    question        - Clarification needed (recipient should reply)
    handoff         - Transferring ownership (recipient should acknowledge)
    info            - FYI, no action needed (recipient should acknowledge)
    review-request  - Please review my work (recipient should approve/comment)

Identity Resolution (for sender):
    1. Worktree name - If in /worktrees/plan-83-foo/, sender is 'plan-83-foo'
    2. Port mapping - Look up $CLAUDE_CODE_SSE_PORT in .claude/sessions.yaml
    3. Fallback - 'main' or 'unknown'
"""

import argparse
import hashlib
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Message types with descriptions
MESSAGE_TYPES = {
    "suggestion": "Code/doc improvements",
    "question": "Clarification needed",
    "handoff": "Transferring ownership",
    "info": "FYI, no action needed",
    "review-request": "Please review my work",
}


def get_repo_root() -> Path:
    """Get the main repository root (not worktree root)."""
    result = subprocess.run(
        ["git", "worktree", "list"], capture_output=True, text=True, check=True
    )
    # First line is always the main worktree
    main_line = result.stdout.strip().split("\n")[0]
    return Path(main_line.split()[0])


def get_sender_identity() -> str:
    """Determine sender identity from context."""
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


def generate_message_id(sender: str, timestamp: datetime) -> str:
    """Generate unique message ID."""
    ts_str = timestamp.strftime("%Y%m%d-%H%M%S")
    # Add random suffix for uniqueness
    hash_input = f"{sender}-{ts_str}-{os.urandom(4).hex()}"
    hash_suffix = hashlib.sha256(hash_input.encode()).hexdigest()[:6]
    return f"msg-{ts_str}-{sender}-{hash_suffix}"


def create_message(
    msg_id: str,
    sender: str,
    recipient: str,
    timestamp: datetime,
    msg_type: str,
    subject: str,
    content: str,
) -> str:
    """Create message content in the specified format."""
    ts_iso = timestamp.isoformat().replace("+00:00", "Z")

    message = f"""---
id: {msg_id}
from: {sender}
to: {recipient}
timestamp: {ts_iso}
type: {msg_type}
subject: {subject}
status: unread
---

## Content

{content}

## Requested Action

"""
    # Add action items based on type
    if msg_type == "suggestion":
        message += "- [ ] Review and integrate suggested changes\n"
        message += "- [ ] Reply with questions if unclear\n"
    elif msg_type == "question":
        message += "- [ ] Reply with answer\n"
    elif msg_type == "handoff":
        message += "- [ ] Acknowledge receipt of ownership\n"
        message += "- [ ] Review handed-off work\n"
    elif msg_type == "info":
        message += "- [ ] Acknowledge receipt\n"
    elif msg_type == "review-request":
        message += "- [ ] Review the work\n"
        message += "- [ ] Approve or provide feedback\n"

    return message


def send_message(
    recipient: str,
    msg_type: str,
    subject: str,
    content: str,
    dry_run: bool = False,
) -> tuple[bool, str]:
    """Send a message to the recipient's inbox.

    Returns:
        Tuple of (success, message_path_or_error)
    """
    # Validate message type
    if msg_type not in MESSAGE_TYPES:
        return False, f"Invalid message type: {msg_type}. Valid types: {', '.join(MESSAGE_TYPES.keys())}"

    # Get sender identity
    sender = get_sender_identity()
    timestamp = datetime.now(timezone.utc)

    # Generate message ID and filename
    msg_id = generate_message_id(sender, timestamp)
    ts_str = timestamp.strftime("%Y%m%d_%H%M%S")
    filename = f"{ts_str}_from-{sender}_{msg_type}.md"

    # Create message content
    message_content = create_message(
        msg_id, sender, recipient, timestamp, msg_type, subject, content
    )

    # Determine inbox path (always in main repo)
    repo_root = get_repo_root()
    inbox_dir = repo_root / ".claude" / "messages" / "inbox" / recipient

    if dry_run:
        print(f"[DRY RUN] Would create message:")
        print(f"  From: {sender}")
        print(f"  To: {recipient}")
        print(f"  Type: {msg_type}")
        print(f"  Subject: {subject}")
        print(f"  Path: {inbox_dir / filename}")
        print("\n--- Message Content ---")
        print(message_content)
        return True, str(inbox_dir / filename)

    # Create inbox directory if needed
    inbox_dir.mkdir(parents=True, exist_ok=True)

    # Write message
    message_path = inbox_dir / filename
    with open(message_path, "w") as f:
        f.write(message_content)

    return True, str(message_path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send a message to another Claude Code instance",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--to",
        required=True,
        help="Recipient identity (worktree name or session name)",
    )
    parser.add_argument(
        "--type",
        required=True,
        choices=MESSAGE_TYPES.keys(),
        help="Message type",
    )
    parser.add_argument(
        "--subject",
        required=True,
        help="Message subject",
    )
    parser.add_argument(
        "--content",
        help="Message content (inline)",
    )
    parser.add_argument(
        "--content-file",
        help="Path to file containing message content",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be sent without actually sending",
    )

    args = parser.parse_args()

    # Get content from file or inline
    if args.content_file:
        try:
            with open(args.content_file) as f:
                content = f.read()
        except FileNotFoundError:
            print(f"Error: Content file not found: {args.content_file}", file=sys.stderr)
            return 1
    elif args.content:
        content = args.content
    else:
        print("Error: Either --content or --content-file is required", file=sys.stderr)
        return 1

    # Send the message
    success, result = send_message(
        recipient=args.to,
        msg_type=args.type,
        subject=args.subject,
        content=content,
        dry_run=args.dry_run,
    )

    if success:
        if args.dry_run:
            print("\n[DRY RUN] Message would be sent successfully")
        else:
            print(f"Message sent successfully: {result}")
        return 0
    else:
        print(f"Error: {result}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

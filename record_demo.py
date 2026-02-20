#!/usr/bin/env python3
"""Record an asciinema demo of the OpenPlanter TUI.

Launches the agent in demo mode, types a prompt with realistic keystroke
timing, waits for the agent to finish, then exits. The result is saved
as an asciinema .cast file.

Usage:
    python record_demo.py                       # record to demo.cast
    python record_demo.py -o my_demo.cast       # custom output path
    python record_demo.py --prompt "Custom task" # custom prompt

Convert to GIF afterward:
    pip install agg          # asciinema GIF generator
    agg demo.cast demo.gif
"""

from __future__ import annotations

import argparse
import random
import re
import sys
import time

import pexpect

DEFAULT_PROMPT = "Investigate local politicians for evidence of corruption."
TYPING_DELAY_MIN = 0.04  # seconds between keystrokes
TYPING_DELAY_MAX = 0.12

# Regex to strip ANSI escape sequences from terminal output.
_RE_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\].*?\x07|\x1b\[[\?]?[0-9;]*[hlm]")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from *text*."""
    return _RE_ANSI.sub("", text)


def simulate_typing(child: pexpect.spawn, text: str) -> None:
    """Send text one character at a time with human-like delays."""
    for ch in text:
        child.send(ch)
        time.sleep(random.uniform(TYPING_DELAY_MIN, TYPING_DELAY_MAX))


def _wait_for_marker(child: pexpect.spawn, marker: str, timeout: int) -> bool:
    """Poll child output until *marker* appears in ANSI-stripped text.

    Rich's Live display injects cursor-movement and clearing sequences that
    fragment text patterns, making pexpect's built-in expect() unreliable.
    This function accumulates raw output, strips ANSI codes, and searches
    the clean text for the marker.

    Returns True if found, False on timeout.
    """
    buf = ""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            chunk = child.read_nonblocking(size=4096, timeout=2)
            buf += chunk
            # Keep only the last 64KB to avoid unbounded memory growth
            # from Rich's rapid Live display updates.
            if len(buf) > 65536:
                buf = buf[-65536:]
            if marker in _strip_ansi(buf):
                return True
        except pexpect.TIMEOUT:
            continue
        except pexpect.EOF:
            return False
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Record an OpenPlanter demo.")
    parser.add_argument("-o", "--output", default="demo.cast", help="Output .cast file path.")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="Prompt to type into the TUI.")
    parser.add_argument("--cols", type=int, default=120, help="Terminal width.")
    parser.add_argument("--rows", type=int, default=32, help="Terminal height.")
    parser.add_argument("--max-steps", type=int, default=8, help="Max agent steps (keeps the recording short).")
    parser.add_argument("--timeout", type=int, default=600, help="Max seconds to wait for the agent to finish.")
    args = parser.parse_args()

    agent_cmd = f"python -m agent --demo --max-steps {args.max_steps}"
    cmd = f"asciinema rec --overwrite -c '{agent_cmd}' {args.output}"
    print(f"Starting recording -> {args.output} ({args.cols}x{args.rows})")

    child = pexpect.spawn(
        "bash", ["-c", cmd],
        encoding="utf-8",
        timeout=args.timeout,
        dimensions=(args.rows, args.cols),
    )
    child.logfile_read = sys.stdout

    # Wait for the TUI to boot (look for the "you>" prompt).
    # The initial prompt appears before any Rich Live display, so
    # pexpect's built-in expect() works here.
    child.expect(r"you>", timeout=30)
    time.sleep(1.0)

    # Type the prompt with realistic timing
    simulate_typing(child, args.prompt)
    time.sleep(0.5)
    child.sendline("")  # Enter

    # Wait for the agent to finish. After the final answer, the TUI prints
    # a "tokens:" summary line. We poll and strip ANSI codes to reliably
    # detect this marker despite Rich's cursor-movement sequences.
    print("\n[record_demo] Waiting for agent to finish...", file=sys.stderr)
    if not _wait_for_marker(child, "tokens:", args.timeout):
        print("\n[record_demo] WARNING: timed out waiting for 'tokens:' marker", file=sys.stderr)

    # Let the token line and the next "you>" prompt render fully
    time.sleep(3.0)

    # Exit cleanly via Ctrl+D (triggers EOFError in prompt_toolkit)
    child.sendcontrol("d")
    try:
        child.expect(pexpect.EOF, timeout=15)
    except pexpect.TIMEOUT:
        # Force-close if prompt_toolkit doesn't exit on Ctrl+D
        child.sendcontrol("c")
        time.sleep(0.5)
        child.sendcontrol("d")
        try:
            child.expect(pexpect.EOF, timeout=10)
        except pexpect.TIMEOUT:
            child.close(force=True)

    print(f"\nRecording saved to {args.output}")
    print(f"Convert to GIF: agg {args.output} demo.gif")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Render an asciinema .cast file to an MP4 video.

Uses pyte (terminal emulator) to replay the cast frame-by-frame,
Pillow to render each terminal state to an image, and ffmpeg to
encode the image sequence into a video.

Usage:
    python cast_to_video.py demo.cast -o demo.mp4
    python cast_to_video.py demo.cast -o demo.mp4 --fps 30 --font-size 16
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pyte
from PIL import Image, ImageDraw, ImageFont

# Catppuccin Mocha palette — matches the TUI's Rich theme closely.
_COLORS_256: dict[str, str] = {
    "black":         "#1e1e2e",
    "red":           "#f38ba8",
    "green":         "#a6e3a1",
    "brown":         "#f9e2af",
    "blue":          "#89b4fa",
    "magenta":       "#cba6f7",
    "cyan":          "#94e2d5",
    "white":         "#cdd6f4",
    "brightblack":   "#585b70",
    "brightred":     "#f38ba8",
    "brightgreen":   "#a6e3a1",
    "brightyellow":  "#f9e2af",
    "brightblue":    "#89b4fa",
    "brightmagenta": "#cba6f7",
    "brightcyan":    "#94e2d5",
    "brightwhite":   "#ffffff",
}

_BG_COLOR = "#1e1e2e"
_FG_COLOR = "#cdd6f4"
_CURSOR_COLOR = "#f5e0dc"

# Padding around the terminal content.
_PAD_X = 24
_PAD_Y = 16


def _color_to_rgb(color: str | None, default: str) -> tuple[int, int, int]:
    """Convert a pyte color name or hex to an RGB tuple."""
    if not color or color == "default":
        c = default
    elif color in _COLORS_256:
        c = _COLORS_256[color]
    elif color.startswith("#"):
        c = color
    elif len(color) == 6:
        # Raw hex without #
        c = f"#{color}"
    else:
        c = default
    c = c.lstrip("#")
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    """Load a monospace font, falling back gracefully."""
    candidates = [
        "/System/Library/Fonts/SFMono-Regular.otf",
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Monaco.dfont",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _measure_char(font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    """Measure the width and height of a single character in the font."""
    bbox = font.getbbox("M")
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    # Use line spacing for height
    metrics = font.getmetrics()
    line_h = metrics[0] + metrics[1]
    return w, max(h, line_h)


def render_frame(
    screen: pyte.Screen,
    font: ImageFont.FreeTypeFont,
    char_w: int,
    char_h: int,
    img_w: int,
    img_h: int,
) -> Image.Image:
    """Render the current terminal screen state to a Pillow Image."""
    img = Image.new("RGB", (img_w, img_h), _color_to_rgb(None, _BG_COLOR))
    draw = ImageDraw.Draw(img)

    y_offset = font.getmetrics()[0] - font.getbbox("M")[1]

    for row in range(screen.lines):
        for col in range(screen.columns):
            char = screen.buffer[row][col]
            ch = char.data if char.data else " "

            # Background
            bg = _color_to_rgb(char.bg, _BG_COLOR)
            if char.reverse:
                fg = _color_to_rgb(char.bg, _BG_COLOR)
                bg = _color_to_rgb(char.fg, _FG_COLOR)
            else:
                fg = _color_to_rgb(char.fg, _FG_COLOR)

            x = _PAD_X + col * char_w
            y = _PAD_Y + row * char_h

            if bg != _color_to_rgb(None, _BG_COLOR):
                draw.rectangle([x, y, x + char_w, y + char_h], fill=bg)

            if ch.strip():
                draw.text(
                    (x, y + y_offset),
                    ch,
                    font=font,
                    fill=fg,
                )

    return img


def main() -> None:
    parser = argparse.ArgumentParser(description="Render .cast to MP4 video.")
    parser.add_argument("input", help="Input .cast file.")
    parser.add_argument("-o", "--output", default="demo.mp4", help="Output video path.")
    parser.add_argument("--fps", type=int, default=24, help="Video frame rate.")
    parser.add_argument("--font-size", type=int, default=16, help="Font size in pixels.")
    parser.add_argument("--speed", type=float, default=1.0, help="Playback speed multiplier.")
    parser.add_argument("--max-pause", type=float, default=3.0, help="Cap pauses at this many seconds.")
    args = parser.parse_args()

    # Parse the .cast file
    with open(args.input) as f:
        lines = f.readlines()

    header = json.loads(lines[0])
    cols = header.get("width", 80)
    rows = header.get("height", 24)

    events: list[tuple[float, str]] = []
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        try:
            ts, etype, data = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if etype == "o":
            events.append((float(ts), data))

    if not events:
        print("No output events found in .cast file.", file=sys.stderr)
        sys.exit(1)

    # Set up terminal emulator
    screen = pyte.Screen(cols, rows)
    stream = pyte.Stream(screen)

    # Set up font and image dimensions
    font = _load_font(args.font_size)
    char_w, char_h = _measure_char(font)
    img_w = 2 * _PAD_X + cols * char_w
    img_h = 2 * _PAD_Y + rows * char_h

    print(f"Terminal: {cols}x{rows}")
    print(f"Char size: {char_w}x{char_h}")
    print(f"Image size: {img_w}x{img_h}")
    print(f"Events: {len(events)}")
    print(f"Duration: {events[-1][0]:.1f}s (speed {args.speed}x)")

    # Launch ffmpeg to encode frames
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-pixel_format", "rgb24",
        "-video_size", f"{img_w}x{img_h}",
        "-framerate", str(args.fps),
        "-i", "pipe:0",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        args.output,
    ]
    ffmpeg = subprocess.Popen(
        ffmpeg_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    frame_duration = 1.0 / args.fps
    current_time = 0.0
    event_idx = 0
    total_frames = 0

    # Render initial frame (blank terminal)
    frame = render_frame(screen, font, char_w, char_h, img_w, img_h)
    ffmpeg.stdin.write(frame.tobytes())
    total_frames += 1

    # Walk through events and render frames at the target FPS
    while event_idx < len(events):
        current_time += frame_duration * args.speed

        # Feed all events up to current_time
        fed = False
        while event_idx < len(events):
            ts, data = events[event_idx]

            # Cap long pauses
            if event_idx > 0:
                gap = ts - events[event_idx - 1][0]
                if gap > args.max_pause:
                    # Shift all remaining timestamps
                    shift = gap - args.max_pause
                    events = [
                        (t - shift if i >= event_idx else t, d)
                        for i, (t, d) in enumerate(events)
                    ]
                    ts = events[event_idx][0]

            if ts > current_time:
                break
            stream.feed(data)
            event_idx += 1
            fed = True

        # Render frame
        frame = render_frame(screen, font, char_w, char_h, img_w, img_h)
        ffmpeg.stdin.write(frame.tobytes())
        total_frames += 1

        if total_frames % (args.fps * 5) == 0:
            print(f"  {total_frames} frames ({current_time / args.speed:.1f}s)...", file=sys.stderr)

    # Hold the final frame for 2 seconds
    try:
        for _ in range(args.fps * 2):
            ffmpeg.stdin.write(frame.tobytes())
            total_frames += 1
    except BrokenPipeError:
        pass

    try:
        ffmpeg.stdin.close()
    except (BrokenPipeError, ValueError):
        pass
    stderr = ffmpeg.communicate()[1].decode(errors="replace")
    if ffmpeg.returncode != 0:
        print(f"ffmpeg failed:\n{stderr}", file=sys.stderr)
        sys.exit(1)

    output_size = Path(args.output).stat().st_size
    print(f"\nDone: {total_frames} frames, {output_size / 1024:.0f}KB -> {args.output}")


if __name__ == "__main__":
    main()

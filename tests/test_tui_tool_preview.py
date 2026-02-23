"""Tests for TUI tool argument preview during model streaming."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from agent.tui import _ActivityDisplay


# ---------------------------------------------------------------------------
# _extract_preview
# ---------------------------------------------------------------------------

class TestExtractPreview:
    def test_extracts_content_key(self):
        buf = '{"path": "/foo/bar.py", "content": "import os\\nimport sys\\ndef main():\\n    print(\\"hello\\")'
        preview = _ActivityDisplay._extract_preview(buf)
        assert "import os" in preview
        assert "import sys" in preview
        assert 'print("hello")' in preview

    def test_extracts_patch_key(self):
        buf = '{"patch": "--- a/foo.py\\n+++ b/foo.py\\n@@ -1 +1 @@\\n-old\\n+new'
        preview = _ActivityDisplay._extract_preview(buf)
        assert "--- a/foo.py" in preview
        assert "+++ b/foo.py" in preview

    def test_fallback_to_raw_tail(self):
        buf = '{"path": "/foo/bar.py", "query": "search term"}'
        preview = _ActivityDisplay._extract_preview(buf)
        # Should fall back to last 3 lines of raw buffer
        assert "search term" in preview

    def test_empty_buffer(self):
        assert _ActivityDisplay._extract_preview("") == ""

    def test_unescape_newlines(self):
        buf = '{"content": "line1\\nline2\\nline3"}'
        preview = _ActivityDisplay._extract_preview(buf)
        lines = preview.splitlines()
        assert len(lines) >= 3
        assert lines[0] == "line1"
        assert lines[1] == "line2"

    def test_unescape_tabs(self):
        buf = '{"content": "\\tindented"}'
        preview = _ActivityDisplay._extract_preview(buf)
        assert "\tindented" in preview

    def test_trailing_backslash(self):
        buf = '{"content": "partial\\'
        preview = _ActivityDisplay._extract_preview(buf)
        assert "partial" in preview

    def test_content_no_space_after_colon(self):
        buf = '{"content":"no space"}'
        preview = _ActivityDisplay._extract_preview(buf)
        assert "no space" in preview


# ---------------------------------------------------------------------------
# _ActivityDisplay.feed with new delta types
# ---------------------------------------------------------------------------

class TestFeedToolDeltas:
    def _make_display(self):
        console = MagicMock()
        d = _ActivityDisplay(console=console)
        d._active = True
        d._start_time = time.monotonic()
        d._live = MagicMock()
        return d

    def test_tool_call_start_sets_tool_args_mode(self):
        d = self._make_display()
        d._mode = "thinking"
        d.feed("tool_call_start", "write_file")
        assert d.mode == "tool_args"
        assert d._tool_arg_name == "write_file"
        assert d._tool_arg_buf == ""

    def test_tool_call_args_accumulates(self):
        d = self._make_display()
        d._mode = "tool_args"
        d._tool_arg_name = "write_file"
        d.feed("tool_call_args", '{"path": ')
        d.feed("tool_call_args", '"/foo.py"')
        assert d._tool_arg_buf == '{"path": "/foo.py"'

    def test_tool_call_start_resets_buffer(self):
        d = self._make_display()
        d._mode = "tool_args"
        d._tool_arg_buf = "old data"
        d.feed("tool_call_start", "edit_file")
        assert d._tool_arg_buf == ""
        assert d._tool_arg_name == "edit_file"

    def test_text_delta_transitions_from_tool_args(self):
        d = self._make_display()
        d._mode = "tool_args"
        d._tool_arg_buf = "some args"
        d.feed("text", "Here is the answer")
        assert d.mode == "streaming"
        assert d._text_buf == "Here is the answer"

    def test_thinking_delta_ignored_in_tool_args(self):
        d = self._make_display()
        d._mode = "tool_args"
        d.feed("thinking", "pondering")
        # thinking delta accumulates in text_buf (mode stays tool_args)
        assert d.mode == "tool_args"
        assert d._text_buf == "pondering"

    def test_feed_not_active(self):
        console = MagicMock()
        d = _ActivityDisplay(console=console)
        d._active = False
        d.feed("tool_call_start", "write_file")
        assert d.mode == "thinking"  # unchanged


# ---------------------------------------------------------------------------
# _build_renderable in tool_args mode
# ---------------------------------------------------------------------------

class TestBuildRenderableToolArgs:
    def _make_display(self):
        console = MagicMock()
        d = _ActivityDisplay(console=console)
        d._active = True
        d._start_time = time.monotonic()
        d._live = MagicMock()
        return d

    def test_tool_args_header(self):
        d = self._make_display()
        d._mode = "tool_args"
        d._tool_arg_name = "write_file"
        d._step_label = "Step 4/20"
        renderable = d._build_renderable()
        rendered = str(renderable)
        assert "Generating write_file" in rendered
        assert "Step 4/20" in rendered

    def test_tool_args_with_content_preview(self):
        d = self._make_display()
        d._mode = "tool_args"
        d._tool_arg_name = "write_file"
        d._tool_arg_buf = '{"path": "/foo.py", "content": "import os\\nimport sys"}'
        renderable = d._build_renderable()
        rendered = str(renderable)
        assert "import os" in rendered
        assert "import sys" in rendered

    def test_tool_args_empty_buffer(self):
        d = self._make_display()
        d._mode = "tool_args"
        d._tool_arg_name = "write_file"
        d._tool_arg_buf = ""
        renderable = d._build_renderable()
        rendered = str(renderable)
        assert "Generating write_file" in rendered

    def test_tool_args_long_lines_truncated(self):
        d = self._make_display()
        d._mode = "tool_args"
        d._tool_arg_name = "write_file"
        long_line = "x" * 200
        d._tool_arg_buf = f'{{"content": "{long_line}"}}'
        renderable = d._build_renderable()
        rendered = str(renderable)
        assert "..." in rendered


# ---------------------------------------------------------------------------
# Buffer reset on mode transitions
# ---------------------------------------------------------------------------

class TestBufferReset:
    def _make_display(self):
        console = MagicMock()
        d = _ActivityDisplay(console=console)
        d._active = True
        d._start_time = time.monotonic()
        d._live = MagicMock()
        return d

    def test_set_tool_clears_tool_arg_buffers(self):
        d = self._make_display()
        d._mode = "tool_args"
        d._tool_arg_buf = "old args"
        d._tool_arg_name = "write_file"
        d.set_tool("run_shell", key_arg="ls -la")
        assert d._tool_arg_buf == ""
        assert d._tool_arg_name == ""

    def test_stop_clears_tool_arg_buffers(self):
        d = self._make_display()
        d._mode = "tool_args"
        d._tool_arg_buf = "some data"
        d._tool_arg_name = "write_file"
        d._live.__exit__ = MagicMock(return_value=False)
        d.stop()
        assert d._tool_arg_buf == ""
        assert d._tool_arg_name == ""

    def test_start_clears_tool_arg_buffers(self):
        d = self._make_display()
        d._tool_arg_buf = "leftover"
        d._tool_arg_name = "old_tool"
        d._live.__exit__ = MagicMock(return_value=False)
        d.stop()
        # Re-start
        from unittest.mock import patch as mpatch
        with mpatch("rich.live.Live") as MockLive:
            instance = MockLive.return_value
            instance.__enter__ = MagicMock(return_value=instance)
            instance.__exit__ = MagicMock(return_value=False)
            d.start(mode="thinking")
        assert d._tool_arg_buf == ""
        assert d._tool_arg_name == ""


# ---------------------------------------------------------------------------
# Model _forward_delta emits new delta types
# ---------------------------------------------------------------------------

class TestOpenAIForwardDelta:
    def test_forwards_tool_call_start_and_args(self):
        from agent.model import OpenAICompatibleModel

        received: list[tuple[str, str]] = []

        model = OpenAICompatibleModel(
            model="test",
            api_key="test",
            base_url="http://test/v1",
        )
        model.on_content_delta = lambda dtype, text: received.append((dtype, text))

        # Simulate SSE events via the _forward_delta closure.
        # We need to reach the inner function — call complete() with a mock.
        # Instead, reconstruct a similar delta forwarding path.
        # Create an event with tool_call name
        event_name = {
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "id": "call_1",
                        "function": {"name": "write_file", "arguments": ""},
                    }]
                },
                "finish_reason": None,
            }]
        }
        event_args = {
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "function": {"arguments": '{"path": "foo.py"'},
                    }]
                },
                "finish_reason": None,
            }]
        }

        # Extract _forward_delta by mocking _http_stream_sse
        from unittest.mock import patch as mpatch

        captured_cb = [None]

        def fake_stream(url, method, headers, payload,
                        first_byte_timeout=10, stream_timeout=120,
                        max_retries=3, on_sse_event=None):
            captured_cb[0] = on_sse_event
            # Call on_sse_event with our test events
            if on_sse_event:
                on_sse_event("", event_name)
                on_sse_event("", event_args)
            # Return events for accumulation
            return [
                ("", event_name),
                ("", event_args),
                ("", {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}),
            ]

        with mpatch("agent.model._http_stream_sse", fake_stream):
            model.complete(model.create_conversation("sys", "hello"))

        assert ("tool_call_start", "write_file") in received
        assert ("tool_call_args", '{"path": "foo.py"') in received


class TestAnthropicForwardDelta:
    def test_forwards_tool_call_start_and_args(self):
        from agent.model import AnthropicModel

        received: list[tuple[str, str]] = []

        model = AnthropicModel(
            model="claude-test",
            api_key="test",
            base_url="http://test/v1",
        )
        model.on_content_delta = lambda dtype, text: received.append((dtype, text))

        # Anthropic events for tool_use
        events = [
            ("message_start", {
                "type": "message_start",
                "message": {"usage": {"input_tokens": 10}},
            }),
            ("content_block_start", {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "write_file",
                },
            }),
            ("content_block_delta", {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": '{"path":',
                },
            }),
            ("content_block_delta", {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": ' "foo.py"}',
                },
            }),
            ("content_block_stop", {
                "type": "content_block_stop",
                "index": 0,
            }),
            ("message_delta", {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use"},
                "usage": {"output_tokens": 20},
            }),
            ("message_stop", {"type": "message_stop"}),
        ]

        from unittest.mock import patch as mpatch

        def fake_stream(url, method, headers, payload,
                        first_byte_timeout=10, stream_timeout=120,
                        max_retries=3, on_sse_event=None):
            if on_sse_event:
                for evt_type, data in events:
                    on_sse_event(evt_type, data)
            return events

        with mpatch("agent.model._http_stream_sse", fake_stream):
            model.complete(model.create_conversation("sys", "hello"))

        assert ("tool_call_start", "write_file") in received
        assert ("tool_call_args", '{"path":') in received
        assert ("tool_call_args", ' "foo.py"}') in received

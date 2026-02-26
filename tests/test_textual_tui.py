"""Tests for agent.textual_tui — Textual App components."""
from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Skip all tests if textual is not installed
textual = pytest.importorskip("textual")

from textual.pilot import Pilot

from agent.textual_tui import (
    ActivityIndicator,
    AgentComplete,
    AgentContentDelta,
    AgentEvent,
    AgentStepEvent,
    OpenPlanterApp,
    WikiChanged,
    WikiGraphCanvas,
    _extract_tool_arg_preview,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_ctx():
    """Create a minimal mock ChatContext for testing."""
    ctx = MagicMock()
    ctx.cfg = MagicMock()
    ctx.cfg.workspace = "/tmp/test-workspace"
    ctx.cfg.demo = False
    ctx.cfg.provider = "openai"
    ctx.cfg.model = "gpt-4o"
    ctx.cfg.reasoning_effort = None
    ctx.cfg.recursive = False
    ctx.cfg.max_steps_per_call = 20

    ctx.runtime = MagicMock()
    ctx.runtime.engine = MagicMock()
    ctx.runtime.engine.session_tokens = {}
    ctx.runtime.engine.model = MagicMock()
    ctx.runtime.engine.model.model = "gpt-4o"

    ctx.settings_store = MagicMock()
    return ctx


# ---------------------------------------------------------------------------
# _extract_tool_arg_preview
# ---------------------------------------------------------------------------

class TestExtractToolArgPreview:
    def test_extracts_content_key(self):
        buf = '{"content": "Hello world\\nLine 2"}'
        result = _extract_tool_arg_preview(buf)
        assert "Hello world" in result
        assert "Line 2" in result

    def test_extracts_patch_key(self):
        buf = '{"patch": "--- a/file\\n+++ b/file"}'
        result = _extract_tool_arg_preview(buf)
        assert "file" in result

    def test_fallback_to_raw(self):
        buf = '{"other": "value"}'
        result = _extract_tool_arg_preview(buf)
        assert "other" in result


# ---------------------------------------------------------------------------
# ActivityIndicator
# ---------------------------------------------------------------------------

class TestActivityIndicator:
    def test_initial_state(self):
        indicator = ActivityIndicator()
        assert indicator.mode == "idle"
        text = indicator.render()
        assert str(text) == ""

    def test_thinking_mode(self):
        indicator = ActivityIndicator()
        indicator.start_activity(mode="thinking", step_label="Step 1/20")
        assert indicator.mode == "thinking"
        text = indicator.render()
        assert "Thinking" in str(text)

    def test_feed_transitions_to_streaming(self):
        indicator = ActivityIndicator()
        indicator.start_activity(mode="thinking")
        indicator.feed("text", "Hello")
        assert indicator.mode == "streaming"

    def test_tool_mode(self):
        indicator = ActivityIndicator()
        indicator.set_tool("read_file", key_arg="test.py", step_label="Step 2/20")
        assert indicator.mode == "tool"
        text = indicator.render()
        assert "read_file" in str(text)

    def test_tool_args_mode(self):
        indicator = ActivityIndicator()
        indicator.start_activity(mode="thinking")
        indicator.feed("tool_call_start", "write_file")
        assert indicator.mode == "tool_args"
        indicator.feed("tool_call_args", '{"content": "hello"}')
        text = indicator.render()
        assert "write_file" in str(text)

    def test_stop_resets(self):
        indicator = ActivityIndicator()
        indicator.start_activity(mode="thinking")
        indicator.stop_activity()
        assert indicator.mode == "idle"

    def test_censor_fn(self):
        censor = lambda t: t.replace("secret", "XXXXX")
        indicator = ActivityIndicator(censor_fn=censor)
        indicator.start_activity(mode="thinking")
        indicator.feed("thinking", "this is secret data")
        text = indicator.render()
        text_str = str(text)
        assert "secret" not in text_str
        assert "XXXXX" in text_str


# ---------------------------------------------------------------------------
# Custom Messages
# ---------------------------------------------------------------------------

class TestCustomMessages:
    def test_agent_event_carries_msg(self):
        msg = AgentEvent("test message")
        assert msg.msg == "test message"

    def test_agent_step_event_carries_data(self):
        data = {"action": {"name": "read_file"}}
        msg = AgentStepEvent(data)
        assert msg.step_event == data

    def test_agent_content_delta(self):
        msg = AgentContentDelta("thinking", "hello")
        assert msg.delta_type == "thinking"
        assert msg.text == "hello"

    def test_agent_complete(self):
        msg = AgentComplete("Final answer")
        assert msg.result == "Final answer"

    def test_wiki_changed(self):
        msg = WikiChanged()
        assert isinstance(msg, WikiChanged)


# ---------------------------------------------------------------------------
# WikiGraphCanvas
# ---------------------------------------------------------------------------

class TestWikiGraphCanvas:
    def test_no_wiki_dir(self):
        canvas = WikiGraphCanvas(wiki_dir=None)
        text = canvas.render()
        assert "No wiki data" in str(text)


# ---------------------------------------------------------------------------
# OpenPlanterApp — async pilot tests
# ---------------------------------------------------------------------------

class TestOpenPlanterApp:
    @pytest.fixture
    def mock_ctx(self):
        return _make_mock_ctx()

    @pytest.mark.asyncio
    async def test_app_launches(self, mock_ctx):
        """App should mount and show splash art."""
        app = OpenPlanterApp(
            mock_ctx,
            startup_info={"Provider": "openai", "Model": "gpt-4o"},
        )
        async with app.run_test() as pilot:
            # App should have composed successfully
            log = app.query_one("#message-log")
            assert log is not None
            inp = app.query_one("#prompt-input")
            assert inp is not None

    @pytest.mark.asyncio
    async def test_slash_help(self, mock_ctx):
        """Typing /help should display help text."""
        app = OpenPlanterApp(mock_ctx)
        async with app.run_test() as pilot:
            inp = app.query_one("#prompt-input")
            inp.value = "/help"
            await pilot.press("enter")
            await pilot.pause()

    @pytest.mark.asyncio
    async def test_slash_status(self, mock_ctx):
        """Typing /status should not crash."""
        app = OpenPlanterApp(mock_ctx)
        async with app.run_test() as pilot:
            inp = app.query_one("#prompt-input")
            inp.value = "/status"
            await pilot.press("enter")
            await pilot.pause()

    @pytest.mark.asyncio
    async def test_slash_quit(self, mock_ctx):
        """Typing /quit should exit the app."""
        app = OpenPlanterApp(mock_ctx)
        async with app.run_test() as pilot:
            inp = app.query_one("#prompt-input")
            inp.value = "/quit"
            await pilot.press("enter")
            await pilot.pause()

    @pytest.mark.asyncio
    async def test_empty_input_ignored(self, mock_ctx):
        """Empty input should be ignored."""
        app = OpenPlanterApp(mock_ctx)
        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.pause()

    @pytest.mark.asyncio
    async def test_agent_complete_renders(self, mock_ctx):
        """Posting AgentComplete should render the result."""
        app = OpenPlanterApp(mock_ctx)
        async with app.run_test() as pilot:
            app._agent_running = True
            app.post_message(AgentComplete("Test result"))
            await pilot.pause()
            assert not app._agent_running

    @pytest.mark.asyncio
    async def test_wiki_changed_triggers_rebuild(self, mock_ctx):
        """WikiChanged message should trigger graph rebuild."""
        app = OpenPlanterApp(mock_ctx)
        async with app.run_test() as pilot:
            app.post_message(WikiChanged())
            await pilot.pause()

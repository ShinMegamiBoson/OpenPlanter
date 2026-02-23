"""Tests for RichREPL initialization, run loop, slash commands, and input queuing."""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.config import AgentConfig
from agent.settings import SettingsStore
from agent.tui import ChatContext, RichREPL, _queue_prompt_style, dispatch_slash_command


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(tmp_path: Path) -> ChatContext:
    """Build a minimal ChatContext backed by *tmp_path*."""
    cfg = AgentConfig(workspace=tmp_path)
    runtime = MagicMock()
    runtime.engine.model.model = "test-model"
    runtime.engine.session_tokens = {}
    settings_store = SettingsStore(workspace=tmp_path)
    return ChatContext(runtime=runtime, cfg=cfg, settings_store=settings_store)


# ---------------------------------------------------------------------------
# _queue_prompt_style
# ---------------------------------------------------------------------------

class TestQueuePromptStyle:
    def test_returns_style_object(self):
        from prompt_toolkit.styles import Style
        s = _queue_prompt_style()
        assert isinstance(s, Style)

    def test_dim_class_resolves(self):
        """The 'dim' class used in the queued-input prompt must be mapped."""
        s = _queue_prompt_style()
        # Style.style_rules is a list of tuples; find the 'dim' entry.
        rules = s.style_rules
        names = [name for name, _ in rules]
        assert "dim" in names


# ---------------------------------------------------------------------------
# RichREPL.__init__
# ---------------------------------------------------------------------------

class TestRichREPLInit:
    def test_attributes_initialized(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        repl = RichREPL(ctx)

        assert repl.ctx is ctx
        assert repl._queued_input == []
        assert isinstance(repl._queued_input, list)
        assert repl._agent_thread is None
        assert repl._agent_result is None
        assert repl._current_step is None
        assert repl._demo_hook is None

    def test_startup_info_defaults_to_empty(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        repl = RichREPL(ctx)
        assert repl._startup_info == {}

    def test_startup_info_stored(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        info = {"model": "gpt-4", "provider": "openai"}
        repl = RichREPL(ctx, startup_info=info)
        assert repl._startup_info == info

    def test_session_created(self, tmp_path):
        from prompt_toolkit import PromptSession
        ctx = _make_ctx(tmp_path)
        repl = RichREPL(ctx)
        assert isinstance(repl.session, PromptSession)


# ---------------------------------------------------------------------------
# RichREPL._on_event
# ---------------------------------------------------------------------------

class TestOnEvent:
    def _make_repl(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        repl = RichREPL(ctx)
        repl._activity = MagicMock()
        return repl

    def test_calling_model_starts_thinking(self, tmp_path):
        repl = self._make_repl(tmp_path)
        repl._on_event("[d0/s1] calling model gpt-4")
        repl._activity.start.assert_called_once_with(
            mode="thinking", step_label=f"Step 1/{repl.ctx.cfg.max_steps_per_call}",
        )

    def test_subtask_stops_activity_and_renders_rule(self, tmp_path):
        repl = self._make_repl(tmp_path)
        repl._on_event("[d1/s2] >> entering subtask: summarize")
        repl._activity.stop.assert_called_once()

    def test_execute_leaf_stops_activity(self, tmp_path):
        repl = self._make_repl(tmp_path)
        repl._on_event("[d0/s1] >> executing leaf: run test")
        repl._activity.stop.assert_called_once()

    def test_error_stops_activity(self, tmp_path):
        repl = self._make_repl(tmp_path)
        repl._on_event("[d0/s1] Model error: timeout")
        repl._activity.stop.assert_called_once()

    def test_tool_start_sets_tool(self, tmp_path):
        repl = self._make_repl(tmp_path)
        repl._on_event("[d0/s3] read_file(path=foo.py)")
        repl._activity.set_tool.assert_called_once_with(
            "read_file",
            key_arg="path=foo.py",
            step_label=f"Step 3/{repl.ctx.cfg.max_steps_per_call}",
        )


# ---------------------------------------------------------------------------
# RichREPL._on_step
# ---------------------------------------------------------------------------

class TestOnStep:
    def _make_repl(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        repl = RichREPL(ctx)
        repl._activity = MagicMock()
        return repl

    def test_model_turn_creates_step_state(self, tmp_path):
        repl = self._make_repl(tmp_path)
        repl._on_step({
            "action": {"name": "_model_turn"},
            "depth": 0,
            "step": 2,
            "model_text": "Hello",
            "elapsed_sec": 1.5,
            "input_tokens": 100,
            "output_tokens": 50,
        })
        assert repl._current_step is not None
        assert repl._current_step.step == 2
        assert repl._current_step.model_text == "Hello"
        assert repl._current_step.input_tokens == 100

    def test_tool_call_appended_to_step(self, tmp_path):
        repl = self._make_repl(tmp_path)
        # First create a step
        repl._on_step({
            "action": {"name": "_model_turn"},
            "depth": 0, "step": 1,
            "model_text": "", "elapsed_sec": 0.5,
            "input_tokens": 50, "output_tokens": 20,
        })
        # Then append a tool call
        repl._on_step({
            "action": {"name": "read_file", "arguments": {"path": "foo.py"}},
            "elapsed_sec": 0.3,
            "observation": "",
        })
        assert len(repl._current_step.tool_calls) == 1
        assert repl._current_step.tool_calls[0].name == "read_file"
        assert repl._current_step.tool_calls[0].key_arg == "foo.py"

    def test_error_tool_call_flagged(self, tmp_path):
        repl = self._make_repl(tmp_path)
        repl._on_step({
            "action": {"name": "_model_turn"},
            "depth": 0, "step": 1,
            "model_text": "", "elapsed_sec": 0.5,
            "input_tokens": 50, "output_tokens": 20,
        })
        repl._on_step({
            "action": {"name": "run_shell", "arguments": {"command": "ls"}},
            "elapsed_sec": 0.1,
            "observation": "Tool run_shell crashed with error",
        })
        assert repl._current_step.tool_calls[0].is_error is True

    def test_final_flushes_step(self, tmp_path):
        repl = self._make_repl(tmp_path)
        repl._on_step({
            "action": {"name": "_model_turn"},
            "depth": 0, "step": 1,
            "model_text": "done", "elapsed_sec": 0.5,
            "input_tokens": 50, "output_tokens": 20,
        })
        assert repl._current_step is not None
        repl._on_step({"action": {"name": "final"}})
        assert repl._current_step is None

    def test_no_step_ignores_tool_call(self, tmp_path):
        """Tool call events before any _model_turn are silently ignored."""
        repl = self._make_repl(tmp_path)
        assert repl._current_step is None
        repl._on_step({
            "action": {"name": "read_file", "arguments": {"path": "x.py"}},
            "elapsed_sec": 0.1,
            "observation": "",
        })
        # Should not raise, step is still None
        assert repl._current_step is None


# ---------------------------------------------------------------------------
# RichREPL._on_content_delta
# ---------------------------------------------------------------------------

class TestOnContentDelta:
    def test_delegates_to_activity(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        repl = RichREPL(ctx)
        repl._activity = MagicMock()
        repl._on_content_delta("text", "Hello")
        repl._activity.feed.assert_called_once_with("text", "Hello")


# ---------------------------------------------------------------------------
# RichREPL.run — integration-style tests with mocked prompt
# ---------------------------------------------------------------------------

class TestRunLoop:
    def _make_repl(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        repl = RichREPL(ctx)
        repl.console = MagicMock()
        return repl

    def test_empty_input_continues(self, tmp_path):
        """Empty input lines should be skipped, not passed to the agent."""
        repl = self._make_repl(tmp_path)
        # prompt returns empty string, then EOFError to exit
        repl.session = MagicMock()
        repl.session.prompt = MagicMock(side_effect=["", "", EOFError()])
        with patch("prompt_toolkit.patch_stdout.patch_stdout"):
            repl.run()
        # runtime.solve should never have been called
        repl.ctx.runtime.solve.assert_not_called()

    def test_quit_command_exits(self, tmp_path):
        repl = self._make_repl(tmp_path)
        repl.session = MagicMock()
        repl.session.prompt = MagicMock(return_value="/quit")
        with patch("prompt_toolkit.patch_stdout.patch_stdout"):
            repl.run()
        repl.ctx.runtime.solve.assert_not_called()

    def test_exit_command_exits(self, tmp_path):
        repl = self._make_repl(tmp_path)
        repl.session = MagicMock()
        repl.session.prompt = MagicMock(return_value="/exit")
        with patch("prompt_toolkit.patch_stdout.patch_stdout"):
            repl.run()
        repl.ctx.runtime.solve.assert_not_called()

    def test_help_command_handled(self, tmp_path):
        """The /help command should be handled without running the agent, then continue."""
        repl = self._make_repl(tmp_path)
        repl.session = MagicMock()
        repl.session.prompt = MagicMock(side_effect=["/help", EOFError()])
        with patch("prompt_toolkit.patch_stdout.patch_stdout"):
            repl.run()
        repl.ctx.runtime.solve.assert_not_called()

    def test_queued_input_dequeued(self, tmp_path):
        """Pre-queued input is consumed before prompting the user."""
        repl = self._make_repl(tmp_path)
        repl._queued_input = ["hello world"]

        # The agent thread runs solve synchronously in this mock
        def fake_solve(objective, on_event=None, on_step=None, on_content_delta=None):
            return "answer"
        repl.ctx.runtime.solve = fake_solve

        # After the queued input is consumed, prompt returns /quit
        repl.session = MagicMock()
        repl.session.prompt = MagicMock(return_value="/quit")
        # The secondary prompt (while agent runs) — agent finishes immediately
        # so the secondary loop won't block. session.app.exit lets it unblock.
        repl.session.app = MagicMock()

        with patch("prompt_toolkit.patch_stdout.patch_stdout"):
            repl.run()

        # The queued input should have been consumed
        assert repl._queued_input == []

    def test_keyboard_interrupt_continues(self, tmp_path):
        repl = self._make_repl(tmp_path)
        repl.session = MagicMock()
        repl.session.prompt = MagicMock(side_effect=[KeyboardInterrupt(), "/quit"])
        with patch("prompt_toolkit.patch_stdout.patch_stdout"):
            repl.run()
        repl.ctx.runtime.solve.assert_not_called()

    def test_regular_input_runs_agent(self, tmp_path):
        """A non-slash-command input should launch the agent thread."""
        repl = self._make_repl(tmp_path)

        agent_ran = threading.Event()

        def fake_solve(objective, on_event=None, on_step=None, on_content_delta=None):
            agent_ran.set()
            return "the answer"
        repl.ctx.runtime.solve = fake_solve

        repl.session = MagicMock()
        # First prompt: regular input. Second prompt: /quit after agent finishes.
        repl.session.prompt = MagicMock(side_effect=["do something", "/quit"])
        repl.session.app = MagicMock()

        with patch("prompt_toolkit.patch_stdout.patch_stdout"):
            repl.run()

        assert agent_ran.is_set()


# ---------------------------------------------------------------------------
# dispatch_slash_command
# ---------------------------------------------------------------------------

class TestDispatchSlashCommand:
    def _make_ctx(self, tmp_path):
        return _make_ctx(tmp_path)

    def test_quit(self, tmp_path):
        ctx = self._make_ctx(tmp_path)
        assert dispatch_slash_command("/quit", ctx, emit=lambda _: None) == "quit"

    def test_exit(self, tmp_path):
        ctx = self._make_ctx(tmp_path)
        assert dispatch_slash_command("/exit", ctx, emit=lambda _: None) == "quit"

    def test_help(self, tmp_path):
        ctx = self._make_ctx(tmp_path)
        lines: list[str] = []
        result = dispatch_slash_command("/help", ctx, emit=lines.append)
        assert result == "handled"
        assert len(lines) > 0

    def test_clear(self, tmp_path):
        ctx = self._make_ctx(tmp_path)
        assert dispatch_slash_command("/clear", ctx, emit=lambda _: None) == "clear"

    def test_status(self, tmp_path):
        ctx = self._make_ctx(tmp_path)
        lines: list[str] = []
        result = dispatch_slash_command("/status", ctx, emit=lines.append)
        assert result == "handled"
        assert any("Model" in ln for ln in lines)

    def test_non_command_returns_none(self, tmp_path):
        ctx = self._make_ctx(tmp_path)
        assert dispatch_slash_command("hello world", ctx, emit=lambda _: None) is None

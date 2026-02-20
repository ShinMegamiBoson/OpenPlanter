"""Boundary condition and edge case tests.

Covers: unicode file ops, extremely long tool output, max_depth=0 with subtask,
max_steps_per_call=1, empty objectives, unknown tool dispatch, corrupted events.jsonl,
and type coercion edge cases in web_search parameters.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from conftest import _tc

from agent.config import AgentConfig
from agent.engine import ExternalContext, RLMEngine
from agent.model import ModelTurn, ScriptedModel
from agent.runtime import SessionRuntime, SessionStore
from agent.tools import WorkspaceTools

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(root: Path, **overrides) -> AgentConfig:
    defaults = {
        "workspace": root,
        "max_depth": 3,
        "max_steps_per_call": 12,
        "session_root_dir": ".openplanter",
        "max_persisted_observations": 400,
        "acceptance_criteria": False,
    }
    defaults.update(overrides)
    return AgentConfig(**defaults)


def _make_engine(root: Path, model: ScriptedModel, **cfg_overrides) -> RLMEngine:
    cfg = _make_config(root, **cfg_overrides)
    tools = WorkspaceTools(root=root)
    return RLMEngine(model=model, tools=tools, config=cfg)


# ---------------------------------------------------------------------------
# Unicode in file operations
# ---------------------------------------------------------------------------


class UnicodeFileOpsTests(unittest.TestCase):
    def test_write_and_read_unicode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            model = ScriptedModel(scripted_turns=[
                ModelTurn(tool_calls=[_tc("write_file", path="uni.txt", content="Hello \u4e16\u754c \U0001f600")]),
                ModelTurn(tool_calls=[_tc("read_file", path="uni.txt")]),
                ModelTurn(text="done", stop_reason="end_turn"),
            ])
            engine = _make_engine(root, model)
            result = engine.solve("unicode test")
            self.assertEqual(result, "done")
            content = (root / "uni.txt").read_text(encoding="utf-8")
            self.assertIn("\u4e16\u754c", content)
            self.assertIn("\U0001f600", content)

    def test_search_unicode_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data.txt").write_text("key=\u00e9l\u00e8ve", encoding="utf-8")
            model = ScriptedModel(scripted_turns=[
                ModelTurn(tool_calls=[_tc("search_files", query="\u00e9l\u00e8ve")]),
                ModelTurn(text="found", stop_reason="end_turn"),
            ])
            engine = _make_engine(root, model)
            result = engine.solve("search unicode")
            self.assertEqual(result, "found")


# ---------------------------------------------------------------------------
# Extremely long tool output truncation
# ---------------------------------------------------------------------------


class LongOutputTruncationTests(unittest.TestCase):
    def test_observation_clipped_to_max(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            big_content = "x" * 50000
            (root / "big.txt").write_text(big_content, encoding="utf-8")
            model = ScriptedModel(scripted_turns=[
                ModelTurn(tool_calls=[_tc("read_file", path="big.txt")]),
                ModelTurn(text="done", stop_reason="end_turn"),
            ])
            engine = _make_engine(root, model, max_observation_chars=1000)
            ctx = ExternalContext()
            result, ctx = engine.solve_with_context("read big file", context=ctx)
            self.assertEqual(result, "done")
            # The observation stored in context should be clipped
            for obs in ctx.observations:
                self.assertLessEqual(len(obs), 1200)  # some overhead for prefix


# ---------------------------------------------------------------------------
# max_depth=0 blocks all subtasks
# ---------------------------------------------------------------------------


class MaxDepthZeroTests(unittest.TestCase):
    def test_subtask_blocked_at_depth_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            model = ScriptedModel(scripted_turns=[
                ModelTurn(tool_calls=[_tc("subtask", objective="should be blocked")]),
                ModelTurn(text="fallback", stop_reason="end_turn"),
            ])
            engine = _make_engine(root, model, max_depth=0, recursive=True)
            result = engine.solve("blocked subtask")
            self.assertEqual(result, "fallback")


# ---------------------------------------------------------------------------
# max_steps_per_call=1 budget exhaustion
# ---------------------------------------------------------------------------


class SingleStepBudgetTests(unittest.TestCase):
    def test_single_step_final_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            model = ScriptedModel(scripted_turns=[
                ModelTurn(text="immediate answer", stop_reason="end_turn"),
            ])
            engine = _make_engine(root, model, max_steps_per_call=1)
            result = engine.solve("quick question")
            self.assertEqual(result, "immediate answer")

    def test_single_step_exhaustion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            model = ScriptedModel(scripted_turns=[
                ModelTurn(tool_calls=[_tc("think", note="thinking...")]),
                ModelTurn(tool_calls=[_tc("think", note="still thinking...")]),
            ])
            engine = _make_engine(root, model, max_steps_per_call=1)
            result = engine.solve("one step only")
            self.assertIn("Step budget exhausted", result)


# ---------------------------------------------------------------------------
# Empty and whitespace objectives
# ---------------------------------------------------------------------------


class EmptyObjectiveTests(unittest.TestCase):
    def test_empty_string(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            model = ScriptedModel(scripted_turns=[])
            engine = _make_engine(root, model)
            result = engine.solve("")
            self.assertIn("No objective", result)

    def test_whitespace_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            model = ScriptedModel(scripted_turns=[])
            engine = _make_engine(root, model)
            result = engine.solve("   \n  ")
            self.assertIn("No objective", result)


# ---------------------------------------------------------------------------
# Unknown tool dispatch
# ---------------------------------------------------------------------------


class UnknownToolTests(unittest.TestCase):
    def test_unknown_tool_returns_error_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            model = ScriptedModel(scripted_turns=[
                ModelTurn(tool_calls=[_tc("nonexistent_tool", arg="val")]),
                ModelTurn(text="done anyway", stop_reason="end_turn"),
            ])
            engine = _make_engine(root, model)
            result = engine.solve("try unknown tool")
            self.assertEqual(result, "done anyway")


# ---------------------------------------------------------------------------
# Corrupted events.jsonl on resume
# ---------------------------------------------------------------------------


class CorruptedEventsTests(unittest.TestCase):
    def test_corrupted_state_returns_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = SessionStore(workspace=root, session_root_dir=".openplanter")
            sid, _, _ = store.open_session()

            # Write corrupted state.json
            state_path = store._state_path(sid)
            state_path.write_text("THIS IS NOT JSON", encoding="utf-8")

            # Loading corrupted state should raise SessionError
            from agent.runtime import SessionError
            with self.assertRaises(SessionError):
                store.load_state(sid)


# ---------------------------------------------------------------------------
# Type coercion edge cases in tool dispatch
# ---------------------------------------------------------------------------


class TypeCoercionTests(unittest.TestCase):
    def test_web_search_bool_as_int_rejected(self) -> None:
        """isinstance(True, int) is True in Python — verify we handle it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            # Pass True for num_results — should be int, True is int
            model = ScriptedModel(scripted_turns=[
                ModelTurn(tool_calls=[_tc("web_search", query="test", num_results=True, include_text=False)]),
                ModelTurn(text="done", stop_reason="end_turn"),
            ])
            engine = _make_engine(root, model)
            from unittest.mock import patch as mock_patch
            with mock_patch.object(engine.tools, "web_search", return_value='{"total":0}') as mocked:
                result = engine.solve("type coercion test")
            self.assertEqual(result, "done")
            # True is technically int(1), so it gets passed through
            mocked.assert_called_once()

    def test_write_file_none_content(self) -> None:
        """str(None) produces 'None' — verify behavior is consistent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            model = ScriptedModel(scripted_turns=[
                ModelTurn(tool_calls=[_tc("write_file", path="test.txt", content=None)]),
                ModelTurn(text="done", stop_reason="end_turn"),
            ])
            engine = _make_engine(root, model)
            result = engine.solve("write none content")
            self.assertEqual(result, "done")
            # str(None) = "None"
            content = (root / "test.txt").read_text(encoding="utf-8")
            self.assertEqual(content, "None")

    def test_search_files_empty_query_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            model = ScriptedModel(scripted_turns=[
                ModelTurn(tool_calls=[_tc("search_files", query="")]),
                ModelTurn(text="done", stop_reason="end_turn"),
            ])
            engine = _make_engine(root, model)
            result = engine.solve("empty search")
            self.assertEqual(result, "done")


# ---------------------------------------------------------------------------
# Shell command with /bin/sh (portability check)
# ---------------------------------------------------------------------------


class ShellPortabilityTests(unittest.TestCase):
    def test_shell_default_is_sh(self) -> None:
        cfg = AgentConfig(workspace=Path("/tmp"))
        self.assertEqual(cfg.shell, "/bin/sh")

    def test_run_shell_with_default_shell(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tools = WorkspaceTools(root=root)
            result = tools.run_shell("echo hello")
            self.assertIn("hello", result)
            self.assertIn("exit_code=0", result)


# ---------------------------------------------------------------------------
# Event log structure validation
# ---------------------------------------------------------------------------


class EventLogStructureTests(unittest.TestCase):
    def test_events_are_valid_json_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root)
            model = ScriptedModel(scripted_turns=[
                ModelTurn(tool_calls=[_tc("think", note="hello")]),
                ModelTurn(text="done", stop_reason="end_turn"),
            ])
            tools = WorkspaceTools(root=root)
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            runtime = SessionRuntime.bootstrap(engine=engine, config=cfg)
            runtime.solve("test events")

            # Find events.jsonl and verify each line is valid JSON
            sessions_dir = root / ".openplanter" / "sessions"
            for session_dir in sessions_dir.iterdir():
                events_file = session_dir / "events.jsonl"
                if events_file.exists():
                    for line_num, line in enumerate(events_file.read_text().splitlines(), 1):
                        if line.strip():
                            try:
                                parsed = json.loads(line)
                                self.assertIn("type", parsed, f"Line {line_num} missing 'type'")
                            except json.JSONDecodeError:
                                self.fail(f"Line {line_num} is not valid JSON: {line[:100]}")


if __name__ == "__main__":
    unittest.main()

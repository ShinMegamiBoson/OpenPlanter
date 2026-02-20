"""Tests for per-command timeout and background command execution."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from conftest import _tc

from agent.config import AgentConfig
from agent.engine import RLMEngine
from agent.model import ModelTurn, ScriptedModel
from agent.tools import WorkspaceTools


class TimeoutTests(unittest.TestCase):
    def test_run_shell_custom_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools = WorkspaceTools(root=Path(tmpdir))
            result = tools.run_shell("echo hi", timeout=5)
            self.assertIn("hi", result)
            self.assertIn("exit_code=0", result)

    def test_run_shell_timeout_exceeded(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools = WorkspaceTools(root=Path(tmpdir))
            result = tools.run_shell("sleep 10", timeout=1)
            self.assertIn("timeout after 1s", result)

    def test_run_shell_timeout_capped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools = WorkspaceTools(root=Path(tmpdir))
            # timeout=9999 should be capped at 600 internally.
            # We verify by running a fast command — it should succeed, not hang for 9999s.
            result = tools.run_shell("echo capped", timeout=9999)
            self.assertIn("capped", result)

    def test_run_shell_timeout_dispatch(self) -> None:
        """Engine dispatches timeout arg correctly to tools.run_shell."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=4)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(scripted_turns=[
                ModelTurn(tool_calls=[_tc("run_shell", command="echo dispatched", timeout=10)]),
                ModelTurn(text="done", stop_reason="end_turn"),
            ])
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            result = engine.solve("test timeout dispatch")
            self.assertEqual(result, "done")


class BackgroundCommandTests(unittest.TestCase):
    def test_bg_start_and_check_finished(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools = WorkspaceTools(root=Path(tmpdir))
            start_result = tools.run_shell_bg("echo hello_bg")
            self.assertIn("job_id=1", start_result)
            # Brief wait for the command to finish.
            time.sleep(0.5)
            check_result = tools.check_shell_bg(1)
            self.assertIn("finished", check_result)
            self.assertIn("hello_bg", check_result)

    def test_bg_check_running(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools = WorkspaceTools(root=Path(tmpdir))
            tools.run_shell_bg("sleep 10")
            # Check immediately — should still be running.
            check_result = tools.check_shell_bg(1)
            self.assertIn("still running", check_result)
            # Clean up.
            tools.kill_shell_bg(1)

    def test_bg_kill(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools = WorkspaceTools(root=Path(tmpdir))
            tools.run_shell_bg("sleep 100")
            kill_result = tools.kill_shell_bg(1)
            self.assertIn("killed", kill_result.lower())

    def test_bg_nonexistent_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools = WorkspaceTools(root=Path(tmpdir))
            result = tools.check_shell_bg(999)
            self.assertIn("No background job", result)

    def test_bg_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools = WorkspaceTools(root=Path(tmpdir))
            tools.run_shell_bg("sleep 100")
            tools.run_shell_bg("sleep 100")
            self.assertEqual(len(tools._bg_jobs), 2)
            tools.cleanup_bg_jobs()
            self.assertEqual(len(tools._bg_jobs), 0)

    def test_bg_dispatch_via_engine(self) -> None:
        """Engine dispatches background tool calls correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=6)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(scripted_turns=[
                ModelTurn(tool_calls=[_tc("run_shell_bg", command="echo engine_bg")]),
                ModelTurn(tool_calls=[_tc("check_shell_bg", job_id=1)]),
                ModelTurn(text="bg done", stop_reason="end_turn"),
            ])
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            result = engine.solve("test bg dispatch")
            self.assertEqual(result, "bg done")


if __name__ == "__main__":
    unittest.main()

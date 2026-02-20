"""Complex user-story integration tests.

Each test simulates a realistic multi-step agent workflow that a real user
would trigger.  All tests are headless (ScriptedModel), exercise full-stack
SessionRuntime → RLMEngine → WorkspaceTools, and verify end-to-end
correctness across sessions, callbacks, context, and artifacts.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from conftest import _tc

from agent.config import AgentConfig
from agent.engine import RLMEngine
from agent.model import (
    EchoFallbackModel,
    ModelTurn,
    ScriptedModel,
)
from agent.runtime import SessionRuntime
from agent.tools import WorkspaceTools


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


def _make_runtime(
    root: Path,
    cfg: AgentConfig,
    turns: list[ModelTurn],
    session_id: str,
    resume: bool = False,
) -> SessionRuntime:
    model = ScriptedModel(scripted_turns=turns)
    tools = WorkspaceTools(root=root)
    engine = RLMEngine(model=model, tools=tools, config=cfg)
    return SessionRuntime.bootstrap(
        engine=engine, config=cfg, session_id=session_id, resume=resume,
    )


def _read_events(root: Path, session_id: str) -> list[dict]:
    events_path = root / ".openplanter" / "sessions" / session_id / "events.jsonl"
    events = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events


def _read_state(root: Path, session_id: str) -> dict:
    state_path = root / ".openplanter" / "sessions" / session_id / "state.json"
    return json.loads(state_path.read_text(encoding="utf-8"))


# ===================================================================
# 1.  Iterative Code Development — write → test → fail → fix → pass
# ===================================================================


class TestIterativeCodeDevelopment(unittest.TestCase):
    """User writes code, writes tests, runs tests (fail), fixes code, reruns (pass)."""

    def test_iterative_red_green_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=10)

            buggy_code = "def double(x):\n    return x + 1  # bug: adds 1 instead of doubling\n"
            test_code = (
                "from mathlib import double\n"
                "assert double(3) == 6, f'Expected 6 got {double(3)}'\n"
                "print('ALL PASS')\n"
            )
            fix_patch = (
                "*** Begin Patch\n"
                "*** Update File: mathlib.py\n"
                "@@\n"
                " def double(x):\n"
                "-    return x + 1  # bug: adds 1 instead of doubling\n"
                "+    return x * 2\n"
                "*** End Patch"
            )

            turns = [
                # Solve 1: Write initial (buggy) code
                ModelTurn(tool_calls=[_tc("write_file", path="mathlib.py", content=buggy_code)]),
                ModelTurn(tool_calls=[_tc("write_file", path="test_mathlib.py", content=test_code)]),
                ModelTurn(text="initial code and tests written", stop_reason="end_turn"),
                # Solve 2: Run tests → failure
                ModelTurn(tool_calls=[_tc("run_shell", command="python test_mathlib.py")]),
                ModelTurn(text="tests failed, need fix", stop_reason="end_turn"),
                # Solve 3: Fix code, re-run tests → pass
                ModelTurn(tool_calls=[_tc("apply_patch", patch=fix_patch)]),
                ModelTurn(tool_calls=[_tc("run_shell", command="python test_mathlib.py")]),
                ModelTurn(text="all tests pass after fix", stop_reason="end_turn"),
            ]
            runtime = _make_runtime(root, cfg, turns, "red-green")

            r1 = runtime.solve("write initial code and tests")
            self.assertEqual(r1, "initial code and tests written")

            r2 = runtime.solve("run the tests")
            self.assertEqual(r2, "tests failed, need fix")
            # Verify test failure was captured
            fail_obs = [o for o in runtime.context.observations if "exit_code" in o and "exit_code=0" not in o]
            self.assertGreaterEqual(len(fail_obs), 1)

            r3 = runtime.solve("fix the bug and retest")
            self.assertEqual(r3, "all tests pass after fix")
            # Verify the fixed code is correct
            final_code = (root / "mathlib.py").read_text()
            self.assertIn("x * 2", final_code)
            self.assertNotIn("bug", final_code)
            # Verify test pass
            pass_obs = [o for o in runtime.context.observations if "exit_code=0" in o]
            self.assertGreaterEqual(len(pass_obs), 1)

            # Event log should span all three solves
            events = _read_events(root, "red-green")
            objectives = [e for e in events if e["type"] == "objective"]
            self.assertEqual(len(objectives), 3)
            results = [e for e in events if e["type"] == "result"]
            self.assertEqual(len(results), 3)


# ===================================================================
# 2.  Multi-File Refactoring — read → search → patch multiple files
# ===================================================================


class TestMultiFileRefactoring(unittest.TestCase):
    """User refactors a function name across multiple files using search + patch."""

    def test_rename_function_across_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=12)

            # Pre-create the "existing" codebase
            (root / "utils.py").write_text("def old_name(x):\n    return x + 1\n", encoding="utf-8")
            (root / "main.py").write_text("from utils import old_name\nresult = old_name(5)\n", encoding="utf-8")
            (root / "tests.py").write_text("from utils import old_name\nassert old_name(1) == 2\n", encoding="utf-8")

            patch_utils = (
                "*** Begin Patch\n"
                "*** Update File: utils.py\n"
                "@@\n"
                "-def old_name(x):\n"
                "+def new_name(x):\n"
                "*** End Patch"
            )
            patch_main = (
                "*** Begin Patch\n"
                "*** Update File: main.py\n"
                "@@\n"
                "-from utils import old_name\n"
                "-result = old_name(5)\n"
                "+from utils import new_name\n"
                "+result = new_name(5)\n"
                "*** End Patch"
            )
            patch_tests = (
                "*** Begin Patch\n"
                "*** Update File: tests.py\n"
                "@@\n"
                "-from utils import old_name\n"
                "-assert old_name(1) == 2\n"
                "+from utils import new_name\n"
                "+assert new_name(1) == 2\n"
                "*** End Patch"
            )

            turns = [
                ModelTurn(tool_calls=[_tc("search_files", query="old_name")]),
                ModelTurn(tool_calls=[_tc("read_file", path="utils.py")]),
                ModelTurn(tool_calls=[
                    _tc("apply_patch", patch=patch_utils),
                ]),
                ModelTurn(tool_calls=[_tc("apply_patch", patch=patch_main)]),
                ModelTurn(tool_calls=[_tc("apply_patch", patch=patch_tests)]),
                ModelTurn(tool_calls=[_tc("search_files", query="old_name")]),
                ModelTurn(tool_calls=[_tc("run_shell", command="python tests.py")]),
                ModelTurn(text="refactoring complete", stop_reason="end_turn"),
            ]
            runtime = _make_runtime(root, cfg, turns, "refactor")
            result = runtime.solve("rename old_name to new_name everywhere")

            self.assertEqual(result, "refactoring complete")
            # All files should have new_name, not old_name
            for fname in ["utils.py", "main.py", "tests.py"]:
                content = (root / fname).read_text()
                self.assertIn("new_name", content, f"{fname} missing new_name")
                self.assertNotIn("old_name", content, f"{fname} still has old_name")

            # Should have 3 patch artifacts
            events = _read_events(root, "refactor")
            artifact_events = [e for e in events if e["type"] == "artifact"]
            self.assertEqual(len(artifact_events), 3)


# ===================================================================
# 3.  Parallel Tool Calls — multiple reads in one turn
# ===================================================================


class TestParallelToolCalls(unittest.TestCase):
    """Model issues multiple tool calls in a single turn (parallel reads)."""

    def test_multiple_reads_single_turn(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=6)

            (root / "a.txt").write_text("content-a", encoding="utf-8")
            (root / "b.txt").write_text("content-b", encoding="utf-8")
            (root / "c.txt").write_text("content-c", encoding="utf-8")

            turns = [
                # Single turn with 3 parallel reads
                ModelTurn(tool_calls=[
                    _tc("read_file", path="a.txt"),
                    _tc("read_file", path="b.txt"),
                    _tc("read_file", path="c.txt"),
                ]),
                ModelTurn(text="read all three files", stop_reason="end_turn"),
            ]
            runtime = _make_runtime(root, cfg, turns, "parallel")
            result = runtime.solve("read all files at once")

            self.assertEqual(result, "read all three files")
            # All three observations should be captured (in one step)
            self.assertEqual(len(runtime.context.observations), 3)
            joined = "\n".join(runtime.context.observations)
            self.assertIn("content-a", joined)
            self.assertIn("content-b", joined)
            self.assertIn("content-c", joined)

    def test_mixed_parallel_tools(self) -> None:
        """Multiple different tool types in one turn."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=6)
            (root / "data.txt").write_text("hello world", encoding="utf-8")

            turns = [
                ModelTurn(tool_calls=[
                    _tc("think", note="planning phase"),
                    _tc("list_files"),
                    _tc("read_file", path="data.txt"),
                ]),
                ModelTurn(text="done", stop_reason="end_turn"),
            ]
            runtime = _make_runtime(root, cfg, turns, "mixed-parallel")
            result = runtime.solve("mixed parallel")

            self.assertEqual(result, "done")
            self.assertEqual(len(runtime.context.observations), 3)
            obs = runtime.context.observations
            self.assertIn("Thought noted", obs[0])
            self.assertIn("data.txt", obs[1])
            self.assertIn("hello world", obs[2])


# ===================================================================
# 4.  Subtask Error Propagation
# ===================================================================


class TestSubtaskErrorPropagation(unittest.TestCase):
    """Subtask encounters errors; parent receives error observations and continues."""

    def test_subtask_reads_missing_file_parent_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_depth=2, max_steps_per_call=6, recursive=True)

            turns = [
                # Depth 0: delegate to subtask
                ModelTurn(tool_calls=[_tc("subtask", objective="try reading missing file")]),
                # Depth 1: subtask reads missing file, then gives up
                ModelTurn(tool_calls=[_tc("read_file", path="nonexistent.txt")]),
                ModelTurn(text="subtask: file not found", stop_reason="end_turn"),
                # Depth 0: parent sees error, creates the file
                ModelTurn(tool_calls=[_tc("write_file", path="nonexistent.txt", content="now exists")]),
                ModelTurn(text="parent recovered from subtask error", stop_reason="end_turn"),
            ]
            runtime = _make_runtime(root, cfg, turns, "sub-error")
            result = runtime.solve("handle subtask error")

            self.assertEqual(result, "parent recovered from subtask error")
            self.assertTrue((root / "nonexistent.txt").exists())
            # Subtask error should appear in context
            error_obs = [o for o in runtime.context.observations if "not found" in o.lower()]
            self.assertGreaterEqual(len(error_obs), 1)

    def test_subtask_shell_fails_parent_continues(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_depth=2, max_steps_per_call=6, recursive=True)

            turns = [
                ModelTurn(tool_calls=[_tc("subtask", objective="run failing test")]),
                # Subtask: shell fails
                ModelTurn(tool_calls=[_tc("run_shell", command="python -c 'raise Exception(\"boom\")'")]),
                ModelTurn(text="subtask: test failed", stop_reason="end_turn"),
                # Parent: handles failure
                ModelTurn(tool_calls=[_tc("think", note="subtask failed, skipping")]),
                ModelTurn(text="gracefully handled", stop_reason="end_turn"),
            ]
            runtime = _make_runtime(root, cfg, turns, "sub-shell-fail")
            result = runtime.solve("subtask with shell failure")
            self.assertEqual(result, "gracefully handled")


# ===================================================================
# 5.  Deep Context Accuracy — verify observations flow correctly
# ===================================================================


class TestContextAccuracyAcrossSolves(unittest.TestCase):
    """Verify the exact content of context summaries fed to subsequent solves."""

    def test_second_solve_sees_first_solve_observations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=6)

            captured_messages: list[str] = []

            class CapturingModel(ScriptedModel):
                def create_conversation(self, system_prompt: str, initial_user_message: str):
                    captured_messages.append(initial_user_message)
                    return super().create_conversation(system_prompt, initial_user_message)

            turns = [
                # Solve 1: write a distinctive file
                ModelTurn(tool_calls=[_tc("write_file", path="marker.txt", content="UNIQUE_MARKER_12345")]),
                ModelTurn(text="marker placed", stop_reason="end_turn"),
                # Solve 2: just answer
                ModelTurn(text="second task done", stop_reason="end_turn"),
            ]
            model = CapturingModel(scripted_turns=turns)
            tools = WorkspaceTools(root=root)
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            runtime = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="ctx-accuracy", resume=False,
            )

            runtime.solve("place marker")
            runtime.solve("check context")

            # Parse second solve's initial message
            self.assertEqual(len(captured_messages), 2)
            second_init = json.loads(captured_messages[1])
            ctx_summary = second_init["external_context_summary"]

            # Context should contain the write observation (mentions file and bytes)
            self.assertIn("marker.txt", ctx_summary)
            self.assertNotEqual(ctx_summary, "(empty)")

    def test_context_preserves_shell_output(self) -> None:
        """Shell output from solve 1 appears in solve 2's context."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=6)

            captured_messages: list[str] = []

            class CapturingModel(ScriptedModel):
                def create_conversation(self, system_prompt: str, initial_user_message: str):
                    captured_messages.append(initial_user_message)
                    return super().create_conversation(system_prompt, initial_user_message)

            turns = [
                ModelTurn(tool_calls=[_tc("run_shell", command="echo SENTINEL_OUTPUT_VALUE")]),
                ModelTurn(text="done 1", stop_reason="end_turn"),
                ModelTurn(text="done 2", stop_reason="end_turn"),
            ]
            model = CapturingModel(scripted_turns=turns)
            tools = WorkspaceTools(root=root)
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            runtime = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="ctx-shell", resume=False,
            )

            runtime.solve("run echo")
            runtime.solve("next task")

            second_init = json.loads(captured_messages[1])
            self.assertIn("SENTINEL_OUTPUT_VALUE", second_init["external_context_summary"])


# ===================================================================
# 6.  Session Resume with Continued Work
# ===================================================================


class TestSessionResumeWithContinuedWork(unittest.TestCase):
    """Resume a session and verify context + filesystem are coherent."""

    def test_resume_preserves_context_and_allows_continued_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=6)

            # Session 1: create files and build context
            turns1 = [
                ModelTurn(tool_calls=[
                    _tc("write_file", path="module.py", content="def greet():\n    return 'hello'\n"),
                ]),
                ModelTurn(tool_calls=[
                    _tc("write_file", path="test_module.py", content="from module import greet\nassert greet() == 'hello'\nprint('OK')\n"),
                ]),
                ModelTurn(tool_calls=[_tc("run_shell", command="python test_module.py")]),
                ModelTurn(text="module created and tested", stop_reason="end_turn"),
            ]
            runtime1 = _make_runtime(root, cfg, turns1, "resume-work")
            r1 = runtime1.solve("create a module with tests")
            self.assertEqual(r1, "module created and tested")
            obs_count_1 = len(runtime1.context.observations)
            self.assertGreater(obs_count_1, 0)

            # Session 2: resume, patch the module, re-run tests
            patch_text = (
                "*** Begin Patch\n"
                "*** Update File: module.py\n"
                "@@\n"
                " def greet():\n"
                "-    return 'hello'\n"
                "+    return 'hello world'\n"
                "*** End Patch"
            )
            test_update = (
                "*** Begin Patch\n"
                "*** Update File: test_module.py\n"
                "@@\n"
                "-assert greet() == 'hello'\n"
                "+assert greet() == 'hello world'\n"
                "*** End Patch"
            )
            turns2 = [
                ModelTurn(tool_calls=[_tc("apply_patch", patch=patch_text)]),
                ModelTurn(tool_calls=[_tc("apply_patch", patch=test_update)]),
                ModelTurn(tool_calls=[_tc("run_shell", command="python test_module.py")]),
                ModelTurn(text="updated and retested", stop_reason="end_turn"),
            ]
            runtime2 = _make_runtime(root, cfg, turns2, "resume-work", resume=True)
            # Resumed context should have obs from session 1
            self.assertEqual(len(runtime2.context.observations), obs_count_1)

            r2 = runtime2.solve("update module and retest")
            self.assertEqual(r2, "updated and retested")
            # Context should have grown
            self.assertGreater(len(runtime2.context.observations), obs_count_1)
            # File should reflect the patch
            self.assertIn("hello world", (root / "module.py").read_text())

            # Events span both sessions
            events = _read_events(root, "resume-work")
            session_started = [e for e in events if e["type"] == "session_started"]
            self.assertEqual(len(session_started), 2)  # original + resume


# ===================================================================
# 7.  Callback Completeness and Ordering
# ===================================================================


class TestCallbackCompleteness(unittest.TestCase):
    """Verify on_event and on_step callbacks fire correctly for all operations."""

    def test_on_step_captures_all_tool_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=8)
            (root / "hello.txt").write_text("hello", encoding="utf-8")

            turns = [
                ModelTurn(tool_calls=[_tc("think", note="planning")]),
                ModelTurn(tool_calls=[_tc("list_files")]),
                ModelTurn(tool_calls=[_tc("read_file", path="hello.txt")]),
                ModelTurn(tool_calls=[_tc("write_file", path="output.txt", content="result")]),
                ModelTurn(text="workflow done", stop_reason="end_turn"),
            ]
            model = ScriptedModel(scripted_turns=turns)
            tools = WorkspaceTools(root=root)
            engine = RLMEngine(model=model, tools=tools, config=cfg)

            steps: list[dict] = []
            events: list[str] = []
            result, _ = engine.solve_with_context(
                objective="callback test",
                on_step=steps.append,
                on_event=events.append,
            )

            self.assertEqual(result, "workflow done")
            # Filter out internal _model_turn diagnostics
            tool_steps = [s for s in steps if s["action"]["name"] != "_model_turn"]
            # 4 tool calls + 1 final = 5 steps
            self.assertEqual(len(tool_steps), 5)
            tool_names = [s["action"]["name"] for s in tool_steps]
            self.assertEqual(tool_names, ["think", "list_files", "read_file", "write_file", "final"])
            # Final step should be marked is_final
            self.assertTrue(tool_steps[-1]["is_final"])
            # Non-final steps should not be marked is_final
            for s in tool_steps[:-1]:
                self.assertFalse(s["is_final"])
            # Events should include depth/step markers
            self.assertTrue(any("[d0/s" in e for e in events))

    def test_on_step_with_parallel_tools(self) -> None:
        """When a turn has multiple tool calls, each gets its own on_step."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=6)

            turns = [
                ModelTurn(tool_calls=[
                    _tc("think", note="a"),
                    _tc("think", note="b"),
                    _tc("think", note="c"),
                ]),
                ModelTurn(text="done", stop_reason="end_turn"),
            ]
            model = ScriptedModel(scripted_turns=turns)
            tools = WorkspaceTools(root=root)
            engine = RLMEngine(model=model, tools=tools, config=cfg)

            steps: list[dict] = []
            engine.solve_with_context(objective="parallel steps", on_step=steps.append)

            # Filter out internal _model_turn diagnostics
            tool_steps = [s for s in steps if s["action"]["name"] != "_model_turn"]
            # 3 tool calls + 1 final = 4 step callbacks
            self.assertEqual(len(tool_steps), 4)
            think_steps = [s for s in tool_steps if s["action"]["name"] == "think"]
            self.assertEqual(len(think_steps), 3)

    def test_on_event_fires_for_subtask_entry_and_exit(self) -> None:
        """Events should include subtask entry/exit markers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_depth=2, max_steps_per_call=6, recursive=True)

            turns = [
                ModelTurn(tool_calls=[_tc("subtask", objective="inner work")]),
                ModelTurn(tool_calls=[_tc("think", note="inside subtask")]),
                ModelTurn(text="subtask done", stop_reason="end_turn"),
                ModelTurn(text="parent done", stop_reason="end_turn"),
            ]
            model = ScriptedModel(scripted_turns=turns)
            tools = WorkspaceTools(root=root)
            engine = RLMEngine(model=model, tools=tools, config=cfg)

            events: list[str] = []
            engine.solve_with_context(objective="subtask events", on_event=events.append)

            # Should have events at both depths
            depth0_events = [e for e in events if "[d0" in e]
            depth1_events = [e for e in events if "[d1" in e]
            self.assertGreater(len(depth0_events), 0)
            self.assertGreater(len(depth1_events), 0)
            # Should mention entering subtask
            subtask_entry = [e for e in events if "entering subtask" in e]
            self.assertGreaterEqual(len(subtask_entry), 1)


# ===================================================================
# 8.  Event Log Reconstruction — full audit trail
# ===================================================================


class TestEventLogReconstruction(unittest.TestCase):
    """Parse events.jsonl and reconstruct the full workflow timeline."""

    def test_event_log_reconstructs_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=8)

            patch_text = (
                "*** Begin Patch\n"
                "*** Add File: audit.txt\n"
                "+audited\n"
                "*** End Patch"
            )
            turns = [
                ModelTurn(tool_calls=[_tc("think", note="analyzing task")]),
                ModelTurn(tool_calls=[_tc("write_file", path="data.txt", content="raw data")]),
                ModelTurn(tool_calls=[_tc("apply_patch", patch=patch_text)]),
                ModelTurn(tool_calls=[_tc("read_file", path="audit.txt")]),
                ModelTurn(text="audit complete", stop_reason="end_turn"),
            ]
            runtime = _make_runtime(root, cfg, turns, "audit-trail")
            runtime.solve("full audit workflow")

            events = _read_events(root, "audit-trail")

            # Every event should have a timestamp
            for event in events:
                self.assertIn("ts", event)
                self.assertIn("type", event)
                self.assertIn("payload", event)

            # Reconstruct: session_started → objective → traces/steps → artifact → result
            types = [e["type"] for e in events]
            self.assertEqual(types[0], "session_started")
            self.assertEqual(types[1], "objective")
            self.assertEqual(types[-1], "result")

            # Steps should have depth, step, action, observation
            step_events = [e for e in events if e["type"] == "step"]
            self.assertGreaterEqual(len(step_events), 4)  # think + write + patch + read
            for step in step_events:
                payload = step["payload"]
                self.assertIn("depth", payload)
                self.assertIn("step", payload)
                self.assertIn("action", payload)
                self.assertIn("observation", payload)

            # Artifact event should reference the patch file
            artifact_events = [e for e in events if e["type"] == "artifact"]
            self.assertEqual(len(artifact_events), 1)
            self.assertIn("patches", artifact_events[0]["payload"]["path"])

            # Verify result event contains the final answer
            result_event = [e for e in events if e["type"] == "result"][-1]
            self.assertEqual(result_event["payload"]["text"], "audit complete")

    def test_multi_solve_event_log_preserves_ordering(self) -> None:
        """Multiple solves produce events in chronological order."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=4)

            turns = [
                ModelTurn(text="r1", stop_reason="end_turn"),
                ModelTurn(text="r2", stop_reason="end_turn"),
                ModelTurn(text="r3", stop_reason="end_turn"),
            ]
            runtime = _make_runtime(root, cfg, turns, "multi-evt")
            runtime.solve("task 1")
            runtime.solve("task 2")
            runtime.solve("task 3")

            events = _read_events(root, "multi-evt")
            objectives = [e for e in events if e["type"] == "objective"]
            results = [e for e in events if e["type"] == "result"]

            self.assertEqual(len(objectives), 3)
            self.assertEqual(len(results), 3)
            self.assertEqual(objectives[0]["payload"]["text"], "task 1")
            self.assertEqual(objectives[1]["payload"]["text"], "task 2")
            self.assertEqual(objectives[2]["payload"]["text"], "task 3")
            self.assertEqual(results[0]["payload"]["text"], "r1")
            self.assertEqual(results[1]["payload"]["text"], "r2")
            self.assertEqual(results[2]["payload"]["text"], "r3")


# ===================================================================
# 9.  Large Observation Stress — many observations with capping
# ===================================================================


class TestLargeObservationStress(unittest.TestCase):
    """Stress test: many tool calls generating observations, verify capping."""

    def test_500_observations_capped_correctly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cap = 20
            step_count = 30
            cfg = _make_config(root, max_persisted_observations=cap, max_steps_per_call=step_count + 2)

            think_turns = [
                ModelTurn(tool_calls=[_tc("think", note=f"thought-{i}")])
                for i in range(step_count)
            ]
            think_turns.append(ModelTurn(text="many thoughts done", stop_reason="end_turn"))

            runtime = _make_runtime(root, cfg, think_turns, "stress-obs")
            result = runtime.solve("generate many observations")
            self.assertEqual(result, "many thoughts done")

            # State should be capped
            state = _read_state(root, "stress-obs")
            self.assertLessEqual(len(state["external_observations"]), cap)
            # Last observation should be the most recent
            last_obs = state["external_observations"][-1]
            self.assertIn(f"thought-{step_count - 1}", last_obs)

    def test_observations_cap_across_many_solves(self) -> None:
        """10 solves with 5 tool calls each, cap=15 — old obs trimmed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cap = 15
            cfg = _make_config(root, max_persisted_observations=cap, max_steps_per_call=8)

            turns: list[ModelTurn] = []
            for solve_idx in range(10):
                for step_idx in range(5):
                    turns.append(ModelTurn(tool_calls=[
                        _tc("think", note=f"solve{solve_idx}-step{step_idx}")
                    ]))
                turns.append(ModelTurn(text=f"solve-{solve_idx}-done", stop_reason="end_turn"))

            runtime = _make_runtime(root, cfg, turns, "multi-stress")
            for i in range(10):
                runtime.solve(f"solve {i}")

            state = _read_state(root, "multi-stress")
            self.assertLessEqual(len(state["external_observations"]), cap)
            # Most recent observations should be from the last few solves
            last_obs = state["external_observations"][-1]
            self.assertIn("solve9-step4", last_obs)


# ===================================================================
# 10. Nested Subtask with Artifact and Context Propagation
# ===================================================================


class TestNestedSubtaskWithArtifact(unittest.TestCase):
    """Three-level deep subtask that creates a file and applies a patch."""

    def test_deep_subtask_creates_file_and_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_depth=3, max_steps_per_call=8, recursive=True)

            patch_text = (
                "*** Begin Patch\n"
                "*** Add File: deep.txt\n"
                "+created at depth 2\n"
                "*** End Patch"
            )

            turns = [
                # Depth 0: delegate
                ModelTurn(tool_calls=[_tc("subtask", objective="go deeper")]),
                # Depth 1: delegate again
                ModelTurn(tool_calls=[_tc("subtask", objective="go deepest")]),
                # Depth 2: create file + patch + answer
                ModelTurn(tool_calls=[_tc("write_file", path="shallow.txt", content="depth2 file")]),
                ModelTurn(tool_calls=[_tc("apply_patch", patch=patch_text)]),
                ModelTurn(text="depth 2 done", stop_reason="end_turn"),
                # Depth 1: verify depth 2 file
                ModelTurn(tool_calls=[_tc("read_file", path="deep.txt")]),
                ModelTurn(text="depth 1 done", stop_reason="end_turn"),
                # Depth 0: final check
                ModelTurn(tool_calls=[_tc("read_file", path="shallow.txt")]),
                ModelTurn(text="all depths completed", stop_reason="end_turn"),
            ]
            runtime = _make_runtime(root, cfg, turns, "deep-nest")
            result = runtime.solve("three level deep task")

            self.assertEqual(result, "all depths completed")
            self.assertTrue((root / "shallow.txt").exists())
            self.assertTrue((root / "deep.txt").exists())
            self.assertEqual((root / "deep.txt").read_text().strip(), "created at depth 2")

            # Artifact event for the patch
            events = _read_events(root, "deep-nest")
            artifact_events = [e for e in events if e["type"] == "artifact"]
            self.assertGreaterEqual(len(artifact_events), 1)

            # Steps from all depths should appear in events
            step_events = [e for e in events if e["type"] == "step"]
            depths_seen = {s["payload"]["depth"] for s in step_events}
            self.assertEqual(depths_seen, {0, 1, 2})


# ===================================================================
# 11. EchoFallbackModel in Session — graceful degradation
# ===================================================================


class TestEchoFallbackSession(unittest.TestCase):
    """No API keys → EchoFallbackModel; session still works but returns fallback text."""

    def test_fallback_model_produces_valid_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root)

            model = EchoFallbackModel()
            tools = WorkspaceTools(root=root)
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            runtime = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="fallback", resume=False,
            )

            result = runtime.solve("do something")
            self.assertIn("No provider API keys configured", result)

            # Session should still have valid structure
            events = _read_events(root, "fallback")
            types = [e["type"] for e in events]
            self.assertIn("session_started", types)
            self.assertIn("objective", types)
            self.assertIn("result", types)

            state = _read_state(root, "fallback")
            self.assertEqual(state["session_id"], "fallback")


# ===================================================================
# 12. Multi-File Project Scaffold — create whole project structure
# ===================================================================


class TestProjectScaffold(unittest.TestCase):
    """Simulate creating a full project: setup.py, src/, tests/, config."""

    def test_scaffold_complete_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=12)

            setup_py = "from setuptools import setup\nsetup(name='myproject', version='1.0')\n"
            init_py = "from .core import main\n"
            core_py = "def main():\n    print('Hello from myproject')\n"
            test_core = (
                "import sys; sys.path.insert(0, 'src')\n"
                "from myproject.core import main\n"
                "main()\n"
                "print('TEST OK')\n"
            )
            config_json = '{"debug": false, "version": "1.0"}\n'

            turns = [
                ModelTurn(tool_calls=[_tc("write_file", path="setup.py", content=setup_py)]),
                ModelTurn(tool_calls=[
                    _tc("write_file", path="src/myproject/__init__.py", content=init_py),
                ]),
                ModelTurn(tool_calls=[
                    _tc("write_file", path="src/myproject/core.py", content=core_py),
                ]),
                ModelTurn(tool_calls=[
                    _tc("write_file", path="tests/test_core.py", content=test_core),
                ]),
                ModelTurn(tool_calls=[
                    _tc("write_file", path="config.json", content=config_json),
                ]),
                # Verify structure
                ModelTurn(tool_calls=[_tc("list_files", glob="*.py")]),
                ModelTurn(tool_calls=[_tc("run_shell", command="python tests/test_core.py")]),
                ModelTurn(text="project scaffolded and tested", stop_reason="end_turn"),
            ]
            runtime = _make_runtime(root, cfg, turns, "scaffold")
            result = runtime.solve("scaffold a complete project")

            self.assertEqual(result, "project scaffolded and tested")
            # All files exist
            self.assertTrue((root / "setup.py").exists())
            self.assertTrue((root / "src" / "myproject" / "__init__.py").exists())
            self.assertTrue((root / "src" / "myproject" / "core.py").exists())
            self.assertTrue((root / "tests" / "test_core.py").exists())
            self.assertTrue((root / "config.json").exists())
            # Config is valid JSON
            parsed = json.loads((root / "config.json").read_text())
            self.assertFalse(parsed["debug"])


# ===================================================================
# 13. Model Switching via TUI Handlers
# ===================================================================


class TestTUIModelAndReasoningSwitching(unittest.TestCase):
    """Test handle_model_command and handle_reasoning_command with ChatContext."""

    def test_model_switch_rebuilds_engine(self) -> None:
        """Switching model via handle_model_command replaces the runtime's engine."""
        from agent.builder import build_engine
        from agent.tui import ChatContext, handle_model_command

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root)
            cfg.provider = "openai"
            cfg.openai_api_key = "test-key"
            cfg.model = "gpt-4.1"

            engine = build_engine(cfg)
            runtime = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="model-switch", resume=False,
            )
            settings_store = __import__("agent.settings", fromlist=["SettingsStore"]).SettingsStore(
                workspace=root, session_root_dir=".openplanter",
            )
            ctx = ChatContext(runtime=runtime, cfg=cfg, settings_store=settings_store)

            old_engine = ctx.runtime.engine
            lines = handle_model_command("gpt-5.2", ctx)

            # Engine should have been rebuilt
            self.assertIsNot(ctx.runtime.engine, old_engine)
            self.assertEqual(cfg.model, "gpt-5.2")
            self.assertTrue(any("gpt-5.2" in line for line in lines))

    def test_model_alias_resolution(self) -> None:
        """Aliases like 'opus' resolve to full model names."""
        from agent.builder import build_engine
        from agent.tui import ChatContext, handle_model_command

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root)
            cfg.provider = "anthropic"
            cfg.anthropic_api_key = "test-key"
            cfg.model = "claude-sonnet-4-5-20250929"

            engine = build_engine(cfg)
            runtime = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="alias-test", resume=False,
            )
            settings_store = __import__("agent.settings", fromlist=["SettingsStore"]).SettingsStore(
                workspace=root, session_root_dir=".openplanter",
            )
            ctx = ChatContext(runtime=runtime, cfg=cfg, settings_store=settings_store)

            lines = handle_model_command("opus", ctx)
            self.assertEqual(cfg.model, "claude-opus-4-6")
            self.assertTrue(any("alias" in line.lower() for line in lines))

    def test_reasoning_change_rebuilds_engine(self) -> None:
        from agent.builder import build_engine
        from agent.tui import ChatContext, handle_reasoning_command

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root)
            cfg.provider = "openai"
            cfg.openai_api_key = "test-key"
            cfg.model = "gpt-5.2"
            cfg.reasoning_effort = "high"

            engine = build_engine(cfg)
            runtime = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="reason-test", resume=False,
            )
            settings_store = __import__("agent.settings", fromlist=["SettingsStore"]).SettingsStore(
                workspace=root, session_root_dir=".openplanter",
            )
            ctx = ChatContext(runtime=runtime, cfg=cfg, settings_store=settings_store)

            old_engine = ctx.runtime.engine
            lines = handle_reasoning_command("low", ctx)

            self.assertIsNot(ctx.runtime.engine, old_engine)
            self.assertEqual(cfg.reasoning_effort, "low")
            self.assertTrue(any("low" in line for line in lines))

    def test_reasoning_off_disables(self) -> None:
        from agent.builder import build_engine
        from agent.tui import ChatContext, handle_reasoning_command

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root)
            cfg.provider = "openai"
            cfg.openai_api_key = "test-key"
            cfg.model = "gpt-5.2"
            cfg.reasoning_effort = "high"

            engine = build_engine(cfg)
            runtime = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="reason-off", resume=False,
            )
            settings_store = __import__("agent.settings", fromlist=["SettingsStore"]).SettingsStore(
                workspace=root, session_root_dir=".openplanter",
            )
            ctx = ChatContext(runtime=runtime, cfg=cfg, settings_store=settings_store)

            handle_reasoning_command("off", ctx)
            self.assertIsNone(cfg.reasoning_effort)


# ===================================================================
# 14. Error Recovery Chain — multiple errors then success
# ===================================================================


class TestErrorRecoveryChain(unittest.TestCase):
    """Simulate agent encountering multiple errors before finding a path forward."""

    def test_multiple_errors_then_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=10)

            good_patch = (
                "*** Begin Patch\n"
                "*** Add File: result.txt\n"
                "+success after errors\n"
                "*** End Patch"
            )

            turns = [
                # Error 1: read missing file
                ModelTurn(tool_calls=[_tc("read_file", path="ghost.txt")]),
                # Error 2: bad patch
                ModelTurn(tool_calls=[_tc("apply_patch", patch="not a valid patch format")]),
                # Error 3: shell command fails
                ModelTurn(tool_calls=[_tc("run_shell", command="false")]),
                # Agent thinks about what went wrong
                ModelTurn(tool_calls=[_tc("think", note="three errors so far, trying different approach")]),
                # Success: create the file properly
                ModelTurn(tool_calls=[_tc("apply_patch", patch=good_patch)]),
                ModelTurn(tool_calls=[_tc("read_file", path="result.txt")]),
                ModelTurn(text="recovered after 3 errors", stop_reason="end_turn"),
            ]
            runtime = _make_runtime(root, cfg, turns, "error-chain")
            result = runtime.solve("try multiple approaches")

            self.assertEqual(result, "recovered after 3 errors")
            self.assertTrue((root / "result.txt").exists())
            self.assertIn("success after errors", (root / "result.txt").read_text())

            # All errors should be captured in context
            obs = runtime.context.observations
            error_count = sum(
                1 for o in obs
                if "not found" in o.lower() or "failed" in o.lower() or "exit_code=1" in o
            )
            self.assertGreaterEqual(error_count, 2)

    def test_all_steps_fail_then_budget_exhausted(self) -> None:
        """Every step errors; budget exhausted message still includes objective."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=3)

            turns = [
                ModelTurn(tool_calls=[_tc("read_file", path="x.txt")]),
                ModelTurn(tool_calls=[_tc("read_file", path="y.txt")]),
                ModelTurn(tool_calls=[_tc("read_file", path="z.txt")]),
                # Extra turn in case budget allows
                ModelTurn(tool_calls=[_tc("read_file", path="w.txt")]),
            ]
            runtime = _make_runtime(root, cfg, turns, "all-fail")
            result = runtime.solve("attempt impossible reads")

            self.assertIn("Step budget exhausted", result)
            self.assertIn("attempt impossible reads", result)


# ===================================================================
# 15. Write → Search → Verify Absence — negative search
# ===================================================================


class TestNegativeSearchVerification(unittest.TestCase):
    """Write a file, remove content via patch, verify search no longer matches."""

    def test_search_confirms_content_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=8)

            remove_patch = (
                "*** Begin Patch\n"
                "*** Update File: secrets.txt\n"
                "@@\n"
                " public info\n"
                "-SECRET_KEY=abc123\n"
                "+# secret removed\n"
                "*** End Patch"
            )

            turns = [
                ModelTurn(tool_calls=[_tc("write_file", path="secrets.txt",
                                          content="public info\nSECRET_KEY=abc123\n")]),
                ModelTurn(tool_calls=[_tc("search_files", query="SECRET_KEY", glob="*.txt")]),
                ModelTurn(tool_calls=[_tc("apply_patch", patch=remove_patch)]),
                ModelTurn(tool_calls=[_tc("search_files", query="SECRET_KEY", glob="*.txt")]),
                ModelTurn(text="secret removed and verified", stop_reason="end_turn"),
            ]
            runtime = _make_runtime(root, cfg, turns, "neg-search")
            result = runtime.solve("remove secret and verify")

            self.assertEqual(result, "secret removed and verified")
            content = (root / "secrets.txt").read_text()
            self.assertNotIn("SECRET_KEY", content)
            self.assertIn("# secret removed", content)

            # First search should find it in secrets.txt
            obs = runtime.context.observations
            self.assertIn("SECRET_KEY", obs[1])
            self.assertIn("secrets.txt", obs[1])
            # Second search should indicate no matches (glob limits to *.txt)
            self.assertIn("no matches", obs[3].lower())


if __name__ == "__main__":
    unittest.main()

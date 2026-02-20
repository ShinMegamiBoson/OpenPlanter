"""Headless integration tests.

Full stack: SessionRuntime → RLMEngine → WorkspaceTools with ScriptedModel.
No live API keys required. Each test exercises a realistic multi-step
agent workflow with real filesystem operations.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from conftest import _tc

from agent.config import AgentConfig
from agent.engine import RLMEngine
from agent.model import ModelTurn, ScriptedModel
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
# 1. Realistic Multi-Step Workflows
# ===================================================================


class TestWritePatchReadWorkflow(unittest.TestCase):
    """write_file → apply_patch (update) → read_file → final"""

    def test_write_patch_read_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=8)

            patch_text = (
                "*** Begin Patch\n"
                "*** Update File: greet.txt\n"
                "@@\n"
                " hello\n"
                "-world\n"
                "+universe\n"
                "*** End Patch"
            )
            turns = [
                ModelTurn(tool_calls=[_tc("write_file", path="greet.txt", content="hello\nworld\n")]),
                ModelTurn(tool_calls=[_tc("apply_patch", patch=patch_text)]),
                ModelTurn(tool_calls=[_tc("read_file", path="greet.txt")]),
                ModelTurn(text="done", stop_reason="end_turn"),
            ]
            runtime = _make_runtime(root, cfg, turns, "wpr-test")
            result = runtime.solve("write, patch, read")

            self.assertEqual(result, "done")
            content = (root / "greet.txt").read_text()
            self.assertIn("universe", content)
            self.assertNotIn("world", content)
            # 3 tool-call steps produce observations
            self.assertGreaterEqual(len(runtime.context.observations), 3)


class TestCreateProjectAndRunTests(unittest.TestCase):
    """write_file(code) → write_file(test) → run_shell(python test) → final"""

    def test_create_project_and_run_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=8)

            code = "def add(a, b):\n    return a + b\n"
            test_code = (
                "from add_mod import add\n"
                "assert add(2, 3) == 5\n"
                "print('PASS')\n"
            )
            turns = [
                ModelTurn(tool_calls=[_tc("write_file", path="add_mod.py", content=code)]),
                ModelTurn(tool_calls=[_tc("write_file", path="test_add.py", content=test_code)]),
                ModelTurn(tool_calls=[_tc("run_shell", command="python test_add.py")]),
                ModelTurn(text="all tests pass", stop_reason="end_turn"),
            ]
            runtime = _make_runtime(root, cfg, turns, "proj-test")
            result = runtime.solve("create project and test")

            self.assertEqual(result, "all tests pass")
            self.assertTrue((root / "add_mod.py").exists())
            self.assertTrue((root / "test_add.py").exists())
            # Verify shell ran successfully by checking context
            shell_obs = [o for o in runtime.context.observations if "exit_code=0" in o]
            self.assertGreaterEqual(len(shell_obs), 1)


class TestSearchDrivenEdit(unittest.TestCase):
    """write_file → search_files → apply_patch → search_files (verify) → final"""

    def test_search_driven_edit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=10)

            patch_text = (
                "*** Begin Patch\n"
                "*** Update File: data.txt\n"
                "@@\n"
                " alpha\n"
                "-beta\n"
                "+gamma\n"
                "*** End Patch"
            )
            turns = [
                ModelTurn(tool_calls=[_tc("write_file", path="data.txt", content="alpha\nbeta\n")]),
                ModelTurn(tool_calls=[_tc("search_files", query="beta")]),
                ModelTurn(tool_calls=[_tc("apply_patch", patch=patch_text)]),
                ModelTurn(tool_calls=[_tc("search_files", query="gamma")]),
                ModelTurn(text="edit verified", stop_reason="end_turn"),
            ]
            runtime = _make_runtime(root, cfg, turns, "sde-test")
            result = runtime.solve("search driven edit")

            self.assertEqual(result, "edit verified")
            content = (root / "data.txt").read_text()
            self.assertIn("gamma", content)
            self.assertNotIn("beta", content)


class TestListFilesThenRead(unittest.TestCase):
    """write_file x 3 → list_files(glob) → read_file → final"""

    def test_list_files_then_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=10)

            turns = [
                ModelTurn(tool_calls=[_tc("write_file", path="src/a.py", content="# a")]),
                ModelTurn(tool_calls=[_tc("write_file", path="src/b.py", content="# b")]),
                ModelTurn(tool_calls=[_tc("write_file", path="docs/readme.md", content="# readme")]),
                ModelTurn(tool_calls=[_tc("list_files", glob="*.py")]),
                ModelTurn(tool_calls=[_tc("read_file", path="src/a.py")]),
                ModelTurn(text="listed and read", stop_reason="end_turn"),
            ]
            runtime = _make_runtime(root, cfg, turns, "lf-test")
            result = runtime.solve("list and read files")

            self.assertEqual(result, "listed and read")
            self.assertTrue((root / "src" / "a.py").exists())
            self.assertTrue((root / "src" / "b.py").exists())
            self.assertTrue((root / "docs" / "readme.md").exists())
            # Check list_files observation mentions .py files
            list_obs = [o for o in runtime.context.observations if "a.py" in o]
            self.assertGreaterEqual(len(list_obs), 1)


class TestSubtaskCreatesFileParentReads(unittest.TestCase):
    """subtask(objective) → [subtask: write_file → final] → read_file → final"""

    def test_subtask_creates_file_parent_reads(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_depth=2, max_steps_per_call=8, recursive=True)

            # ScriptedModel returns in order: subtask call at depth 0,
            # then subtask's write + final at depth 1,
            # then parent's read + final at depth 0
            turns = [
                ModelTurn(tool_calls=[_tc("subtask", objective="create config")]),
                # --- subtask depth 1 ---
                ModelTurn(tool_calls=[_tc("write_file", path="config.json", content='{"key": "value"}')]),
                ModelTurn(text="config created", stop_reason="end_turn"),
                # --- back to depth 0 ---
                ModelTurn(tool_calls=[_tc("read_file", path="config.json")]),
                ModelTurn(text="subtask workflow complete", stop_reason="end_turn"),
            ]
            runtime = _make_runtime(root, cfg, turns, "sub-test")
            result = runtime.solve("use subtask to create file")

            self.assertEqual(result, "subtask workflow complete")
            self.assertTrue((root / "config.json").exists())
            parsed = json.loads((root / "config.json").read_text())
            self.assertEqual(parsed["key"], "value")
            # Context should have observations from both depths
            self.assertGreaterEqual(len(runtime.context.observations), 3)


# ===================================================================
# 2. Multi-Solve Session Continuity
# ===================================================================


class TestThreeSolveSession(unittest.TestCase):
    """solve("write file") → solve("read file") → solve("patch file")"""

    def test_three_solve_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=6)

            # All turns for all three solves go into one ScriptedModel
            turns = [
                # Solve 1: write
                ModelTurn(tool_calls=[_tc("write_file", path="multi.txt", content="line one\n")]),
                ModelTurn(text="written", stop_reason="end_turn"),
                # Solve 2: read
                ModelTurn(tool_calls=[_tc("read_file", path="multi.txt")]),
                ModelTurn(text="read ok", stop_reason="end_turn"),
                # Solve 3: patch
                ModelTurn(tool_calls=[_tc("apply_patch", patch=(
                    "*** Begin Patch\n"
                    "*** Update File: multi.txt\n"
                    "@@\n"
                    "-line one\n"
                    "+line two\n"
                    "*** End Patch"
                ))]),
                ModelTurn(text="patched", stop_reason="end_turn"),
            ]
            runtime = _make_runtime(root, cfg, turns, "three-solve")

            r1 = runtime.solve("write a file")
            obs_after_1 = len(runtime.context.observations)
            self.assertEqual(r1, "written")

            r2 = runtime.solve("read the file")
            obs_after_2 = len(runtime.context.observations)
            self.assertEqual(r2, "read ok")
            self.assertGreater(obs_after_2, obs_after_1)

            r3 = runtime.solve("patch the file")
            obs_after_3 = len(runtime.context.observations)
            self.assertEqual(r3, "patched")
            self.assertGreater(obs_after_3, obs_after_2)

            # state.json reflects all observations
            state = _read_state(root, "three-solve")
            self.assertEqual(len(state["external_observations"]), obs_after_3)


class TestResumeSessionPreservesFiles(unittest.TestCase):
    """Bootstrap → solve(write) → new bootstrap(resume=True) → solve(read)"""

    def test_resume_session_preserves_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=6)

            # First session: write a file
            turns1 = [
                ModelTurn(tool_calls=[_tc("write_file", path="persist.txt", content="persisted data")]),
                ModelTurn(text="saved", stop_reason="end_turn"),
            ]
            runtime1 = _make_runtime(root, cfg, turns1, "resume-fs")
            r1 = runtime1.solve("save data")
            self.assertEqual(r1, "saved")
            obs_count_1 = len(runtime1.context.observations)

            # Second session (resumed): read the file
            turns2 = [
                ModelTurn(tool_calls=[_tc("read_file", path="persist.txt")]),
                ModelTurn(text="data confirmed", stop_reason="end_turn"),
            ]
            runtime2 = _make_runtime(root, cfg, turns2, "resume-fs", resume=True)
            # Resumed context should have observations from first solve
            self.assertEqual(len(runtime2.context.observations), obs_count_1)

            r2 = runtime2.solve("confirm data")
            self.assertEqual(r2, "data confirmed")
            # File created by first session is readable
            self.assertTrue((root / "persist.txt").exists())


class TestContextSummaryFedToNextSolve(unittest.TestCase):
    """solve (generates observations) → solve (model sees context summary)"""

    def test_context_summary_fed_to_next_solve(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=6)

            # We use a custom model that captures what it receives
            captured_messages: list[str] = []

            class CapturingModel(ScriptedModel):
                def create_conversation(self, system_prompt: str, initial_user_message: str):
                    captured_messages.append(initial_user_message)
                    return super().create_conversation(system_prompt, initial_user_message)

            turns = [
                # Solve 1
                ModelTurn(tool_calls=[_tc("write_file", path="ctx.txt", content="context data")]),
                ModelTurn(text="first done", stop_reason="end_turn"),
                # Solve 2
                ModelTurn(text="second done", stop_reason="end_turn"),
            ]
            model = CapturingModel(scripted_turns=turns)
            tools = WorkspaceTools(root=root)
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            runtime = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="ctx-fed", resume=False,
            )

            runtime.solve("first task")
            self.assertGreater(len(runtime.context.observations), 0)

            runtime.solve("second task")

            # The second solve's initial message should contain context from first solve
            self.assertEqual(len(captured_messages), 2)
            second_msg = captured_messages[1]
            parsed = json.loads(second_msg)
            ctx_summary = parsed.get("external_context_summary", "")
            # Context summary should not be "(empty)" since first solve added observations
            self.assertNotEqual(ctx_summary, "(empty)")
            # The observation contains the tool output, e.g. "Wrote 12 chars to ctx.txt"
            self.assertIn("ctx.txt", ctx_summary)


# ===================================================================
# 3. Session Lifecycle & Persistence
# ===================================================================


class TestFullEventLogFlow(unittest.TestCase):
    """Bootstrap → solve (multi-step with patch) → verify events.jsonl"""

    def test_full_event_log_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=8)

            patch_text = (
                "*** Begin Patch\n"
                "*** Add File: evtfile.txt\n"
                "+event logged\n"
                "*** End Patch"
            )
            turns = [
                ModelTurn(tool_calls=[_tc("think", note="planning")]),
                ModelTurn(tool_calls=[_tc("apply_patch", patch=patch_text)]),
                ModelTurn(text="event flow done", stop_reason="end_turn"),
            ]
            runtime = _make_runtime(root, cfg, turns, "evt-flow")
            runtime.solve("test event log")

            events = _read_events(root, "evt-flow")
            event_types = [e["type"] for e in events]

            for expected in ("session_started", "objective", "trace", "step", "artifact", "result"):
                self.assertIn(
                    expected, event_types,
                    f"Expected event type '{expected}' not found in {event_types}",
                )

            # Verify artifact event references a patch
            artifact_events = [e for e in events if e["type"] == "artifact"]
            self.assertGreaterEqual(len(artifact_events), 1)
            self.assertEqual(artifact_events[0]["payload"]["kind"], "patch")


class TestSessionDirectoryStructure(unittest.TestCase):
    """Bootstrap → solve → inspect disk"""

    def test_session_directory_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=6)

            patch_text = (
                "*** Begin Patch\n"
                "*** Add File: struct.txt\n"
                "+structure test\n"
                "*** End Patch"
            )
            turns = [
                ModelTurn(tool_calls=[_tc("apply_patch", patch=patch_text)]),
                ModelTurn(text="structure ok", stop_reason="end_turn"),
            ]
            runtime = _make_runtime(root, cfg, turns, "dir-struct")
            runtime.solve("verify directory structure")

            session_dir = root / ".openplanter" / "sessions" / "dir-struct"
            self.assertTrue((session_dir / "metadata.json").exists())
            self.assertTrue((session_dir / "state.json").exists())
            self.assertTrue((session_dir / "events.jsonl").exists())
            self.assertTrue((session_dir / "artifacts").is_dir())
            self.assertTrue((session_dir / "artifacts" / "patches").is_dir())

            # Validate metadata.json content
            meta = json.loads((session_dir / "metadata.json").read_text())
            self.assertEqual(meta["session_id"], "dir-struct")
            self.assertIn("created_at", meta)
            self.assertIn("updated_at", meta)

            # Validate state.json content
            state = json.loads((session_dir / "state.json").read_text())
            self.assertEqual(state["session_id"], "dir-struct")
            self.assertIn("external_observations", state)

            # Validate patch files exist
            patches = list((session_dir / "artifacts" / "patches").glob("*.patch"))
            self.assertGreaterEqual(len(patches), 1)


class TestObservationCapAcrossSolves(unittest.TestCase):
    """Set max_persisted_observations=5, solve with many steps twice"""

    def test_observation_cap_across_solves(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_persisted_observations=5, max_steps_per_call=10)

            # Solve 1: 4 think steps + final
            # Solve 2: 4 think steps + final
            turns = [
                # Solve 1
                ModelTurn(tool_calls=[_tc("think", note="s1-a")]),
                ModelTurn(tool_calls=[_tc("think", note="s1-b")]),
                ModelTurn(tool_calls=[_tc("think", note="s1-c")]),
                ModelTurn(tool_calls=[_tc("think", note="s1-d")]),
                ModelTurn(text="solve1 done", stop_reason="end_turn"),
                # Solve 2
                ModelTurn(tool_calls=[_tc("think", note="s2-a")]),
                ModelTurn(tool_calls=[_tc("think", note="s2-b")]),
                ModelTurn(tool_calls=[_tc("think", note="s2-c")]),
                ModelTurn(tool_calls=[_tc("think", note="s2-d")]),
                ModelTurn(text="solve2 done", stop_reason="end_turn"),
            ]
            runtime = _make_runtime(root, cfg, turns, "obs-cap")

            runtime.solve("first batch")
            state1 = _read_state(root, "obs-cap")
            self.assertLessEqual(len(state1["external_observations"]), 5)

            runtime.solve("second batch")
            state2 = _read_state(root, "obs-cap")
            self.assertLessEqual(len(state2["external_observations"]), 5)
            # Most recent observations should be from solve 2
            last_obs = state2["external_observations"][-1]
            self.assertIn("s2-d", last_obs)


# ===================================================================
# 4. Error Recovery & Edge Cases
# ===================================================================


class TestShellFailureContinues(unittest.TestCase):
    """run_shell(failing command) → think → final"""

    def test_shell_failure_continues(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=6)

            turns = [
                ModelTurn(tool_calls=[_tc("run_shell", command="exit 42")]),
                ModelTurn(tool_calls=[_tc("think", note="shell failed, adapting")]),
                ModelTurn(text="recovered from failure", stop_reason="end_turn"),
            ]
            runtime = _make_runtime(root, cfg, turns, "shell-fail")
            result = runtime.solve("run failing command")

            self.assertEqual(result, "recovered from failure")
            # Check that nonzero exit code was captured
            exit_obs = [o for o in runtime.context.observations if "exit_code=42" in o]
            self.assertGreaterEqual(len(exit_obs), 1)


class TestBadPatchContinues(unittest.TestCase):
    """apply_patch(malformed) → think → final"""

    def test_bad_patch_continues(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=6)

            turns = [
                ModelTurn(tool_calls=[_tc("apply_patch", patch="this is not a valid patch")]),
                ModelTurn(tool_calls=[_tc("think", note="patch failed, trying alternative")]),
                ModelTurn(text="handled bad patch", stop_reason="end_turn"),
            ]
            runtime = _make_runtime(root, cfg, turns, "bad-patch")
            result = runtime.solve("apply malformed patch")

            self.assertEqual(result, "handled bad patch")
            # Observation should mention failure
            error_obs = [o for o in runtime.context.observations if "failed" in o.lower() or "Patch" in o]
            self.assertGreaterEqual(len(error_obs), 1)


class TestReadNonexistentFileContinues(unittest.TestCase):
    """read_file(missing.txt) → write_file → final"""

    def test_read_nonexistent_file_continues(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=6)

            turns = [
                ModelTurn(tool_calls=[_tc("read_file", path="missing.txt")]),
                ModelTurn(tool_calls=[_tc("write_file", path="missing.txt", content="now exists")]),
                ModelTurn(text="file created after miss", stop_reason="end_turn"),
            ]
            runtime = _make_runtime(root, cfg, turns, "read-miss")
            result = runtime.solve("read missing then write")

            self.assertEqual(result, "file created after miss")
            self.assertTrue((root / "missing.txt").exists())
            self.assertEqual((root / "missing.txt").read_text(), "now exists")
            # Check error observation from reading missing file
            miss_obs = [o for o in runtime.context.observations if "not found" in o.lower() or "File not found" in o]
            self.assertGreaterEqual(len(miss_obs), 1)


class TestPathEscapeBlockedInIntegration(unittest.TestCase):
    """write_file("../escape.txt", "bad") → ToolError raised, solve crashes.

    The ToolError from _resolve_path propagates uncaught through the engine,
    which is correct security behavior — path escapes are hard failures.
    """

    def test_path_escape_blocked_in_integration(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=4)

            turns = [
                ModelTurn(tool_calls=[_tc("write_file", path="../escape.txt", content="bad")]),
                ModelTurn(text="escape blocked", stop_reason="end_turn"),
            ]
            runtime = _make_runtime(root, cfg, turns, "escape-test")

            # Engine catches the ToolError and converts it to an observation
            # instead of crashing — the solve completes gracefully.
            result = runtime.solve("try path escape")
            self.assertIsInstance(result, str)
            # File should NOT exist outside workspace
            escape_path = Path(tmpdir).parent / "escape.txt"
            self.assertFalse(escape_path.exists())


# ===================================================================
# 5. Complex Subtask / Recursion
# ===================================================================


class TestSubtaskWithShell(unittest.TestCase):
    """subtask → [run_shell(echo hello) → final] → final"""

    def test_subtask_with_shell(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_depth=2, max_steps_per_call=6, recursive=True)

            turns = [
                # Depth 0: call subtask
                ModelTurn(tool_calls=[_tc("subtask", objective="run a shell command")]),
                # Depth 1 (subtask): run shell + final
                ModelTurn(tool_calls=[_tc("run_shell", command="echo hello-from-subtask")]),
                ModelTurn(text="subtask shell done", stop_reason="end_turn"),
                # Depth 0: final
                ModelTurn(text="parent done after subtask", stop_reason="end_turn"),
            ]
            runtime = _make_runtime(root, cfg, turns, "sub-shell")
            result = runtime.solve("subtask with shell")

            self.assertEqual(result, "parent done after subtask")
            # Shell output from subtask should appear in context
            shell_obs = [o for o in runtime.context.observations if "hello-from-subtask" in o]
            self.assertGreaterEqual(len(shell_obs), 1)


class TestDepthLimitedSubtaskInSession(unittest.TestCase):
    """max_depth=0, subtask called → receives depth limit error → final"""

    def test_depth_limited_subtask_in_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_depth=0, max_steps_per_call=4, recursive=True)

            turns = [
                ModelTurn(tool_calls=[_tc("subtask", objective="should be blocked")]),
                ModelTurn(text="depth limit handled", stop_reason="end_turn"),
            ]
            runtime = _make_runtime(root, cfg, turns, "depth-lim")
            result = runtime.solve("try deep subtask")

            self.assertEqual(result, "depth limit handled")
            # Observation should contain max recursion depth message
            depth_obs = [o for o in runtime.context.observations if "Max recursion depth" in o]
            self.assertGreaterEqual(len(depth_obs), 1)

            # Verify event log captures the step
            events = _read_events(root, "depth-lim")
            step_events = [e for e in events if e["type"] == "step"]
            self.assertGreaterEqual(len(step_events), 1)


if __name__ == "__main__":
    unittest.main()

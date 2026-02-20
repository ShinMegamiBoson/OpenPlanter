"""Live integration tests — full stack with real model APIs.

SessionRuntime → RLMEngine → real LLM → WorkspaceTools → real filesystem.
These tests make actual HTTP calls and consume API credits.
Skipped automatically when the corresponding API key is not configured.

Run explicitly:
    PYTHONPATH=src python -m pytest tests/test_integration_live.py -v
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent.config import AgentConfig
from agent.credentials import CredentialStore
from agent.engine import RLMEngine
from agent.model import AnthropicModel, OpenAICompatibleModel
from agent.runtime import SessionRuntime
from agent.tools import WorkspaceTools

# ---------------------------------------------------------------------------
# Load credentials once for the module
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_cred_store = CredentialStore(workspace=_PROJECT_ROOT, session_root_dir=".openplanter")
_creds = _cred_store.load()

_OPENAI_KEY = _creds.openai_api_key or ""
_ANTHROPIC_KEY = _creds.anthropic_api_key or ""

# Cheap/fast models to keep costs and latency minimal
_OPENAI_MODEL = "gpt-4.1-mini"
_ANTHROPIC_MODEL = "claude-sonnet-4-5-20250929"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_openai_engine(root: Path, cfg: AgentConfig) -> RLMEngine:
    model = OpenAICompatibleModel(
        model=_OPENAI_MODEL,
        api_key=_OPENAI_KEY,
        timeout_sec=90,
    )
    return RLMEngine(model=model, tools=WorkspaceTools(root=root), config=cfg)


def _make_anthropic_engine(root: Path, cfg: AgentConfig) -> RLMEngine:
    model = AnthropicModel(
        model=_ANTHROPIC_MODEL,
        api_key=_ANTHROPIC_KEY,
        timeout_sec=90,
    )
    return RLMEngine(model=model, tools=WorkspaceTools(root=root), config=cfg)


def _make_config(root: Path, **overrides) -> AgentConfig:
    defaults = {
        "workspace": root,
        "max_depth": 1,
        "max_steps_per_call": 8,
        "session_root_dir": ".openplanter",
        "max_persisted_observations": 400,
    }
    defaults.update(overrides)
    return AgentConfig(**defaults)


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


def _assert_no_error(test: unittest.TestCase, result: str) -> None:
    test.assertNotIn("Model error", result)
    test.assertNotIn("Step budget exhausted", result)


# ===================================================================
# OpenAI Live Integration Tests
# ===================================================================


class OpenAIWriteReadIntegration(unittest.TestCase):
    """Model writes a file, reads it back, returns contents."""

    @unittest.skipUnless(_OPENAI_KEY, "No OpenAI API key configured")
    def test_write_read_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root)
            engine = _make_openai_engine(root, cfg)
            runtime = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="oai-wr", resume=False,
            )

            result = runtime.solve(
                "Create a file called hello.txt containing exactly the text 'hello world'. "
                "Then read the file to confirm. Return the file contents as your final answer."
            )

            _assert_no_error(self, result)
            hello = root / "hello.txt"
            self.assertTrue(hello.exists(), "Model did not create hello.txt")
            self.assertIn("hello world", hello.read_text())
            self.assertGreater(len(runtime.context.observations), 0)


class OpenAIMultiStepIntegration(unittest.TestCase):
    """Model writes code, writes a test, runs the test via shell."""

    @unittest.skipUnless(_OPENAI_KEY, "No OpenAI API key configured")
    def test_write_code_and_test(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=10)
            engine = _make_openai_engine(root, cfg)
            runtime = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="oai-code", resume=False,
            )

            result = runtime.solve(
                "1. Create a Python file 'math_utils.py' with a function multiply(a, b) that returns a * b.\n"
                "2. Create a test file 'test_math.py' that imports multiply and asserts multiply(3, 4) == 12, "
                "then prints 'OK'.\n"
                "3. Run 'python test_math.py' to verify.\n"
                "4. Return 'all tests passed' as your final answer."
            )

            _assert_no_error(self, result)
            self.assertTrue((root / "math_utils.py").exists())
            self.assertTrue((root / "test_math.py").exists())


class OpenAIPatchIntegration(unittest.TestCase):
    """Model writes a file then patches it using apply_patch."""

    @unittest.skipUnless(_OPENAI_KEY, "No OpenAI API key configured")
    def test_write_then_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=10)
            engine = _make_openai_engine(root, cfg)
            runtime = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="oai-patch", resume=False,
            )

            result = runtime.solve(
                "1. Write a file 'greeting.txt' containing the single line 'hello world'.\n"
                "2. Use apply_patch to change 'world' to 'universe' in greeting.txt.\n"
                "3. Read greeting.txt to confirm the change.\n"
                "4. Return the updated contents as your final answer."
            )

            _assert_no_error(self, result)
            greeting = root / "greeting.txt"
            self.assertTrue(greeting.exists())
            content = greeting.read_text()
            self.assertIn("universe", content)


class OpenAISessionPersistenceIntegration(unittest.TestCase):
    """Two solves on the same runtime — session events and state persist."""

    @unittest.skipUnless(_OPENAI_KEY, "No OpenAI API key configured")
    def test_two_solve_session_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root)
            engine = _make_openai_engine(root, cfg)
            runtime = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="oai-persist", resume=False,
            )

            r1 = runtime.solve(
                "Write a file 'note.txt' with content 'first solve'. "
                "Return 'saved' as your final answer."
            )
            _assert_no_error(self, r1)
            obs_after_1 = len(runtime.context.observations)

            r2 = runtime.solve(
                "Read the file 'note.txt' and return its contents as your final answer."
            )
            _assert_no_error(self, r2)
            obs_after_2 = len(runtime.context.observations)
            self.assertGreater(obs_after_2, obs_after_1)

            # Verify events.jsonl has both objectives
            events = _read_events(root, "oai-persist")
            obj_events = [e for e in events if e["type"] == "objective"]
            self.assertGreaterEqual(len(obj_events), 2)

            # Verify state.json persisted
            state = _read_state(root, "oai-persist")
            self.assertEqual(len(state["external_observations"]), obs_after_2)


class OpenAISearchIntegration(unittest.TestCase):
    """Model writes files then uses search_files and list_files."""

    @unittest.skipUnless(_OPENAI_KEY, "No OpenAI API key configured")
    def test_search_and_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=10)
            engine = _make_openai_engine(root, cfg)
            runtime = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="oai-search", resume=False,
            )

            result = runtime.solve(
                "1. Create a file 'data.py' containing 'SECRET_TOKEN = 42'.\n"
                "2. Create a file 'readme.md' containing 'This is the readme'.\n"
                "3. Use search_files to find 'SECRET_TOKEN'.\n"
                "4. Use list_files to list all files.\n"
                "5. Return a summary of what you found as your final answer."
            )

            _assert_no_error(self, result)
            self.assertTrue((root / "data.py").exists())
            self.assertTrue((root / "readme.md").exists())


class OpenAISubtaskIntegration(unittest.TestCase):
    """Model uses subtask to delegate work, parent verifies."""

    @unittest.skipUnless(_OPENAI_KEY, "No OpenAI API key configured")
    def test_subtask_delegation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_depth=2, max_steps_per_call=10, recursive=True)
            engine = _make_openai_engine(root, cfg)
            runtime = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="oai-sub", resume=False,
            )

            result = runtime.solve(
                "Use a subtask to create a file called 'sub_output.txt' with content 'from subtask'. "
                "After the subtask completes, read 'sub_output.txt' to verify, "
                "then return 'subtask verified' as your final answer."
            )

            _assert_no_error(self, result)
            sub_file = root / "sub_output.txt"
            self.assertTrue(sub_file.exists(), "Subtask did not create file")


class OpenAIEventLogIntegration(unittest.TestCase):
    """Verify full event log structure from a live solve."""

    @unittest.skipUnless(_OPENAI_KEY, "No OpenAI API key configured")
    def test_event_log_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root)
            engine = _make_openai_engine(root, cfg)
            runtime = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="oai-events", resume=False,
            )

            result = runtime.solve(
                "Write a file 'event_test.txt' with content 'logged'. "
                "Return 'done' as your final answer."
            )
            _assert_no_error(self, result)

            events = _read_events(root, "oai-events")
            event_types = [e["type"] for e in events]
            for expected in ("session_started", "objective", "trace", "step", "result"):
                self.assertIn(expected, event_types)

            # Verify session directory structure
            session_dir = root / ".openplanter" / "sessions" / "oai-events"
            self.assertTrue((session_dir / "metadata.json").exists())
            self.assertTrue((session_dir / "state.json").exists())
            self.assertTrue((session_dir / "events.jsonl").exists())


class OpenAIResumeIntegration(unittest.TestCase):
    """Write in session 1, resume and read in session 2."""

    @unittest.skipUnless(_OPENAI_KEY, "No OpenAI API key configured")
    def test_resume_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root)

            # Session 1: write a file
            engine1 = _make_openai_engine(root, cfg)
            runtime1 = SessionRuntime.bootstrap(
                engine=engine1, config=cfg, session_id="oai-resume", resume=False,
            )
            r1 = runtime1.solve(
                "Write a file 'persist.txt' with content 'persisted data'. "
                "Return 'saved' as your final answer."
            )
            _assert_no_error(self, r1)
            obs_count = len(runtime1.context.observations)

            # Session 2: resume and read
            engine2 = _make_openai_engine(root, cfg)
            runtime2 = SessionRuntime.bootstrap(
                engine=engine2, config=cfg, session_id="oai-resume", resume=True,
            )
            self.assertEqual(len(runtime2.context.observations), obs_count)

            r2 = runtime2.solve(
                "Read the file 'persist.txt' and return its contents as your final answer."
            )
            _assert_no_error(self, r2)
            self.assertTrue((root / "persist.txt").exists())


# ===================================================================
# Anthropic Live Integration Tests
# ===================================================================


class AnthropicWriteReadIntegration(unittest.TestCase):
    """Model writes a file, reads it back, returns contents."""

    @unittest.skipUnless(_ANTHROPIC_KEY, "No Anthropic API key configured")
    def test_write_read_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root)
            engine = _make_anthropic_engine(root, cfg)
            runtime = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="ant-wr", resume=False,
            )

            result = runtime.solve(
                "Create a file called hello.txt containing exactly the text 'hello world'. "
                "Then read the file to confirm. Return the file contents as your final answer."
            )

            _assert_no_error(self, result)
            hello = root / "hello.txt"
            self.assertTrue(hello.exists(), "Model did not create hello.txt")
            self.assertIn("hello world", hello.read_text())


class AnthropicMultiStepIntegration(unittest.TestCase):
    """Model writes code, writes a test, runs the test via shell."""

    @unittest.skipUnless(_ANTHROPIC_KEY, "No Anthropic API key configured")
    def test_write_code_and_test(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=10)
            engine = _make_anthropic_engine(root, cfg)
            runtime = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="ant-code", resume=False,
            )

            result = runtime.solve(
                "1. Create a Python file 'math_utils.py' with a function multiply(a, b) that returns a * b.\n"
                "2. Create a test file 'test_math.py' that imports multiply and asserts multiply(3, 4) == 12, "
                "then prints 'OK'.\n"
                "3. Run 'python test_math.py' to verify.\n"
                "4. Return 'all tests passed' as your final answer."
            )

            _assert_no_error(self, result)
            self.assertTrue((root / "math_utils.py").exists())
            self.assertTrue((root / "test_math.py").exists())


class AnthropicPatchIntegration(unittest.TestCase):
    """Model writes a file then patches it using apply_patch."""

    @unittest.skipUnless(_ANTHROPIC_KEY, "No Anthropic API key configured")
    def test_write_then_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_steps_per_call=10)
            engine = _make_anthropic_engine(root, cfg)
            runtime = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="ant-patch", resume=False,
            )

            result = runtime.solve(
                "1. Write a file 'greeting.txt' containing the single line 'hello world'.\n"
                "2. Use apply_patch to change 'world' to 'universe' in greeting.txt.\n"
                "3. Read greeting.txt to confirm the change.\n"
                "4. Return the updated contents as your final answer."
            )

            _assert_no_error(self, result)
            greeting = root / "greeting.txt"
            self.assertTrue(greeting.exists())
            content = greeting.read_text()
            self.assertIn("universe", content)


class AnthropicSessionPersistenceIntegration(unittest.TestCase):
    """Two solves on the same runtime — session events and state persist."""

    @unittest.skipUnless(_ANTHROPIC_KEY, "No Anthropic API key configured")
    def test_two_solve_session_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root)
            engine = _make_anthropic_engine(root, cfg)
            runtime = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="ant-persist", resume=False,
            )

            r1 = runtime.solve(
                "Write a file 'note.txt' with content 'first solve'. "
                "Return 'saved' as your final answer."
            )
            _assert_no_error(self, r1)
            obs_after_1 = len(runtime.context.observations)

            r2 = runtime.solve(
                "Read the file 'note.txt' and return its contents as your final answer."
            )
            _assert_no_error(self, r2)
            obs_after_2 = len(runtime.context.observations)
            self.assertGreater(obs_after_2, obs_after_1)

            # Verify events.jsonl has both objectives
            events = _read_events(root, "ant-persist")
            obj_events = [e for e in events if e["type"] == "objective"]
            self.assertGreaterEqual(len(obj_events), 2)


class AnthropicSubtaskIntegration(unittest.TestCase):
    """Model uses subtask to delegate work, parent verifies."""

    @unittest.skipUnless(_ANTHROPIC_KEY, "No Anthropic API key configured")
    def test_subtask_delegation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_depth=2, max_steps_per_call=10, recursive=True)
            engine = _make_anthropic_engine(root, cfg)
            runtime = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="ant-sub", resume=False,
            )

            result = runtime.solve(
                "Use a subtask to create a file called 'sub_output.txt' with content 'from subtask'. "
                "After the subtask completes, read 'sub_output.txt' to verify, "
                "then return 'subtask verified' as your final answer."
            )

            _assert_no_error(self, result)
            sub_file = root / "sub_output.txt"
            self.assertTrue(sub_file.exists(), "Subtask did not create file")


class AnthropicResumeIntegration(unittest.TestCase):
    """Write in session 1, resume and read in session 2."""

    @unittest.skipUnless(_ANTHROPIC_KEY, "No Anthropic API key configured")
    def test_resume_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root)

            # Session 1: write a file
            engine1 = _make_anthropic_engine(root, cfg)
            runtime1 = SessionRuntime.bootstrap(
                engine=engine1, config=cfg, session_id="ant-resume", resume=False,
            )
            r1 = runtime1.solve(
                "Write a file 'persist.txt' with content 'persisted data'. "
                "Return 'saved' as your final answer."
            )
            _assert_no_error(self, r1)
            obs_count = len(runtime1.context.observations)

            # Session 2: resume and read
            engine2 = _make_anthropic_engine(root, cfg)
            runtime2 = SessionRuntime.bootstrap(
                engine=engine2, config=cfg, session_id="ant-resume", resume=True,
            )
            self.assertEqual(len(runtime2.context.observations), obs_count)

            r2 = runtime2.solve(
                "Read the file 'persist.txt' and return its contents as your final answer."
            )
            _assert_no_error(self, r2)
            self.assertTrue((root / "persist.txt").exists())


class AnthropicEventLogIntegration(unittest.TestCase):
    """Verify full event log structure from a live solve."""

    @unittest.skipUnless(_ANTHROPIC_KEY, "No Anthropic API key configured")
    def test_event_log_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root)
            engine = _make_anthropic_engine(root, cfg)
            runtime = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="ant-events", resume=False,
            )

            result = runtime.solve(
                "Write a file 'event_test.txt' with content 'logged'. "
                "Return 'done' as your final answer."
            )
            _assert_no_error(self, result)

            events = _read_events(root, "ant-events")
            event_types = [e["type"] for e in events]
            for expected in ("session_started", "objective", "trace", "step", "result"):
                self.assertIn(expected, event_types)


if __name__ == "__main__":
    unittest.main()

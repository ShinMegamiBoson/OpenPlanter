from __future__ import annotations

import json
import tempfile
import threading
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

from conftest import _tc
from agent.config import AgentConfig
from agent.engine import RLMEngine
from agent.prompts import build_system_prompt as _build_system_prompt
from agent.model import Conversation, ModelError, ModelTurn, ScriptedModel, ToolResult
from agent.tool_defs import TOOL_DEFINITIONS
from agent.tool_registry import ToolRegistry
from agent.tools import WorkspaceTools


class EngineTests(unittest.TestCase):
    def test_write_and_read_then_final(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=2, max_steps_per_call=6)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("write_file", path="hello.txt", content="hello")]),
                    ModelTurn(tool_calls=[_tc("read_file", path="hello.txt")]),
                    ModelTurn(text="completed", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            result = engine.solve("create and inspect hello")

            self.assertEqual(result, "completed")
            self.assertEqual((root / "hello.txt").read_text(), "hello")

    def test_subtask_recursion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=2, max_steps_per_call=4, recursive=True, acceptance_criteria=False)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("subtask", objective="do sub work")]),
                    ModelTurn(text="sub done", stop_reason="end_turn"),
                    ModelTurn(text="root done", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            result = engine.solve("top level objective")
            self.assertEqual(result, "root done")

    def test_depth_limit_blocks_subtask(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=0, max_steps_per_call=3, recursive=True, acceptance_criteria=False)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("subtask", objective="should be blocked")]),
                    ModelTurn(text="fallback final", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            result = engine.solve("depth limited")
            self.assertEqual(result, "fallback final")

    def test_subtask_rejected_in_flat_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=2, max_steps_per_call=3, recursive=False)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("subtask", objective="should be rejected")]),
                    ModelTurn(text="flat mode fallback", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            result = engine.solve("test flat mode")
            self.assertEqual(result, "flat mode fallback")

    def test_web_search_action_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=4)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("web_search", query="example query", num_results=2, include_text=False)]),
                    ModelTurn(text="done", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            with patch.object(tools, "web_search", return_value='{"total":0}') as mocked:
                result = engine.solve("run web search")
            self.assertEqual(result, "done")
            mocked.assert_called_once()

    def test_repo_map_action_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=4)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("repo_map", glob="*.py", max_files=50)]),
                    ModelTurn(text="done", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            with patch.object(tools, "repo_map", return_value='{"total":0}') as mocked:
                result = engine.solve("build repo map")
            self.assertEqual(result, "done")
            mocked.assert_called_once_with(glob="*.py", max_files=50)

    def test_runtime_policy_blocks_repeated_shell_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=6, acceptance_criteria=False)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("run_shell", command="echo hello")]),
                    ModelTurn(tool_calls=[_tc("run_shell", command="echo hello")]),
                    ModelTurn(tool_calls=[_tc("run_shell", command="echo hello")]),
                    ModelTurn(text="done", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            result, ctx = engine.solve_with_context("repeat shell")
            self.assertEqual(result, "done")
            self.assertTrue(
                any("Blocked by runtime policy" in obs for obs in ctx.observations),
                "expected policy block observation in context",
            )

    def test_registry_dispatch_precedes_legacy_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=4, acceptance_criteria=False)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("list_files")]),
                    ModelTurn(text="done", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            with patch.object(ToolRegistry, "try_invoke", return_value=(True, "registry-hit")) as mocked_registry:
                with patch.object(tools, "list_files", return_value="legacy-hit") as mocked_legacy:
                    result, ctx = engine.solve_with_context("registry precedence")
            self.assertEqual(result, "done")
            mocked_registry.assert_called()
            mocked_legacy.assert_not_called()
            self.assertTrue(any("registry-hit" in obs for obs in ctx.observations))

    def test_registry_unhandled_falls_back_to_legacy_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=4, acceptance_criteria=False)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("list_files")]),
                    ModelTurn(text="done", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            with patch.object(ToolRegistry, "try_invoke", return_value=(False, "")) as mocked_registry:
                with patch.object(tools, "list_files", return_value="legacy-hit") as mocked_legacy:
                    result, ctx = engine.solve_with_context("registry fallback")
            self.assertEqual(result, "done")
            mocked_registry.assert_called()
            mocked_legacy.assert_called_once()
            self.assertTrue(any("legacy-hit" in obs for obs in ctx.observations))

    def test_runtime_policy_blocks_before_registry_run_shell(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=6, acceptance_criteria=False)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("run_shell", command="echo hello")]),
                    ModelTurn(tool_calls=[_tc("run_shell", command="echo hello")]),
                    ModelTurn(tool_calls=[_tc("run_shell", command="echo hello")]),
                    ModelTurn(text="done", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            with patch.object(ToolRegistry, "try_invoke", return_value=(True, "ok")) as mocked_registry:
                result, ctx = engine.solve_with_context("policy before registry")
            self.assertEqual(result, "done")
            # Third repeated command is blocked before registry dispatch.
            self.assertEqual(mocked_registry.call_count, 2)
            self.assertTrue(any("Blocked by runtime policy" in obs for obs in ctx.observations))

    def test_engine_uses_injected_tool_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=4)
            tools = WorkspaceTools(root=root)
            calls: list[str] = []

            class SpyRegistry(ToolRegistry):
                def try_invoke(self, name, args, ctx=None):
                    calls.append(name)
                    return super().try_invoke(name, args, ctx)

            injected = SpyRegistry.from_definitions(TOOL_DEFINITIONS)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("list_files")]),
                    ModelTurn(text="done", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg, tool_registry=injected)
            self.assertIs(engine.tool_registry, injected)
            with patch.object(tools, "list_files", return_value="ok") as mocked_list_files:
                result = engine.solve("use injected registry")
            self.assertEqual(result, "done")
            mocked_list_files.assert_called_once()
            self.assertIn("list_files", calls)

    def test_registry_dispatch_used_for_read_image_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=4)
            tools = WorkspaceTools(root=root)
            calls: list[str] = []

            class SpyRegistry(ToolRegistry):
                def try_invoke(self, name, args, ctx=None):
                    calls.append(name)
                    return super().try_invoke(name, args, ctx)

            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("read_image", path="chart.png")]),
                    ModelTurn(text="done", stop_reason="end_turn"),
                ]
            )
            injected = SpyRegistry.from_definitions(TOOL_DEFINITIONS)
            engine = RLMEngine(model=model, tools=tools, config=cfg, tool_registry=injected)
            with patch.object(tools, "read_image", return_value=("ok image", "ZmFrZQ==", "image/png")) as mocked_read_image:
                result = engine.solve("read image")
            self.assertEqual(result, "done")
            self.assertIn("read_image", calls)
            mocked_read_image.assert_called_once_with("chart.png")

    def test_registry_dispatch_used_for_subtask_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=2, max_steps_per_call=4, recursive=True, acceptance_criteria=False)
            tools = WorkspaceTools(root=root)
            calls: list[str] = []

            class SpyRegistry(ToolRegistry):
                def try_invoke(self, name, args, ctx=None):
                    calls.append(name)
                    return super().try_invoke(name, args, ctx)

            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("subtask", objective="do sub work")]),
                    ModelTurn(text="sub done", stop_reason="end_turn"),
                    ModelTurn(text="root done", stop_reason="end_turn"),
                ]
            )
            injected = SpyRegistry.from_definitions(TOOL_DEFINITIONS)
            engine = RLMEngine(model=model, tools=tools, config=cfg, tool_registry=injected)
            result = engine.solve("top level objective")
            self.assertEqual(result, "root done")
            self.assertIn("subtask", calls)

    def test_registry_dispatch_used_for_read_artifact_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=3, recursive=True)
            tools = WorkspaceTools(root=root)
            calls: list[str] = []

            artifacts_dir = root / ".openplanter_artifacts"
            artifacts_dir.mkdir(parents=True)
            (artifacts_dir / "demo.jsonl").write_text(
                '{"artifact_id":"demo","objective":"demo objective"}\n{"step":1}\n',
                encoding="utf-8",
            )

            class SpyRegistry(ToolRegistry):
                def try_invoke(self, name, args, ctx=None):
                    calls.append(name)
                    return super().try_invoke(name, args, ctx)

            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("read_artifact", artifact_id="demo", offset=0, limit=1)]),
                    ModelTurn(text="done", stop_reason="end_turn"),
                ]
            )
            injected = SpyRegistry.from_definitions(TOOL_DEFINITIONS)
            engine = RLMEngine(model=model, tools=tools, config=cfg, tool_registry=injected)
            result, ctx = engine.solve_with_context("read artifact")
            self.assertEqual(result, "done")
            self.assertIn("read_artifact", calls)
            self.assertTrue(any("Artifact demo" in obs for obs in ctx.observations))


class CustomSystemPromptTests(unittest.TestCase):
    def test_custom_system_prompt_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=2)
            tools = WorkspaceTools(root=root)

            captured: list[str] = []

            class CapturingModel(ScriptedModel):
                def create_conversation(self, system_prompt: str, initial_user_message: str):
                    captured.append(system_prompt)
                    return super().create_conversation(system_prompt, initial_user_message)

            custom = "You are a custom test agent."
            model = CapturingModel(scripted_turns=[
                ModelTurn(text="done", stop_reason="end_turn"),
            ])
            engine = RLMEngine(model=model, tools=tools, config=cfg, system_prompt=custom)
            engine.solve("test")

            self.assertEqual(len(captured), 1)
            self.assertEqual(captured[0], custom)


class REPLPromptTests(unittest.TestCase):
    def test_recursive_prompt_includes_repl(self) -> None:
        prompt = _build_system_prompt(recursive=True)
        for keyword in ("REPL STRUCTURE", "READ", "EVAL", "PRINT", "LOOP"):
            self.assertIn(keyword, prompt)

    def test_flat_prompt_excludes_repl(self) -> None:
        prompt = _build_system_prompt(recursive=False)
        self.assertNotIn("REPL STRUCTURE", prompt)

    def test_recursive_initial_message_has_repl_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=2, max_steps_per_call=3, recursive=True)
            tools = WorkspaceTools(root=root)

            captured: list[str] = []

            class CapturingModel(ScriptedModel):
                def create_conversation(self, system_prompt: str, initial_user_message: str):
                    captured.append(initial_user_message)
                    return super().create_conversation(system_prompt, initial_user_message)

            model = CapturingModel(scripted_turns=[
                ModelTurn(text="done", stop_reason="end_turn"),
            ])
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            engine.solve("test objective")

            self.assertEqual(len(captured), 1)
            parsed = json.loads(captured[0])
            self.assertIn("repl_hint", parsed)
            self.assertIn("REPL", parsed["repl_hint"])

    def test_flat_initial_message_no_repl_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=2, max_steps_per_call=3, recursive=False)
            tools = WorkspaceTools(root=root)

            captured: list[str] = []

            class CapturingModel(ScriptedModel):
                def create_conversation(self, system_prompt: str, initial_user_message: str):
                    captured.append(initial_user_message)
                    return super().create_conversation(system_prompt, initial_user_message)

            model = CapturingModel(scripted_turns=[
                ModelTurn(text="done", stop_reason="end_turn"),
            ])
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            engine.solve("test objective")

            self.assertEqual(len(captured), 1)
            parsed = json.loads(captured[0])
            self.assertNotIn("repl_hint", parsed)


@dataclass
class ThreadSafeScriptedModel:
    """ScriptedModel with a lock so pop(0) is safe under concurrent access."""
    scripted_turns: list[ModelTurn] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def create_conversation(self, system_prompt: str, initial_user_message: str) -> Conversation:
        return Conversation(
            _provider_messages=[{"role": "user", "content": initial_user_message}],
            system_prompt=system_prompt,
        )

    def complete(self, conversation: Conversation) -> ModelTurn:
        with self._lock:
            if not self.scripted_turns:
                raise ModelError("ThreadSafeScriptedModel exhausted; no responses left.")
            return self.scripted_turns.pop(0)

    def append_assistant_turn(self, conversation: Conversation, turn: ModelTurn) -> None:
        pass

    def append_tool_results(self, conversation: Conversation, results: list[ToolResult]) -> None:
        pass

    def condense_conversation(self, conversation: Conversation, keep_recent_turns: int = 4) -> int:
        return 0


class ParallelExecutionTests(unittest.TestCase):
    def test_parallel_subtask_execution(self) -> None:
        """Two subtask calls in one turn should both run and results appear in order."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=3, max_steps_per_call=6, recursive=True, acceptance_criteria=False)
            tools = WorkspaceTools(root=root)
            # Turn 1 (parent): two subtask calls in one turn
            # Turn 2 (child A): final answer
            # Turn 3 (child B): final answer
            # Turn 4 (parent): final answer incorporating both results
            model = ThreadSafeScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[
                        _tc("subtask", objective="task A"),
                        _tc("subtask", objective="task B"),
                    ]),
                    ModelTurn(text="result A", stop_reason="end_turn"),
                    ModelTurn(text="result B", stop_reason="end_turn"),
                    ModelTurn(text="all done", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            result = engine.solve("parallel test")
            self.assertEqual(result, "all done")

    def test_parallel_subtask_write_conflict_is_blocked(self) -> None:
        """Parallel subtask calls writing the same file should trigger runtime conflict protection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "shared.txt").write_text("base\n", encoding="utf-8")
            cfg = AgentConfig(
                workspace=root,
                max_depth=3,
                max_steps_per_call=8,
                recursive=True,
                acceptance_criteria=False,
            )
            tools = WorkspaceTools(root=root)
            parent_model = ThreadSafeScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[
                        _tc("subtask", objective="update shared A", model="worker-a"),
                        _tc("subtask", objective="update shared B", model="worker-b"),
                    ]),
                    ModelTurn(text="parent done", stop_reason="end_turn"),
                ]
            )

            def _child(label: str) -> ScriptedModel:
                return ScriptedModel(
                    scripted_turns=[
                        ModelTurn(tool_calls=[_tc("read_file", path="shared.txt")]),
                        ModelTurn(tool_calls=[_tc("write_file", path="shared.txt", content=label)]),
                        ModelTurn(text=f"child {label} done", stop_reason="end_turn"),
                    ]
                )

            def factory(model_name: str, _effort: str | None):
                if model_name == "worker-a":
                    return _child("v1")
                return _child("v2")

            engine = RLMEngine(model=parent_model, tools=tools, config=cfg, model_factory=factory)
            result, ctx = engine.solve_with_context("conflict test")
            self.assertEqual(result, "parent done")
            self.assertTrue(
                any("Parallel write conflict" in obs for obs in ctx.observations),
                "expected parallel write conflict observation",
            )

    def test_sequential_fallback_no_factory_execute(self) -> None:
        """Execute calls without model_factory fall back to sequential execution."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(
                workspace=root, max_depth=4, max_steps_per_call=8,
                recursive=True, min_subtask_depth=0,
                acceptance_criteria=False,
            )
            tools = WorkspaceTools(root=root)
            # Turn 1 (parent): two execute calls
            # Turn 2 (child executor A): final answer
            # Turn 3 (child executor B): final answer
            # Turn 4 (parent): final answer
            model = ThreadSafeScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[
                        _tc("execute", objective="exec A"),
                        _tc("execute", objective="exec B"),
                    ]),
                    ModelTurn(text="exec A done", stop_reason="end_turn"),
                    ModelTurn(text="exec B done", stop_reason="end_turn"),
                    ModelTurn(text="parent done", stop_reason="end_turn"),
                ]
            )
            # No model_factory — should fall back to sequential
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            result = engine.solve("sequential fallback test")
            self.assertEqual(result, "parent done")


if __name__ == "__main__":
    unittest.main()

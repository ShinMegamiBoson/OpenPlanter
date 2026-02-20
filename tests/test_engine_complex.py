from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from conftest import _tc
from agent.config import AgentConfig
from agent.engine import RLMEngine, ExternalContext
from agent.model import Conversation, ModelTurn, RateLimitError, ScriptedModel, ToolResult
from agent.tools import WorkspaceTools


class EngineComplexTests(unittest.TestCase):
    """Complex behavior tests for the RLM engine."""

    # ------------------------------------------------------------------
    # 1. Step budget exhaustion
    # ------------------------------------------------------------------
    def test_step_budget_exhaustion(self) -> None:
        """ScriptedModel returning only think actions exceeds the step budget."""
        max_steps = 3
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=max_steps)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("think", note=f"thinking {i}")])
                    for i in range(max_steps + 5)
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            result = engine.solve("infinite thinking")
            self.assertIn("Step budget exhausted", result)

    # ------------------------------------------------------------------
    # 2. Nested subtasks at depth 2 (3-level recursion)
    # ------------------------------------------------------------------
    def test_nested_subtasks_depth_2(self) -> None:
        """Depth 0 -> subtask -> depth 1 -> subtask -> depth 2 -> final.
        Root should return properly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=3, max_steps_per_call=6, recursive=True, acceptance_criteria=False)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    # depth 0, step 1: issue subtask
                    ModelTurn(tool_calls=[_tc("subtask", objective="level-1 work")]),
                    # depth 1, step 1: issue subtask
                    ModelTurn(tool_calls=[_tc("subtask", objective="level-2 work")]),
                    # depth 2, step 1: final answer
                    ModelTurn(text="leaf done", stop_reason="end_turn"),
                    # depth 1, step 2: after subtask result, final
                    ModelTurn(text="mid done", stop_reason="end_turn"),
                    # depth 0, step 2: after subtask result, final
                    ModelTurn(text="root done", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            result = engine.solve("three-level task")
            self.assertEqual(result, "root done")

    # ------------------------------------------------------------------
    # 3. ExternalContext accumulates across steps
    # ------------------------------------------------------------------
    def test_external_context_accumulates_across_steps(self) -> None:
        """Run a multi-step solve and verify ExternalContext grows."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=6)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("think", note="step one")]),
                    ModelTurn(tool_calls=[_tc("think", note="step two")]),
                    ModelTurn(text="done", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            ctx = ExternalContext()
            result, returned_ctx = engine.solve_with_context(
                objective="accumulate context",
                context=ctx,
            )
            self.assertEqual(result, "done")
            # Two non-final steps should have added two observations.
            self.assertEqual(len(returned_ctx.observations), 2)
            self.assertIs(returned_ctx, ctx)

    # ------------------------------------------------------------------
    # 4. ExternalContext summary truncation
    # ------------------------------------------------------------------
    def test_external_context_summary_truncation(self) -> None:
        """Summary with max_items and max_chars truncates properly."""
        ctx = ExternalContext()
        # Add 10 observations, each about 60 chars long.
        for i in range(10):
            ctx.add(f"observation-{i}: " + "x" * 40)
        # max_items=2 picks the last 2, max_chars=50 truncates the joined text.
        summary = ctx.summary(max_items=2, max_chars=50)
        # Only the last 2 observations should be selected (not observation-0).
        self.assertNotIn("observation-0", summary)
        # The start of the first selected observation should appear.
        self.assertIn("observation-8", summary)
        # The output should be truncated because the two joined observations exceed 50 chars.
        self.assertIn("truncated", summary.lower())

    # ------------------------------------------------------------------
    # 5. Empty objective returns early
    # ------------------------------------------------------------------
    def test_empty_objective_returns_early(self) -> None:
        """Calling solve with whitespace-only objective returns early."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(scripted_turns=[])
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            result = engine.solve("  ")
            self.assertEqual(result, "No objective provided.")

    # ------------------------------------------------------------------
    # 6. ModelError during solve
    # ------------------------------------------------------------------
    def test_model_error_during_solve(self) -> None:
        """ScriptedModel raising ModelError is caught and reported."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=4)
            tools = WorkspaceTools(root=root)
            # The ScriptedModel has no responses, so the first call raises ModelError.
            model = ScriptedModel(scripted_turns=[])
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            result = engine.solve("trigger error")
            self.assertIn("Model error", result)

    # ------------------------------------------------------------------
    # 7. Observation clipping
    # ------------------------------------------------------------------
    def test_observation_clipping(self) -> None:
        """Tool output exceeding max_observation_chars is clipped."""
        max_obs = 100
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(
                workspace=root,
                max_depth=1,
                max_steps_per_call=4,
                max_observation_chars=max_obs,
            )
            tools = WorkspaceTools(root=root)
            # Write a file whose read output will exceed max_obs chars.
            big_content = "Z" * (max_obs * 3)
            (root / "big.txt").write_text(big_content, encoding="utf-8")

            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("read_file", path="big.txt")]),
                    ModelTurn(text="done", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            ctx = ExternalContext()
            result, returned_ctx = engine.solve_with_context(
                objective="read big file",
                context=ctx,
            )
            self.assertEqual(result, "done")
            # The observation from the read step should contain truncation marker.
            self.assertTrue(len(returned_ctx.observations) >= 1)
            obs = returned_ctx.observations[0]
            self.assertIn("truncated", obs.lower())

    # ------------------------------------------------------------------
    # 8. on_event callback fires
    # ------------------------------------------------------------------
    def test_on_event_callback_fires(self) -> None:
        """on_event receives messages containing depth and step info."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=4)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("think", note="planning")]),
                    ModelTurn(text="done", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            events: list[str] = []
            result = engine.solve("event test", on_event=events.append)
            self.assertEqual(result, "done")
            self.assertTrue(len(events) > 0, "Expected at least one event")
            # Events use format [dN/sN] for depth/step.
            has_depth = any("[d" in e for e in events)
            has_step = any("/s" in e for e in events)
            self.assertTrue(has_depth, "Expected an event containing depth marker")
            self.assertTrue(has_step, "Expected an event containing step marker")

    # ------------------------------------------------------------------
    # 9. on_step callback receives step data
    # ------------------------------------------------------------------
    def test_on_step_callback_receives_step_data(self) -> None:
        """on_step callback dicts have required keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=4)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("think", note="one")]),
                    ModelTurn(text="done", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            steps: list[dict] = []
            result, _ = engine.solve_with_context(
                objective="step callback test",
                on_step=steps.append,
            )
            self.assertEqual(result, "done")
            self.assertTrue(len(steps) >= 1, "Expected at least one step callback")
            required_keys = {"depth", "step", "objective", "action", "observation", "is_final"}
            for step_data in steps:
                self.assertTrue(
                    required_keys.issubset(step_data.keys()),
                    f"Step data missing keys: {required_keys - step_data.keys()}",
                )

    # ------------------------------------------------------------------
    # 10. Unknown action type handled gracefully
    # ------------------------------------------------------------------
    def test_unknown_action_type_handled(self) -> None:
        """An unknown tool name is tolerated and final is still reached."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=4)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("teleport")]),
                    ModelTurn(text="ok", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            ctx = ExternalContext()
            result, returned_ctx = engine.solve_with_context(
                objective="unknown action test",
                context=ctx,
            )
            self.assertEqual(result, "ok")
            # The unknown type should have been noted in context observations.
            self.assertTrue(len(returned_ctx.observations) >= 1)


    # ------------------------------------------------------------------
    # 11. Empty model response (no tool_calls, no text) triggers retry
    # ------------------------------------------------------------------
    def test_empty_model_response_triggers_retry(self) -> None:
        """When the model returns no tool calls and no text, engine prompts
        and continues to next step."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=4)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    # Empty response: no tool_calls, no text
                    ModelTurn(tool_calls=[], text=None, stop_reason="stop"),
                    # Second attempt: final answer
                    ModelTurn(text="recovered", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            result = engine.solve("empty response test")
            self.assertEqual(result, "recovered")

    # ------------------------------------------------------------------
    # 12. Multiple tool calls in a single turn
    # ------------------------------------------------------------------
    def test_multiple_tool_calls_in_single_turn(self) -> None:
        """Engine processes all tool calls from one turn."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=4)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[
                        _tc("think", note="thought-1"),
                        _tc("think", note="thought-2"),
                    ]),
                    ModelTurn(text="done", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            ctx = ExternalContext()
            result, returned_ctx = engine.solve_with_context(
                objective="multi tool",
                context=ctx,
            )
            self.assertEqual(result, "done")
            # Both tool calls should produce observations
            self.assertEqual(len(returned_ctx.observations), 2)
            self.assertIn("thought-1", returned_ctx.observations[0])
            self.assertIn("thought-2", returned_ctx.observations[1])

    # ------------------------------------------------------------------
    # 13. Final answer on_step callback has is_final=True and name="final"
    # ------------------------------------------------------------------
    def test_final_answer_on_step_callback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=4)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(text="my final answer", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            steps: list[dict] = []
            result, _ = engine.solve_with_context(
                objective="final test",
                on_step=steps.append,
            )
            self.assertEqual(result, "my final answer")
            # The final answer produces a step with is_final=True
            final_steps = [s for s in steps if s.get("is_final")]
            self.assertEqual(len(final_steps), 1)
            self.assertEqual(final_steps[0]["action"]["name"], "final")
            self.assertEqual(final_steps[0]["action"]["arguments"]["text"], "my final answer")

    # ------------------------------------------------------------------
    # 14-20. _apply_tool_call edge cases via engine solve
    # ------------------------------------------------------------------
    def test_read_file_empty_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=4)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("read_file", path="")]),
                    ModelTurn(text="done", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            ctx = ExternalContext()
            result, returned_ctx = engine.solve_with_context("empty path", context=ctx)
            self.assertEqual(result, "done")
            self.assertIn("requires path", returned_ctx.observations[0])

    def test_write_file_empty_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=4)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("write_file", path="", content="x")]),
                    ModelTurn(text="done", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            ctx = ExternalContext()
            result, returned_ctx = engine.solve_with_context("empty write path", context=ctx)
            self.assertEqual(result, "done")
            self.assertIn("requires path", returned_ctx.observations[0])

    def test_search_files_empty_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=4)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("search_files", query="")]),
                    ModelTurn(text="done", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            ctx = ExternalContext()
            result, returned_ctx = engine.solve_with_context("empty query", context=ctx)
            self.assertEqual(result, "done")
            self.assertIn("requires non-empty query", returned_ctx.observations[0])

    def test_run_shell_empty_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=4)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("run_shell", command="")]),
                    ModelTurn(text="done", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            ctx = ExternalContext()
            result, returned_ctx = engine.solve_with_context("empty cmd", context=ctx)
            self.assertEqual(result, "done")
            self.assertIn("requires command", returned_ctx.observations[0])

    def test_apply_patch_empty_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=4)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("apply_patch", patch="  ")]),
                    ModelTurn(text="done", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            ctx = ExternalContext()
            result, returned_ctx = engine.solve_with_context("empty patch", context=ctx)
            self.assertEqual(result, "done")
            self.assertIn("requires non-empty patch", returned_ctx.observations[0])

    def test_fetch_url_non_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=4)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("fetch_url", urls="not-a-list")]),
                    ModelTurn(text="done", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            ctx = ExternalContext()
            result, returned_ctx = engine.solve_with_context("fetch url", context=ctx)
            self.assertEqual(result, "done")
            self.assertIn("requires a list", returned_ctx.observations[0])

    def test_subtask_empty_objective(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=2, max_steps_per_call=4, recursive=True, acceptance_criteria=False)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("subtask", objective="")]),
                    ModelTurn(text="done", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            ctx = ExternalContext()
            result, returned_ctx = engine.solve_with_context("empty subtask", context=ctx)
            self.assertEqual(result, "done")
            self.assertIn("requires objective", returned_ctx.observations[0])

    def test_web_search_empty_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=4)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("web_search", query="")]),
                    ModelTurn(text="done", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            ctx = ExternalContext()
            result, returned_ctx = engine.solve_with_context("empty web query", context=ctx)
            self.assertEqual(result, "done")
            self.assertIn("requires non-empty query", returned_ctx.observations[0])

    # ------------------------------------------------------------------
    # 21. web_search non-int num_results defaults to 10
    # ------------------------------------------------------------------
    def test_web_search_non_int_num_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=4)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("web_search", query="test", num_results="five")]),
                    ModelTurn(text="done", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            with patch.object(tools, "web_search", return_value="results") as mocked:
                result = engine.solve("web search test")
            self.assertEqual(result, "done")
            mocked.assert_called_once_with(query="test", num_results=10, include_text=False)

    # ------------------------------------------------------------------
    # 22. web_search non-bool include_text defaults to False
    # ------------------------------------------------------------------
    def test_web_search_non_bool_include_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=4)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("web_search", query="test", include_text="yes")]),
                    ModelTurn(text="done", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            with patch.object(tools, "web_search", return_value="results") as mocked:
                result = engine.solve("web search test")
            self.assertEqual(result, "done")
            mocked.assert_called_once_with(query="test", num_results=10, include_text=False)

    # ------------------------------------------------------------------
    # 23. _clip_observation at exact boundary
    # ------------------------------------------------------------------
    def test_clip_observation_exact_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_observation_chars=10)
            tools = WorkspaceTools(root=root)
            engine = RLMEngine(model=ScriptedModel(scripted_turns=[]), tools=tools, config=cfg)
            # Exactly at limit: no truncation
            self.assertEqual(engine._clip_observation("1234567890"), "1234567890")
            # One over: truncation
            result = engine._clip_observation("12345678901")
            self.assertIn("truncated", result.lower())
            self.assertTrue(result.startswith("1234567890"))

    # ------------------------------------------------------------------
    # 24. ExternalContext.summary() with empty observations
    # ------------------------------------------------------------------
    def test_external_context_summary_empty(self) -> None:
        ctx = ExternalContext()
        self.assertEqual(ctx.summary(), "(empty)")

    # ------------------------------------------------------------------
    # 25. list_files tool call dispatch
    # ------------------------------------------------------------------
    def test_list_files_with_glob(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "foo.py").write_text("pass", encoding="utf-8")
            (root / "bar.txt").write_text("text", encoding="utf-8")
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=4)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("list_files", glob="*.py")]),
                    ModelTurn(text="done", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            ctx = ExternalContext()
            result, returned_ctx = engine.solve_with_context("list py", context=ctx)
            self.assertEqual(result, "done")
            self.assertIn("foo.py", returned_ctx.observations[0])
            self.assertNotIn("bar.txt", returned_ctx.observations[0])

    # ------------------------------------------------------------------
    # 26. list_files without glob
    # ------------------------------------------------------------------
    def test_list_files_without_glob(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "a.txt").write_text("x", encoding="utf-8")
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=4)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("list_files")]),
                    ModelTurn(text="done", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            ctx = ExternalContext()
            result, returned_ctx = engine.solve_with_context("list all", context=ctx)
            self.assertEqual(result, "done")
            self.assertIn("a.txt", returned_ctx.observations[0])

    # ------------------------------------------------------------------
    # 27. search_files with glob filter
    # ------------------------------------------------------------------
    def test_search_files_with_glob(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "code.py").write_text("hello world\n", encoding="utf-8")
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=4)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("search_files", query="hello", glob="*.py")]),
                    ModelTurn(text="done", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            ctx = ExternalContext()
            result, returned_ctx = engine.solve_with_context("search", context=ctx)
            self.assertEqual(result, "done")
            self.assertIn("hello", returned_ctx.observations[0])

    # ------------------------------------------------------------------
    # 28. Step budget exhaustion returns message with objective
    # ------------------------------------------------------------------
    def test_step_budget_message_includes_objective(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=1)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("think", note="planning")]),
                    ModelTurn(tool_calls=[_tc("think", note="still planning")]),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            result = engine.solve("my specific objective")
            self.assertIn("Step budget exhausted", result)
            self.assertIn("my specific objective", result)

    # ------------------------------------------------------------------
    # 29. think tool returns "Thought noted" observation
    # ------------------------------------------------------------------
    def test_think_tool_observation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=4)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("think", note="my thought")]),
                    ModelTurn(text="done", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            ctx = ExternalContext()
            result, returned_ctx = engine.solve_with_context("think test", context=ctx)
            self.assertEqual(result, "done")
            self.assertIn("Thought noted: my thought", returned_ctx.observations[0])

    # ------------------------------------------------------------------
    # 30. Rate-limit retries succeed without consuming extra step budget
    # ------------------------------------------------------------------
    def test_rate_limit_retries_then_succeeds(self) -> None:
        class RetryThenSuccessModel:
            def __init__(self) -> None:
                self.calls = 0

            def create_conversation(self, system_prompt: str, initial_user_message: str) -> Conversation:
                return Conversation(_provider_messages=[{"role": "user", "content": initial_user_message}])

            def complete(self, conversation: Conversation) -> ModelTurn:
                self.calls += 1
                if self.calls == 1:
                    raise RateLimitError(
                        "rate limit",
                        status_code=429,
                        provider_code="1302",
                    )
                return ModelTurn(text="done", stop_reason="end_turn")

            def append_assistant_turn(self, conversation: Conversation, turn: ModelTurn) -> None:
                pass

            def append_tool_results(self, conversation: Conversation, results: list[ToolResult]) -> None:
                pass

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(
                workspace=root,
                max_depth=1,
                max_steps_per_call=1,
                rate_limit_max_retries=3,
                rate_limit_backoff_base_sec=0.0,
                rate_limit_backoff_max_sec=0.0,
                rate_limit_retry_after_cap_sec=0.0,
            )
            tools = WorkspaceTools(root=root)
            model = RetryThenSuccessModel()
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            with patch("agent.engine.random.uniform", return_value=0.0):
                result = engine.solve("retry test")
            self.assertEqual(result, "done")
            self.assertEqual(model.calls, 2)

    # ------------------------------------------------------------------
    # 31. Exhausted rate-limit retries surfaces model error
    # ------------------------------------------------------------------
    def test_rate_limit_retries_exhausted_returns_model_error(self) -> None:
        class AlwaysRateLimitModel:
            def create_conversation(self, system_prompt: str, initial_user_message: str) -> Conversation:
                return Conversation(_provider_messages=[{"role": "user", "content": initial_user_message}])

            def complete(self, conversation: Conversation) -> ModelTurn:
                raise RateLimitError("still rate limited", status_code=429, provider_code="1302")

            def append_assistant_turn(self, conversation: Conversation, turn: ModelTurn) -> None:
                pass

            def append_tool_results(self, conversation: Conversation, results: list[ToolResult]) -> None:
                pass

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(
                workspace=root,
                max_depth=1,
                max_steps_per_call=1,
                rate_limit_max_retries=2,
                rate_limit_backoff_base_sec=0.0,
                rate_limit_backoff_max_sec=0.0,
                rate_limit_retry_after_cap_sec=0.0,
            )
            tools = WorkspaceTools(root=root)
            engine = RLMEngine(model=AlwaysRateLimitModel(), tools=tools, config=cfg)
            with patch("agent.engine.random.uniform", return_value=0.0):
                result = engine.solve("retry test")
            self.assertIn("Model error at depth 0, step 1", result)

    # ------------------------------------------------------------------
    # 32. Deadline exits gracefully during rate-limit wait
    # ------------------------------------------------------------------
    def test_rate_limit_wait_respects_deadline(self) -> None:
        class SlowRateLimitModel:
            def create_conversation(self, system_prompt: str, initial_user_message: str) -> Conversation:
                return Conversation(_provider_messages=[{"role": "user", "content": initial_user_message}])

            def complete(self, conversation: Conversation) -> ModelTurn:
                raise RateLimitError("wait", status_code=429, retry_after_sec=10.0)

            def append_assistant_turn(self, conversation: Conversation, turn: ModelTurn) -> None:
                pass

            def append_tool_results(self, conversation: Conversation, results: list[ToolResult]) -> None:
                pass

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(
                workspace=root,
                max_depth=1,
                max_steps_per_call=1,
                max_solve_seconds=1,
                rate_limit_max_retries=3,
            )
            tools = WorkspaceTools(root=root)
            engine = RLMEngine(model=SlowRateLimitModel(), tools=tools, config=cfg)
            result = engine.solve("deadline retry test")
            self.assertIn("Time limit exceeded", result)


if __name__ == "__main__":
    unittest.main()

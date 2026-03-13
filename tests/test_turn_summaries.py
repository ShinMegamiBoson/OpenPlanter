"""Tests for per-turn session summaries."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from conftest import _tc
from agent.config import AgentConfig
from agent.engine import RLMEngine, TurnSummary
from agent.model import ModelTurn, ScriptedModel
from agent.runtime import SessionRuntime
from agent.tools import WorkspaceTools


class TurnSummarySerializationTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        ts = TurnSummary(
            turn_number=1,
            objective="analyze data",
            result_preview="Found 3 entities...",
            timestamp="2026-01-15T10:00:00Z",
            steps_used=5,
            replay_seq_start=0,
        )
        d = ts.to_dict()
        restored = TurnSummary.from_dict(d)
        self.assertEqual(restored.turn_number, 1)
        self.assertEqual(restored.objective, "analyze data")
        self.assertEqual(restored.result_preview, "Found 3 entities...")
        self.assertEqual(restored.timestamp, "2026-01-15T10:00:00Z")
        self.assertEqual(restored.steps_used, 5)
        self.assertEqual(restored.replay_seq_start, 0)

    def test_from_dict_missing_optional_fields(self) -> None:
        d = {
            "turn_number": 2,
            "objective": "test",
            "result_preview": "ok",
            "timestamp": "2026-01-15T11:00:00Z",
        }
        ts = TurnSummary.from_dict(d)
        self.assertEqual(ts.steps_used, 0)
        self.assertEqual(ts.replay_seq_start, 0)

    def test_to_dict_all_fields_present(self) -> None:
        ts = TurnSummary(
            turn_number=3,
            objective="obj",
            result_preview="rp",
            timestamp="2026-01-15T12:00:00Z",
            steps_used=10,
            replay_seq_start=42,
        )
        d = ts.to_dict()
        self.assertIn("turn_number", d)
        self.assertIn("objective", d)
        self.assertIn("result_preview", d)
        self.assertIn("timestamp", d)
        self.assertIn("steps_used", d)
        self.assertIn("replay_seq_start", d)
        self.assertEqual(d["replay_seq_start"], 42)


class TurnSummaryPersistenceTests(unittest.TestCase):
    def _make_config(self, root: Path, **overrides) -> AgentConfig:
        defaults = dict(
            workspace=root,
            max_depth=1,
            max_steps_per_call=5,
            session_root_dir=".openplanter",
            max_persisted_observations=50,
            max_turn_summaries=50,
        )
        defaults.update(overrides)
        return AgentConfig(**defaults)

    def test_turn_summary_persisted_after_solve(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = self._make_config(root)
            model = ScriptedModel(
                scripted_turns=[ModelTurn(text="done", stop_reason="end_turn")]
            )
            engine = RLMEngine(model=model, tools=WorkspaceTools(root=root), config=cfg)
            runtime = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="sess-1", resume=False,
            )
            runtime.solve("test objective")

            state_path = root / ".openplanter" / "sessions" / "sess-1" / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertIn("turn_history", state)
            self.assertEqual(len(state["turn_history"]), 1)
            entry = state["turn_history"][0]
            self.assertEqual(entry["turn_number"], 1)
            self.assertEqual(entry["objective"], "test objective")
            self.assertEqual(entry["result_preview"], "done")

    def test_turn_summaries_loaded_on_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = self._make_config(root)

            # First turn
            model1 = ScriptedModel(
                scripted_turns=[ModelTurn(text="first result", stop_reason="end_turn")]
            )
            engine1 = RLMEngine(model=model1, tools=WorkspaceTools(root=root), config=cfg)
            rt1 = SessionRuntime.bootstrap(
                engine=engine1, config=cfg, session_id="sess-resume", resume=False,
            )
            rt1.solve("first objective")

            # Resume session
            model2 = ScriptedModel(
                scripted_turns=[ModelTurn(text="second result", stop_reason="end_turn")]
            )
            engine2 = RLMEngine(model=model2, tools=WorkspaceTools(root=root), config=cfg)
            rt2 = SessionRuntime.bootstrap(
                engine=engine2, config=cfg, session_id="sess-resume", resume=True,
            )
            self.assertIsNotNone(rt2.turn_history)
            self.assertEqual(len(rt2.turn_history), 1)
            self.assertEqual(rt2.turn_history[0].objective, "first objective")

            # Second turn
            rt2.solve("second objective")
            self.assertEqual(len(rt2.turn_history), 2)
            self.assertEqual(rt2.turn_history[1].turn_number, 2)
            self.assertEqual(rt2.turn_history[1].objective, "second objective")

    def test_turn_history_injected_into_initial_message(self) -> None:
        """When turn_history is non-empty, it should appear in the initial message dict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = self._make_config(root)

            # First turn
            model1 = ScriptedModel(
                scripted_turns=[ModelTurn(text="first done", stop_reason="end_turn")]
            )
            engine1 = RLMEngine(model=model1, tools=WorkspaceTools(root=root), config=cfg)
            rt1 = SessionRuntime.bootstrap(
                engine=engine1, config=cfg, session_id="sess-inject", resume=False,
            )
            rt1.solve("first task")

            # Second turn — capture the initial message sent to the model
            captured_messages: list[str] = []

            class CapturingModel(ScriptedModel):
                def create_conversation(self, system_prompt, initial_user_message):
                    captured_messages.append(initial_user_message)
                    return super().create_conversation(system_prompt, initial_user_message)

            model2 = CapturingModel(
                scripted_turns=[ModelTurn(text="second done", stop_reason="end_turn")]
            )
            engine2 = RLMEngine(model=model2, tools=WorkspaceTools(root=root), config=cfg)
            rt2 = SessionRuntime.bootstrap(
                engine=engine2, config=cfg, session_id="sess-inject", resume=True,
            )
            rt2.solve("second task")

            self.assertEqual(len(captured_messages), 1)
            msg_dict = json.loads(captured_messages[0])
            self.assertIn("turn_history", msg_dict)
            self.assertIn("turn_history_note", msg_dict)
            self.assertEqual(len(msg_dict["turn_history"]), 1)
            self.assertEqual(msg_dict["turn_history"][0]["objective"], "first task")
            self.assertIn("1 prior turn(s)", msg_dict["turn_history_note"])

    def test_empty_history_no_turn_history_key(self) -> None:
        """First turn should not have turn_history in the initial message."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = self._make_config(root)

            captured_messages: list[str] = []

            class CapturingModel(ScriptedModel):
                def create_conversation(self, system_prompt, initial_user_message):
                    captured_messages.append(initial_user_message)
                    return super().create_conversation(system_prompt, initial_user_message)

            model = CapturingModel(
                scripted_turns=[ModelTurn(text="done", stop_reason="end_turn")]
            )
            engine = RLMEngine(model=model, tools=WorkspaceTools(root=root), config=cfg)
            rt = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="sess-empty", resume=False,
            )
            rt.solve("first task")

            self.assertEqual(len(captured_messages), 1)
            msg_dict = json.loads(captured_messages[0])
            self.assertNotIn("turn_history", msg_dict)
            self.assertNotIn("turn_history_note", msg_dict)

    def test_max_turn_summaries_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = self._make_config(root, max_turn_summaries=3)

            # Run 5 turns
            for i in range(5):
                model = ScriptedModel(
                    scripted_turns=[ModelTurn(text=f"result-{i}", stop_reason="end_turn")]
                )
                engine = RLMEngine(model=model, tools=WorkspaceTools(root=root), config=cfg)
                rt = SessionRuntime.bootstrap(
                    engine=engine, config=cfg, session_id="sess-trunc",
                    resume=(i > 0),
                )
                rt.solve(f"task-{i}")

            # After 5 turns with max=3, state should have only 3 entries
            state_path = root / ".openplanter" / "sessions" / "sess-trunc" / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            history = state.get("turn_history", [])
            self.assertEqual(len(history), 3)
            # Should be the last 3 turns (3, 4, 5)
            self.assertEqual(history[0]["turn_number"], 3)
            self.assertEqual(history[1]["turn_number"], 4)
            self.assertEqual(history[2]["turn_number"], 5)

    def test_result_preview_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = self._make_config(root)
            long_text = "x" * 300
            model = ScriptedModel(
                scripted_turns=[ModelTurn(text=long_text, stop_reason="end_turn")]
            )
            engine = RLMEngine(model=model, tools=WorkspaceTools(root=root), config=cfg)
            rt = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="sess-trunc-preview", resume=False,
            )
            rt.solve("long result task")

            self.assertIsNotNone(rt.turn_history)
            self.assertEqual(len(rt.turn_history), 1)
            preview = rt.turn_history[0].result_preview
            self.assertTrue(preview.endswith("..."))
            self.assertLessEqual(len(preview), 204)  # 200 + "..."

    def test_backward_compat_old_state_no_turn_history(self) -> None:
        """Old state.json without turn_history key → empty list on resume."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = self._make_config(root)

            # Create session manually with old-format state
            session_dir = root / ".openplanter" / "sessions" / "sess-old"
            session_dir.mkdir(parents=True)
            (session_dir / "artifacts").mkdir()
            (session_dir / "metadata.json").write_text(
                json.dumps({"session_id": "sess-old", "workspace": str(root)}),
                encoding="utf-8",
            )
            (session_dir / "state.json").write_text(
                json.dumps({
                    "session_id": "sess-old",
                    "saved_at": "2026-01-01T00:00:00Z",
                    "external_observations": ["old obs"],
                }),
                encoding="utf-8",
            )

            model = ScriptedModel(
                scripted_turns=[ModelTurn(text="resumed", stop_reason="end_turn")]
            )
            engine = RLMEngine(model=model, tools=WorkspaceTools(root=root), config=cfg)
            rt = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="sess-old", resume=True,
            )
            self.assertIsNotNone(rt.turn_history)
            self.assertEqual(len(rt.turn_history), 0)
            rt.solve("new task")
            self.assertEqual(len(rt.turn_history), 1)
            self.assertEqual(rt.turn_history[0].turn_number, 1)

    def test_loop_metrics_persisted_and_loaded_additively(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = self._make_config(root)

            model1 = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("list_files")]),
                    ModelTurn(text="done-1", stop_reason="end_turn"),
                ]
            )
            engine1 = RLMEngine(model=model1, tools=WorkspaceTools(root=root), config=cfg)
            rt1 = SessionRuntime.bootstrap(
                engine=engine1, config=cfg, session_id="sess-loop", resume=False,
            )
            rt1.solve("first")

            state_path = root / ".openplanter" / "sessions" / "sess-loop" / "state.json"
            state_after_first = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertIn("loop_metrics", state_after_first)
            self.assertEqual(state_after_first["loop_metrics"]["turns"], 1)

            model2 = ScriptedModel(
                scripted_turns=[ModelTurn(text="done-2", stop_reason="end_turn")]
            )
            engine2 = RLMEngine(model=model2, tools=WorkspaceTools(root=root), config=cfg)
            rt2 = SessionRuntime.bootstrap(
                engine=engine2, config=cfg, session_id="sess-loop", resume=True,
            )
            self.assertIn("turns", rt2.loop_metrics)
            rt2.solve("second")

            state_after_second = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state_after_second["loop_metrics"]["turns"], 2)
            self.assertIn("last_turn", state_after_second["loop_metrics"])

    def test_backward_compat_old_state_no_loop_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = self._make_config(root)

            session_dir = root / ".openplanter" / "sessions" / "sess-no-loop"
            session_dir.mkdir(parents=True)
            (session_dir / "artifacts").mkdir()
            (session_dir / "metadata.json").write_text(
                json.dumps({"session_id": "sess-no-loop", "workspace": str(root)}),
                encoding="utf-8",
            )
            (session_dir / "state.json").write_text(
                json.dumps({
                    "session_id": "sess-no-loop",
                    "saved_at": "2026-01-01T00:00:00Z",
                    "external_observations": [],
                }),
                encoding="utf-8",
            )

            model = ScriptedModel(
                scripted_turns=[ModelTurn(text="resumed", stop_reason="end_turn")]
            )
            engine = RLMEngine(model=model, tools=WorkspaceTools(root=root), config=cfg)
            rt = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="sess-no-loop", resume=True,
            )
            self.assertIsNotNone(rt.loop_metrics)
            self.assertEqual(rt.loop_metrics.get("turns"), 0)
            rt.solve("new turn")
            self.assertEqual(rt.loop_metrics.get("turns"), 1)


if __name__ == "__main__":
    unittest.main()

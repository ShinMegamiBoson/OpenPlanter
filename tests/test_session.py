from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from conftest import _tc
from agent.config import AgentConfig
from agent.engine import RLMEngine
from agent.model import ModelTurn, ScriptedModel
from agent.runtime import SessionRuntime, _has_reasoning_content
from agent.tools import WorkspaceTools


class SessionRuntimeTests(unittest.TestCase):
    def test_session_persist_and_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(
                workspace=root,
                max_depth=2,
                max_steps_per_call=5,
                session_root_dir=".openplanter",
                max_persisted_observations=50,
            )

            model1 = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("write_file", path="note.txt", content="hello")]),
                    ModelTurn(text="first done", stop_reason="end_turn"),
                ]
            )
            engine1 = RLMEngine(model=model1, tools=WorkspaceTools(root=root), config=cfg)
            runtime1 = SessionRuntime.bootstrap(
                engine=engine1,
                config=cfg,
                session_id="session-a",
                resume=False,
            )
            result1 = runtime1.solve("write a note")
            self.assertEqual(result1, "first done")

            state_path = root / ".openplanter" / "sessions" / "session-a" / "state.json"
            self.assertTrue(state_path.exists())
            state = json.loads(state_path.read_text(encoding="utf-8"))
            obs = state.get("external_observations", [])
            self.assertTrue(isinstance(obs, list) and len(obs) > 0)

            model2 = ScriptedModel(
                scripted_turns=[ModelTurn(text="second done", stop_reason="end_turn")]
            )
            engine2 = RLMEngine(model=model2, tools=WorkspaceTools(root=root), config=cfg)
            runtime2 = SessionRuntime.bootstrap(
                engine=engine2,
                config=cfg,
                session_id="session-a",
                resume=True,
            )
            self.assertGreater(len(runtime2.context.observations), 0)
            result2 = runtime2.solve("finish")
            self.assertEqual(result2, "second done")

    def test_runtime_solve_injects_question_reasoning_packet_from_typed_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(
                workspace=root,
                max_depth=1,
                max_steps_per_call=2,
                session_root_dir=".openplanter",
                max_persisted_observations=50,
            )

            captured: list[str] = []

            class CapturingModel(ScriptedModel):
                def create_conversation(self, system_prompt: str, initial_user_message: str):
                    captured.append(initial_user_message)
                    return super().create_conversation(system_prompt, initial_user_message)

            model = CapturingModel(scripted_turns=[ModelTurn(text="ok", stop_reason="end_turn")])
            engine = RLMEngine(model=model, tools=WorkspaceTools(root=root), config=cfg)
            runtime = SessionRuntime.bootstrap(
                engine=engine,
                config=cfg,
                session_id="session-packet",
                resume=False,
            )

            session_dir = root / ".openplanter" / "sessions" / "session-packet"
            typed_state_path = session_dir / "investigation_state.json"
            typed = json.loads(typed_state_path.read_text(encoding="utf-8"))
            typed["questions"] = {
                "q_1": {
                    "id": "q_1",
                    "question_text": "Open question",
                    "status": "open",
                    "priority": "high",
                    "claim_ids": ["cl_1"],
                }
            }
            typed["claims"] = {
                "cl_1": {
                    "id": "cl_1",
                    "claim_text": "Needs support",
                    "status": "unresolved",
                    "evidence_ids": ["ev_1"],
                }
            }
            typed["evidence"] = {
                "ev_1": {
                    "id": "ev_1",
                    "evidence_type": "web_fetch",
                    "source_uri": "https://example.test",
                    "provenance_ids": ["pv_1"],
                }
            }
            typed_state_path.write_text(json.dumps(typed), encoding="utf-8")

            result = runtime.solve("continue")

            self.assertEqual(result, "ok")
            self.assertEqual(len(captured), 1)
            parsed = json.loads(captured[0])
            packet = parsed["question_reasoning_packet"]
            self.assertEqual(packet["reasoning_mode"], "question_centric")
            self.assertEqual(packet["focus_question_ids"], ["q_1"])
            self.assertEqual(packet["findings"]["unresolved"][0]["id"], "cl_1")
            self.assertEqual(packet["candidate_actions"][0]["id"], "ca_q_q_1")
            self.assertEqual(packet["candidate_actions"][1]["id"], "ca_c_cl_1")
            self.assertEqual(packet["candidate_actions"][1]["required_sources"], ["https://example.test"])

    def test_runtime_reasoning_gate_accepts_candidate_actions_only(self) -> None:
        packet = {
            "focus_question_ids": [],
            "findings": {"supported": [], "contested": [], "unresolved": []},
            "contradictions": [],
            "candidate_actions": [{"id": "ca_q_q_1"}],
        }

        self.assertTrue(_has_reasoning_content(packet))

    def test_runtime_resume_falls_back_to_legacy_state_when_typed_state_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(
                workspace=root,
                max_depth=1,
                max_steps_per_call=2,
                session_root_dir=".openplanter",
                max_persisted_observations=50,
            )
            session_id = "session-invalid-typed-resume"

            engine1 = RLMEngine(
                model=ScriptedModel(scripted_turns=[ModelTurn(text="ok", stop_reason="end_turn")]),
                tools=WorkspaceTools(root=root),
                config=cfg,
            )
            SessionRuntime.bootstrap(
                engine=engine1,
                config=cfg,
                session_id=session_id,
                resume=False,
            )

            session_dir = root / ".openplanter" / "sessions" / session_id
            state_path = session_dir / "state.json"
            typed_state_path = session_dir / "investigation_state.json"
            events_path = session_dir / "events.jsonl"

            legacy_state = json.loads(state_path.read_text(encoding="utf-8"))
            legacy_state["external_observations"] = ["legacy fallback observation"]
            state_path.write_text(json.dumps(legacy_state), encoding="utf-8")
            typed_state_path.write_text("{not-json", encoding="utf-8")

            engine2 = RLMEngine(
                model=ScriptedModel(scripted_turns=[ModelTurn(text="ok", stop_reason="end_turn")]),
                tools=WorkspaceTools(root=root),
                config=cfg,
            )
            runtime = SessionRuntime.bootstrap(
                engine=engine2,
                config=cfg,
                session_id=session_id,
                resume=True,
            )

            self.assertIn("legacy fallback observation", runtime.context.observations)
            self.assertEqual(typed_state_path.read_text(encoding="utf-8"), "{not-json")

            traces = [
                json.loads(line)["payload"]["message"]
                for line in events_path.read_text(encoding="utf-8").splitlines()
                if line.strip() and json.loads(line).get("type") == "trace"
            ]
            self.assertTrue(
                any("falling back to legacy state" in trace for trace in traces),
                traces,
            )
            self.assertTrue(
                any("preserving the corrupt typed state file" in trace for trace in traces),
                traces,
            )

    def test_runtime_solve_continues_without_reasoning_packet_when_typed_state_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(
                workspace=root,
                max_depth=1,
                max_steps_per_call=2,
                session_root_dir=".openplanter",
                max_persisted_observations=50,
            )

            captured: list[str] = []

            class CapturingModel(ScriptedModel):
                def create_conversation(self, system_prompt: str, initial_user_message: str):
                    captured.append(initial_user_message)
                    return super().create_conversation(system_prompt, initial_user_message)

            model = CapturingModel(scripted_turns=[ModelTurn(text="ok", stop_reason="end_turn")])
            engine = RLMEngine(model=model, tools=WorkspaceTools(root=root), config=cfg)
            runtime = SessionRuntime.bootstrap(
                engine=engine,
                config=cfg,
                session_id="session-invalid-typed-solve",
                resume=False,
            )

            session_dir = root / ".openplanter" / "sessions" / "session-invalid-typed-solve"
            typed_state_path = session_dir / "investigation_state.json"
            typed_state_path.write_text("{not-json", encoding="utf-8")

            events: list[str] = []
            result = runtime.solve("continue", on_event=events.append)

            self.assertEqual(result, "ok")
            self.assertEqual(typed_state_path.read_text(encoding="utf-8"), "{not-json")
            self.assertTrue(
                any("continuing without typed reasoning state" in message for message in events),
                events,
            )

            parsed = json.loads(captured[0])
            self.assertNotIn("question_reasoning_packet", parsed)

    def test_runtime_persist_preserves_corrupt_typed_state_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(
                workspace=root,
                max_depth=1,
                max_steps_per_call=2,
                session_root_dir=".openplanter",
                max_persisted_observations=50,
            )

            engine = RLMEngine(
                model=ScriptedModel(scripted_turns=[ModelTurn(text="ok", stop_reason="end_turn")]),
                tools=WorkspaceTools(root=root),
                config=cfg,
            )
            runtime = SessionRuntime.bootstrap(
                engine=engine,
                config=cfg,
                session_id="session-invalid-typed-persist",
                resume=False,
            )

            session_dir = root / ".openplanter" / "sessions" / "session-invalid-typed-persist"
            state_path = session_dir / "state.json"
            typed_state_path = session_dir / "investigation_state.json"
            typed_state_path.write_text("{not-json", encoding="utf-8")

            runtime.context.observations.append("fresh observation")
            runtime._persist_state()

            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertIn("fresh observation", persisted["external_observations"])
            self.assertEqual(typed_state_path.read_text(encoding="utf-8"), "{not-json")
            self.assertTrue(
                any(
                    "preserving the corrupt typed state file" in warning
                    for warning in runtime.store.drain_warnings()
                )
            )

    def test_patch_artifact_saved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(
                workspace=root,
                max_depth=1,
                max_steps_per_call=4,
                session_root_dir=".openplanter",
            )
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(
                        tool_calls=[
                            _tc(
                                "apply_patch",
                                patch=(
                                    "*** Begin Patch\n"
                                    "*** Add File: hello.txt\n"
                                    "+hello\n"
                                    "*** End Patch"
                                ),
                            )
                        ]
                    ),
                    ModelTurn(text="ok", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=WorkspaceTools(root=root), config=cfg)
            runtime = SessionRuntime.bootstrap(
                engine=engine,
                config=cfg,
                session_id="session-patch",
                resume=False,
            )
            result = runtime.solve("add file with patch")
            self.assertEqual(result, "ok")

            patch_dir = root / ".openplanter" / "sessions" / "session-patch" / "artifacts" / "patches"
            patches = sorted(patch_dir.glob("*.patch"))
            self.assertGreaterEqual(len(patches), 1)


if __name__ == "__main__":
    unittest.main()

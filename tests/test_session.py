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

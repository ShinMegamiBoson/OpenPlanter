from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from conftest import _tc

from agent.config import AgentConfig
from agent.engine import RLMEngine
from agent.model import ModelTurn, ScriptedModel
from agent.runtime import SessionError, SessionRuntime, SessionStore
from agent.tools import WorkspaceTools


def _make_config(root: Path, **overrides) -> AgentConfig:
    defaults = {
        "workspace": root,
        "max_depth": 2,
        "max_steps_per_call": 12,
        "session_root_dir": ".openplanter",
        "max_persisted_observations": 400,
    }
    defaults.update(overrides)
    return AgentConfig(**defaults)


def _make_engine(root: Path, cfg: AgentConfig, turns: list[ModelTurn]) -> RLMEngine:
    model = ScriptedModel(scripted_turns=turns)
    tools = WorkspaceTools(root=root)
    return RLMEngine(model=model, tools=tools, config=cfg)


class SessionComplexTests(unittest.TestCase):

    # 1. Create a session with known ID, then create again (non-resume) with same ID.
    #    Verify the second gets a different (suffixed) ID.
    def test_session_id_collision_avoidance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = SessionStore(workspace=root)

            sid1, _, _ = store.open_session(session_id="my-session", resume=False)
            self.assertEqual(sid1, "my-session")

            sid2, _, _ = store.open_session(session_id="my-session", resume=False)
            self.assertNotEqual(sid1, sid2)
            self.assertTrue(sid2.startswith("my-session-"))

    # 2. Bootstrap one session, solve twice. Verify context.observations grows
    #    after each solve. Verify state.json has all observations.
    def test_multiple_solves_accumulate_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_persisted_observations=400)

            turns = [
                ModelTurn(tool_calls=[_tc("think", note="planning first")]),
                ModelTurn(text="done-1", stop_reason="end_turn"),
                ModelTurn(tool_calls=[_tc("think", note="planning second")]),
                ModelTurn(text="done-2", stop_reason="end_turn"),
            ]
            engine = _make_engine(root, cfg, turns)
            runtime = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="accum", resume=False
            )

            runtime.solve("first objective")
            obs_after_first = len(runtime.context.observations)
            self.assertGreater(obs_after_first, 0)

            runtime.solve("second objective")
            obs_after_second = len(runtime.context.observations)
            self.assertGreater(obs_after_second, obs_after_first)

            state_path = root / ".openplanter" / "sessions" / "accum" / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(
                len(state["external_observations"]), obs_after_second
            )

    # 3. Set max_persisted_observations=3. Solve with a ScriptedModel that
    #    generates many steps (think + think + think + final). Then check
    #    state.json has at most 3 external_observations.
    def test_observation_trimming_on_persist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_persisted_observations=3)

            turns = [
                ModelTurn(tool_calls=[_tc("think", note="step-a")]),
                ModelTurn(tool_calls=[_tc("think", note="step-b")]),
                ModelTurn(tool_calls=[_tc("think", note="step-c")]),
                ModelTurn(text="trimmed-done", stop_reason="end_turn"),
            ]
            engine = _make_engine(root, cfg, turns)
            runtime = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="trim-test", resume=False
            )
            runtime.solve("generate many observations")

            state_path = (
                root / ".openplanter" / "sessions" / "trim-test" / "state.json"
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))
            obs = state.get("external_observations", [])
            self.assertLessEqual(len(obs), 3)

    # 4. Create 3 sessions with different IDs.
    #    Verify list_sessions returns them in reverse mtime order.
    def test_list_sessions_ordering(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = SessionStore(workspace=root)

            ids_in_order = ["alpha", "bravo", "charlie"]
            for sid in ids_in_order:
                store.open_session(session_id=sid, resume=False)
                # Touch the metadata to give each session a distinct mtime.
                meta = store._metadata_path(sid)
                # Bump mtime slightly so ordering is deterministic.
                time.sleep(0.05)
                meta.write_text(
                    json.dumps({"updated_at": "x"}), encoding="utf-8"
                )

            sessions = store.list_sessions()
            returned_ids = [s["session_id"] for s in sessions]
            self.assertEqual(returned_ids, list(reversed(ids_in_order)))

    # 5. Call open_session with resume=True and a non-existent session_id.
    #    Assert SessionError.
    def test_resume_nonexistent_session_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = SessionStore(workspace=root)
            with self.assertRaises(SessionError):
                store.open_session(session_id="does-not-exist", resume=True)

    # 6. Fresh workspace with no sessions. Call open_session(resume=True,
    #    session_id=None). Assert SessionError with "No previous sessions".
    def test_resume_no_previous_sessions_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = SessionStore(workspace=root)
            with self.assertRaises(SessionError) as cm:
                store.open_session(session_id=None, resume=True)
            self.assertIn("No previous sessions", str(cm.exception))

    # 7. Create a session, then manually write invalid JSON to its state.json.
    #    Call load_state. Assert SessionError.
    def test_corrupted_state_json_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = SessionStore(workspace=root)
            sid, _, _ = store.open_session(session_id="corrupt", resume=False)

            state_path = store._state_path(sid)
            state_path.write_text("{{{not valid json!!!", encoding="utf-8")

            with self.assertRaises(SessionError):
                store.load_state(sid)

    # 8. Run a multi-step solve, then read events.jsonl. Parse each line as JSON.
    #    Verify events include: session_started, objective, trace, step, result.
    def test_event_log_integrity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root)

            turns = [
                ModelTurn(tool_calls=[_tc("think", note="planning")]),
                ModelTurn(text="events-ok", stop_reason="end_turn"),
            ]
            engine = _make_engine(root, cfg, turns)
            runtime = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="evlog", resume=False
            )
            runtime.solve("test events")

            events_path = (
                root / ".openplanter" / "sessions" / "evlog" / "events.jsonl"
            )
            self.assertTrue(events_path.exists())

            events = []
            for line in events_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    events.append(json.loads(line))

            event_types = [e["type"] for e in events]
            for expected in ("session_started", "objective", "trace", "step", "result"):
                self.assertIn(
                    expected,
                    event_types,
                    f"Expected event type '{expected}' not found in {event_types}",
                )

    # 9. ScriptedModel that applies two patches in one solve.
    #    Verify artifacts/patches/ has 2 uniquely named .patch files.
    def test_multiple_patch_artifacts_named_uniquely(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_depth=1, max_steps_per_call=6)

            patch1 = (
                "*** Begin Patch\n"
                "*** Add File: file_a.txt\n"
                "+content a\n"
                "*** End Patch"
            )
            patch2 = (
                "*** Begin Patch\n"
                "*** Add File: file_b.txt\n"
                "+content b\n"
                "*** End Patch"
            )
            turns = [
                ModelTurn(tool_calls=[_tc("apply_patch", patch=patch1)]),
                ModelTurn(tool_calls=[_tc("apply_patch", patch=patch2)]),
                ModelTurn(text="patches applied", stop_reason="end_turn"),
            ]
            engine = _make_engine(root, cfg, turns)
            runtime = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="multi-patch", resume=False
            )
            runtime.solve("apply two patches")

            patch_dir = (
                root
                / ".openplanter"
                / "sessions"
                / "multi-patch"
                / "artifacts"
                / "patches"
            )
            self.assertTrue(patch_dir.exists(), "patches directory should exist")
            patch_files = sorted(patch_dir.glob("*.patch"))
            self.assertEqual(len(patch_files), 2)
            # Names must be unique.
            names = [p.name for p in patch_files]
            self.assertEqual(len(set(names)), 2, f"Patch names not unique: {names}")

    # 10. Fresh SessionStore with no sessions.
    #     Verify latest_session_id() returns None.
    def test_latest_session_id_returns_none_when_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = SessionStore(workspace=root)
            self.assertIsNone(store.latest_session_id())

    # 11. Write an artifact, verify file exists at expected path with correct
    #     content.
    def test_artifact_write_and_retrieve(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = SessionStore(workspace=root)
            sid, _, _ = store.open_session(session_id="art-test", resume=False)

            rel_path = store.write_artifact(
                session_id=sid,
                category="logs",
                name="build.log",
                content="Build succeeded.\n",
            )
            self.assertEqual(rel_path, "artifacts/logs/build.log")

            abs_path = store._session_dir(sid) / rel_path
            self.assertTrue(abs_path.exists())
            self.assertEqual(
                abs_path.read_text(encoding="utf-8"), "Build succeeded.\n"
            )

    # 12. Save state with 100 observations, set max_persisted_observations=5.
    #     Bootstrap with resume=True. Verify context has exactly 5 observations
    #     (the last 5).
    def test_bootstrap_restores_capped_observations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_persisted_observations=5)

            # First create the session so it exists on disk.
            store = SessionStore(workspace=root)
            sid, _, _ = store.open_session(session_id="cap-test", resume=False)

            # Write a state with 100 observations.
            all_obs = [f"obs-{i}" for i in range(100)]
            state = {
                "session_id": sid,
                "external_observations": all_obs,
            }
            store.save_state(sid, state)

            # Now bootstrap with resume=True.
            model = ScriptedModel(scripted_turns=[])
            engine = RLMEngine(
                model=model, tools=WorkspaceTools(root=root), config=cfg
            )
            runtime = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="cap-test", resume=True
            )

            self.assertEqual(len(runtime.context.observations), 5)
            self.assertEqual(runtime.context.observations, all_obs[-5:])


    # 13. _safe_component with special characters
    def test_safe_component_special_chars(self) -> None:
        from agent.runtime import _safe_component
        self.assertEqual(_safe_component("hello world!"), "hello-world")
        self.assertEqual(_safe_component("file/path\\name"), "file-path-name")
        self.assertEqual(_safe_component("a@b#c$d"), "a-b-c-d")
        # Normal names pass through
        self.assertEqual(_safe_component("valid-name.txt"), "valid-name.txt")
        self.assertEqual(_safe_component("under_score"), "under_score")

    # 14. _safe_component with empty/all-special input → "artifact"
    def test_safe_component_empty_input(self) -> None:
        from agent.runtime import _safe_component
        self.assertEqual(_safe_component(""), "artifact")
        self.assertEqual(_safe_component("!!!"), "artifact")
        self.assertEqual(_safe_component("   "), "artifact")

    # 15. list_sessions with corrupted metadata
    def test_list_sessions_corrupted_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = SessionStore(workspace=root)
            sid, _, _ = store.open_session(session_id="corrupt-meta", resume=False)

            # Corrupt the metadata file
            meta_path = store._metadata_path(sid)
            meta_path.write_text("{{{invalid json!!!", encoding="utf-8")

            sessions = store.list_sessions()
            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0]["session_id"], sid)
            # created_at should be None since metadata parsing failed
            self.assertIsNone(sessions[0]["created_at"])

    # 16. _touch_metadata with corrupted metadata recovers
    def test_touch_metadata_recovers_from_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = SessionStore(workspace=root)
            sid, _, _ = store.open_session(session_id="touch-test", resume=False)

            # Corrupt the metadata file
            meta_path = store._metadata_path(sid)
            meta_path.write_text("{{{broken", encoding="utf-8")

            # Calling _touch_metadata should not crash; it recovers gracefully
            store._touch_metadata(sid)

            # Metadata should now be valid JSON
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            self.assertEqual(meta["session_id"], sid)
            self.assertIn("updated_at", meta)

    # 17. SessionRuntime.solve with empty objective
    def test_runtime_solve_empty_objective(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root)
            turns = [ModelTurn(text="should not reach", stop_reason="end_turn")]
            engine = _make_engine(root, cfg, turns)
            runtime = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="empty-obj", resume=False
            )
            result = runtime.solve("  ")
            self.assertEqual(result, "No objective provided.")

    # 18. Step callback patch artifact format verification
    def test_step_callback_patch_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_depth=1, max_steps_per_call=6)

            patch_text = (
                "*** Begin Patch\n"
                "*** Add File: verify.txt\n"
                "+verified\n"
                "*** End Patch"
            )
            turns = [
                ModelTurn(tool_calls=[_tc("apply_patch", patch=patch_text)]),
                ModelTurn(text="done", stop_reason="end_turn"),
            ]
            engine = _make_engine(root, cfg, turns)
            runtime = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="patch-fmt", resume=False
            )
            runtime.solve("verify patch format")

            # Verify events include an artifact event
            events_path = (
                root / ".openplanter" / "sessions" / "patch-fmt" / "events.jsonl"
            )
            events = []
            for line in events_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    events.append(json.loads(line))

            artifact_events = [e for e in events if e["type"] == "artifact"]
            self.assertEqual(len(artifact_events), 1)
            self.assertEqual(artifact_events[0]["payload"]["kind"], "patch")

    # 19. save_state and load_state round-trip
    def test_save_and_load_state_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = SessionStore(workspace=root)
            sid, _, _ = store.open_session(session_id="roundtrip", resume=False)

            state = {
                "session_id": sid,
                "external_observations": ["obs1", "obs2"],
                "custom_field": "hello",
            }
            store.save_state(sid, state)
            loaded = store.load_state(sid)
            self.assertEqual(loaded["session_id"], sid)
            self.assertEqual(loaded["external_observations"], ["obs1", "obs2"])
            self.assertEqual(loaded["custom_field"], "hello")

    # 20. open_session with no session_id generates unique ID
    def test_open_session_generates_unique_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = SessionStore(workspace=root)
            sid1, _, _ = store.open_session(session_id=None, resume=False)
            sid2, _, _ = store.open_session(session_id=None, resume=False)
            self.assertNotEqual(sid1, sid2)
            self.assertTrue(len(sid1) > 0)
            self.assertTrue(len(sid2) > 0)

    # 21. latest_session_id returns most recently modified
    def test_latest_session_id_returns_most_recent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = SessionStore(workspace=root)
            store.open_session(session_id="first", resume=False)
            time.sleep(0.05)
            store.open_session(session_id="second", resume=False)
            # Touch second session to make it most recent
            store._touch_metadata("second")
            latest = store.latest_session_id()
            self.assertEqual(latest, "second")

    # 22. append_event creates events file
    def test_append_event_creates_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = SessionStore(workspace=root)
            sid, _, _ = store.open_session(session_id="evt-test", resume=False)
            store.append_event(sid, "test_event", {"key": "value"})

            events_path = store._events_path(sid)
            self.assertTrue(events_path.exists())
            line = events_path.read_text(encoding="utf-8").strip()
            event = json.loads(line)
            self.assertEqual(event["type"], "test_event")
            self.assertEqual(event["payload"]["key"], "value")

    # 23. Bootstrap with resume restores context from state
    def test_bootstrap_resume_restores_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root, max_persisted_observations=100)

            # Create initial session with some observations
            turns1 = [
                ModelTurn(tool_calls=[_tc("think", note="remembered")]),
                ModelTurn(text="done-1", stop_reason="end_turn"),
            ]
            engine1 = _make_engine(root, cfg, turns1)
            runtime1 = SessionRuntime.bootstrap(
                engine=engine1, config=cfg, session_id="resume-test", resume=False
            )
            runtime1.solve("first task")
            obs_count = len(runtime1.context.observations)
            self.assertGreater(obs_count, 0)

            # Resume the session
            from agent.model import ScriptedModel
            model2 = ScriptedModel(scripted_turns=[])
            engine2 = RLMEngine(
                model=model2, tools=WorkspaceTools(root=root), config=cfg
            )
            runtime2 = SessionRuntime.bootstrap(
                engine=engine2, config=cfg, session_id="resume-test", resume=True
            )
            self.assertEqual(len(runtime2.context.observations), obs_count)

    # 24. Non-list persisted observations handled gracefully
    def test_bootstrap_non_list_observations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = _make_config(root)
            store = SessionStore(workspace=root)
            sid, _, _ = store.open_session(session_id="nonlist", resume=False)

            # Write state with non-list observations
            state = {
                "session_id": sid,
                "external_observations": "not a list",
            }
            store.save_state(sid, state)

            from agent.model import ScriptedModel
            model = ScriptedModel(scripted_turns=[])
            engine = RLMEngine(
                model=model, tools=WorkspaceTools(root=root), config=cfg
            )
            runtime = SessionRuntime.bootstrap(
                engine=engine, config=cfg, session_id="nonlist", resume=True
            )
            # Should gracefully handle non-list by treating as empty
            self.assertEqual(len(runtime.context.observations), 0)


if __name__ == "__main__":
    unittest.main()

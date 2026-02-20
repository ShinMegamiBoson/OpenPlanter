"""Tests for replay-capable LLM interaction logging."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from conftest import _tc

from agent.config import AgentConfig
from agent.engine import RLMEngine
from agent.model import ModelTurn, ScriptedModel
from agent.replay_log import ReplayLogger
from agent.tools import WorkspaceTools


class ReplayLoggerUnitTests(unittest.TestCase):
    def _read_records(self, path: Path) -> list[dict]:
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        return [json.loads(line) for line in lines]

    def test_write_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "replay.jsonl"
            logger = ReplayLogger(path=p)
            logger.write_header(
                provider="openai",
                model="gpt-5",
                base_url="https://api.openai.com/v1",
                system_prompt="You are helpful.",
                tool_defs=[{"name": "run_shell"}],
                reasoning_effort="high",
                temperature=0.0,
            )
            records = self._read_records(p)
            self.assertEqual(len(records), 1)
            r = records[0]
            self.assertEqual(r["type"], "header")
            self.assertEqual(r["conversation_id"], "root")
            self.assertEqual(r["provider"], "openai")
            self.assertEqual(r["model"], "gpt-5")
            self.assertEqual(r["system_prompt"], "You are helpful.")
            self.assertEqual(r["reasoning_effort"], "high")
            self.assertEqual(r["temperature"], 0.0)

    def test_header_omits_none_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "replay.jsonl"
            logger = ReplayLogger(path=p)
            logger.write_header(
                provider="anthropic",
                model="claude-opus-4-6",
                base_url="https://api.anthropic.com/v1",
                system_prompt="sys",
                tool_defs=[],
            )
            records = self._read_records(p)
            r = records[0]
            self.assertNotIn("reasoning_effort", r)
            self.assertNotIn("temperature", r)

    def test_seq0_writes_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "replay.jsonl"
            logger = ReplayLogger(path=p)
            messages = [{"role": "system", "content": "hi"}, {"role": "user", "content": "hello"}]
            logger.log_call(
                depth=0, step=1, messages=messages,
                response={"content": "ok"}, input_tokens=10, output_tokens=5, elapsed_sec=1.5,
            )
            records = self._read_records(p)
            self.assertEqual(len(records), 1)
            r = records[0]
            self.assertEqual(r["type"], "call")
            self.assertEqual(r["seq"], 0)
            self.assertIn("messages_snapshot", r)
            self.assertNotIn("messages_delta", r)
            self.assertEqual(r["messages_snapshot"], messages)
            self.assertEqual(r["input_tokens"], 10)
            self.assertEqual(r["output_tokens"], 5)

    def test_seq1_writes_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "replay.jsonl"
            logger = ReplayLogger(path=p)
            msgs_v1 = [{"role": "user", "content": "hi"}]
            logger.log_call(
                depth=0, step=1, messages=list(msgs_v1),
                response={"r": 1},
            )
            msgs_v2 = [
                *msgs_v1,
                {"role": "assistant", "content": "hello"},
                {"role": "user", "content": "thanks"},
            ]
            logger.log_call(
                depth=0, step=2, messages=list(msgs_v2),
                response={"r": 2},
            )
            records = self._read_records(p)
            self.assertEqual(len(records), 2)
            r0 = records[0]
            r1 = records[1]
            self.assertEqual(r0["seq"], 0)
            self.assertIn("messages_snapshot", r0)
            self.assertEqual(r1["seq"], 1)
            self.assertIn("messages_delta", r1)
            self.assertNotIn("messages_snapshot", r1)
            self.assertEqual(r1["messages_delta"], [
                {"role": "assistant", "content": "hello"},
                {"role": "user", "content": "thanks"},
            ])

    def test_reconstruction_from_snapshot_and_deltas(self) -> None:
        """snapshot + deltas == full message list at any point."""
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "replay.jsonl"
            logger = ReplayLogger(path=p)
            all_messages: list[dict] = [{"role": "user", "content": "start"}]

            # seq 0
            logger.log_call(depth=0, step=1, messages=list(all_messages), response={})
            # seq 1
            all_messages.append({"role": "assistant", "content": "step1"})
            logger.log_call(depth=0, step=2, messages=list(all_messages), response={})
            # seq 2
            all_messages.append({"role": "user", "content": "step2"})
            all_messages.append({"role": "assistant", "content": "step2-resp"})
            logger.log_call(depth=0, step=3, messages=list(all_messages), response={})

            records = self._read_records(p)
            # Reconstruct messages at each seq point
            reconstructed = records[0]["messages_snapshot"]
            self.assertEqual(reconstructed, [{"role": "user", "content": "start"}])

            reconstructed = reconstructed + records[1]["messages_delta"]
            self.assertEqual(reconstructed, [
                {"role": "user", "content": "start"},
                {"role": "assistant", "content": "step1"},
            ])

            reconstructed = reconstructed + records[2]["messages_delta"]
            self.assertEqual(reconstructed, all_messages)

    def test_child_logger(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "replay.jsonl"
            parent = ReplayLogger(path=p)
            parent.write_header(
                provider="test", model="m", base_url="", system_prompt="",
                tool_defs=[],
            )
            parent.log_call(depth=0, step=1, messages=[{"role": "user", "content": "hi"}], response={})

            child = parent.child(depth=0, step=2)
            self.assertEqual(child.conversation_id, "root/d0s2")
            self.assertEqual(child.path, p)
            child.write_header(
                provider="test", model="m-child", base_url="", system_prompt="",
                tool_defs=[],
            )
            child.log_call(depth=1, step=1, messages=[{"role": "user", "content": "sub"}], response={})

            # grandchild
            grandchild = child.child(depth=1, step=2)
            self.assertEqual(grandchild.conversation_id, "root/d0s2/d1s2")

            records = self._read_records(p)
            self.assertEqual(len(records), 4)
            # parent header + call
            self.assertEqual(records[0]["conversation_id"], "root")
            self.assertEqual(records[1]["conversation_id"], "root")
            # child header + call
            self.assertEqual(records[2]["conversation_id"], "root/d0s2")
            self.assertEqual(records[2]["model"], "m-child")
            self.assertEqual(records[3]["conversation_id"], "root/d0s2")
            self.assertEqual(records[3]["seq"], 0)
            self.assertIn("messages_snapshot", records[3])

    def test_creates_parent_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "deep" / "nested" / "replay.jsonl"
            logger = ReplayLogger(path=p)
            logger.write_header(
                provider="test", model="test", base_url="", system_prompt="",
                tool_defs=[],
            )
            self.assertTrue(p.exists())


class ReplayLoggerIntegrationTests(unittest.TestCase):
    def _read_records(self, path: Path) -> list[dict]:
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        return [json.loads(line) for line in lines]

    def test_engine_writes_replay_log(self) -> None:
        """End-to-end: engine + ScriptedModel produces a valid replay log."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=2, max_steps_per_call=6)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(tool_calls=[_tc("write_file", path="f.txt", content="data")]),
                    ModelTurn(text="done", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)

            replay_path = root / "replay.jsonl"
            replay_logger = ReplayLogger(path=replay_path)

            result, _ = engine.solve_with_context(
                objective="write a file",
                replay_logger=replay_logger,
            )
            self.assertEqual(result, "done")
            self.assertTrue(replay_path.exists())

            lines = replay_path.read_text(encoding="utf-8").strip().splitlines()
            records = [json.loads(line) for line in lines]

            # Header + 2 calls (one for tool call turn, one for final answer)
            self.assertEqual(records[0]["type"], "header")
            self.assertEqual(records[0]["model"], "(unknown)")  # ScriptedModel has no .model attr

            call_records = [r for r in records if r["type"] == "call"]
            self.assertEqual(len(call_records), 2)
            self.assertEqual(call_records[0]["seq"], 0)
            self.assertIn("messages_snapshot", call_records[0])
            self.assertEqual(call_records[1]["seq"], 1)
            self.assertIn("messages_delta", call_records[1])

    def test_subtask_logged_with_child_conversation(self) -> None:
        """Subtask calls produce their own header + calls in the replay log."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=2, max_steps_per_call=6, recursive=True, acceptance_criteria=False)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    # depth 0, step 1: spawn subtask
                    ModelTurn(tool_calls=[_tc("subtask", objective="do sub work")]),
                    # depth 1, step 1: subtask final answer
                    ModelTurn(text="sub done", stop_reason="end_turn"),
                    # depth 0, step 2: root final answer
                    ModelTurn(text="root done", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)

            replay_path = root / "replay.jsonl"
            replay_logger = ReplayLogger(path=replay_path)

            result, _ = engine.solve_with_context(
                objective="top level",
                replay_logger=replay_logger,
            )
            self.assertEqual(result, "root done")

            records = self._read_records(replay_path)
            headers = [r for r in records if r["type"] == "header"]
            calls = [r for r in records if r["type"] == "call"]

            # Two headers: root + subtask child
            self.assertEqual(len(headers), 2)
            self.assertEqual(headers[0]["conversation_id"], "root")
            self.assertEqual(headers[1]["conversation_id"], "root/d0s1")

            # Root: 2 calls (step 1 = subtask, step 2 = final)
            # Child: 1 call (step 1 = final answer)
            root_calls = [c for c in calls if c["conversation_id"] == "root"]
            child_calls = [c for c in calls if c["conversation_id"] == "root/d0s1"]
            self.assertEqual(len(root_calls), 2)
            self.assertEqual(len(child_calls), 1)
            self.assertEqual(child_calls[0]["depth"], 1)

    def test_replay_log_via_runtime(self) -> None:
        """SessionRuntime.solve() creates replay.jsonl in session dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=4)
            tools = WorkspaceTools(root=root)
            model = ScriptedModel(
                scripted_turns=[
                    ModelTurn(text="hi", stop_reason="end_turn"),
                ]
            )
            engine = RLMEngine(model=model, tools=tools, config=cfg)

            from agent.runtime import SessionRuntime
            runtime = SessionRuntime.bootstrap(engine=engine, config=cfg)
            result = runtime.solve("say hi")
            self.assertEqual(result, "hi")

            replay_path = (
                root / cfg.session_root_dir / "sessions" / runtime.session_id / "replay.jsonl"
            )
            self.assertTrue(replay_path.exists())

            lines = replay_path.read_text(encoding="utf-8").strip().splitlines()
            records = [json.loads(line) for line in lines]
            types = [r["type"] for r in records]
            self.assertIn("header", types)
            self.assertIn("call", types)


if __name__ == "__main__":
    unittest.main()

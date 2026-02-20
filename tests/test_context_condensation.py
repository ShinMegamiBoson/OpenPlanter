"""Tests for context condensation across model implementations."""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from typing import Any

from agent.model import (
    AnthropicModel,
    Conversation,
    ModelTurn,
    OpenAICompatibleModel,
    ScriptedModel,
    ToolResult,
)


def _make_openai_conversation_with_tool_results(n: int) -> Conversation:
    """Build a fake OpenAI-format conversation with n tool result messages."""
    msgs: list[Any] = [{"role": "system", "content": "system prompt"}]
    for i in range(n):
        # Assistant turn with a tool call
        msgs.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": f"call_{i}",
                "type": "function",
                "function": {"name": "run_shell", "arguments": "{}"},
            }],
        })
        # Tool result
        msgs.append({
            "role": "tool",
            "tool_call_id": f"call_{i}",
            "name": "run_shell",
            "content": f"output from tool call {i} " * 50,
        })
    return Conversation(_provider_messages=msgs, system_prompt="system prompt")


def _make_anthropic_conversation_with_tool_results(n: int) -> Conversation:
    """Build a fake Anthropic-format conversation with n tool result user messages."""
    msgs: list[Any] = []
    for i in range(n):
        # Assistant turn
        msgs.append({
            "role": "assistant",
            "content": [{"type": "tool_use", "id": f"tu_{i}", "name": "run_shell", "input": {}}],
        })
        # User turn with tool_result blocks
        msgs.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": f"tu_{i}",
                "content": f"anthropic output {i} " * 50,
            }],
        })
    return Conversation(_provider_messages=msgs, system_prompt="system prompt")


class OpenAICondenseTests(unittest.TestCase):
    def test_openai_condense(self) -> None:
        model = OpenAICompatibleModel(model="gpt-4o", api_key="fake")
        conv = _make_openai_conversation_with_tool_results(8)
        condensed = model.condense_conversation(conv, keep_recent_turns=4)
        self.assertEqual(condensed, 4)
        # First 4 tool messages should be condensed.
        tool_msgs = [m for m in conv._provider_messages if isinstance(m, dict) and m.get("role") == "tool"]
        for m in tool_msgs[:4]:
            self.assertEqual(m["content"], "[earlier tool output condensed]")
        # Last 4 should be intact.
        for m in tool_msgs[4:]:
            self.assertNotEqual(m["content"], "[earlier tool output condensed]")

    def test_condense_preserves_recent(self) -> None:
        model = OpenAICompatibleModel(model="gpt-4o", api_key="fake")
        conv = _make_openai_conversation_with_tool_results(10)
        condensed = model.condense_conversation(conv, keep_recent_turns=3)
        self.assertEqual(condensed, 7)
        tool_msgs = [m for m in conv._provider_messages if isinstance(m, dict) and m.get("role") == "tool"]
        # 7 condensed, 3 intact
        for m in tool_msgs[:7]:
            self.assertEqual(m["content"], "[earlier tool output condensed]")
        for m in tool_msgs[7:]:
            self.assertNotEqual(m["content"], "[earlier tool output condensed]")

    def test_condense_idempotent(self) -> None:
        model = OpenAICompatibleModel(model="gpt-4o", api_key="fake")
        conv = _make_openai_conversation_with_tool_results(6)
        first = model.condense_conversation(conv, keep_recent_turns=3)
        self.assertEqual(first, 3)
        second = model.condense_conversation(conv, keep_recent_turns=3)
        self.assertEqual(second, 0)


class AnthropicCondenseTests(unittest.TestCase):
    def test_anthropic_condense(self) -> None:
        model = AnthropicModel(model="claude-opus-4-6", api_key="fake")
        conv = _make_anthropic_conversation_with_tool_results(8)
        condensed = model.condense_conversation(conv, keep_recent_turns=4)
        self.assertEqual(condensed, 4)
        # Verify tool_use_id is preserved on condensed blocks.
        tool_user_msgs = [
            m for m in conv._provider_messages
            if isinstance(m, dict) and m.get("role") == "user"
            and isinstance(m.get("content"), list)
            and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in m["content"])
        ]
        for m in tool_user_msgs[:4]:
            for block in m["content"]:
                if block.get("type") == "tool_result":
                    self.assertEqual(block["content"], "[earlier tool output condensed]")
                    self.assertIn("tool_use_id", block)
        for m in tool_user_msgs[4:]:
            for block in m["content"]:
                if block.get("type") == "tool_result":
                    self.assertNotEqual(block["content"], "[earlier tool output condensed]")


class ScriptedModelCondenseTests(unittest.TestCase):
    def test_scripted_model_noop(self) -> None:
        model = ScriptedModel()
        conv = Conversation(_provider_messages=[], system_prompt="")
        result = model.condense_conversation(conv)
        self.assertEqual(result, 0)


class EngineCondensationTriggerTests(unittest.TestCase):
    def test_engine_triggers_condensation(self) -> None:
        """When input_tokens exceeds threshold, engine calls condense_conversation."""
        import tempfile
        from pathlib import Path

        from agent.config import AgentConfig
        from agent.engine import RLMEngine

        condensation_calls: list[int] = []

        @dataclass
        class HighTokenModel:
            """Model that reports high input_tokens to trigger condensation."""
            scripted_turns: list[ModelTurn] = field(default_factory=list)
            model: str = "gpt-4o"

            def create_conversation(self, system_prompt: str, initial_user_message: str) -> Conversation:
                return Conversation(
                    _provider_messages=[{"role": "user", "content": initial_user_message}],
                    system_prompt=system_prompt,
                )

            def complete(self, conversation: Conversation) -> ModelTurn:
                if not self.scripted_turns:
                    return ModelTurn(text="exhausted", stop_reason="end_turn")
                return self.scripted_turns.pop(0)

            def append_assistant_turn(self, conversation: Conversation, turn: ModelTurn) -> None:
                pass

            def append_tool_results(self, conversation: Conversation, results: list[ToolResult]) -> None:
                pass

            def condense_conversation(self, conversation: Conversation, keep_recent_turns: int = 4) -> int:
                condensation_calls.append(1)
                return 5

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=1, max_steps_per_call=4)
            from agent.tools import WorkspaceTools
            tools = WorkspaceTools(root=root)
            # First turn: high input_tokens to trigger condensation, then final answer.
            model = HighTokenModel(scripted_turns=[
                ModelTurn(
                    tool_calls=[],
                    text=None,
                    stop_reason="",
                    input_tokens=100_000,  # > 0.75 * 128000
                    output_tokens=100,
                ),
                ModelTurn(text="done", stop_reason="end_turn", input_tokens=50_000),
            ])
            engine = RLMEngine(model=model, tools=tools, config=cfg)
            # The first turn has no tool calls and no text, so it nudges.
            # The second turn is the final answer.
            result = engine.solve("test condensation")
            self.assertEqual(result, "done")
            # Condensation should NOT have been called for the second turn
            # (50k < 96k threshold), but should have been called for the first (100k > 96k).
            self.assertEqual(len(condensation_calls), 1)


if __name__ == "__main__":
    unittest.main()

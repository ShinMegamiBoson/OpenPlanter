from __future__ import annotations

import unittest
from unittest.mock import patch

from conftest import mock_anthropic_stream, mock_openai_stream
from agent.model import (
    AnthropicModel,
    EchoFallbackModel,
    ModelError,
    ModelTurn,
    OpenAICompatibleModel,
    ScriptedModel,
    _extract_content,
    _parse_timestamp,
    _sorted_models,
)


class ModelComplexTests(unittest.TestCase):
    # ------------------------------------------------------------------ #
    # 1. ScriptedModel exhaustion
    # ------------------------------------------------------------------ #
    def test_scripted_model_exhaustion_raises(self) -> None:
        model = ScriptedModel(scripted_turns=[ModelTurn(text="ok", stop_reason="end_turn")])
        conv = model.create_conversation("sys", "usr")
        model.complete(conv)  # first call succeeds
        with self.assertRaises(ModelError) as ctx:
            model.complete(conv)  # second call should raise
        self.assertIn("exhausted", str(ctx.exception).lower())

    # ------------------------------------------------------------------ #
    # 2-3. EchoFallbackModel
    # ------------------------------------------------------------------ #
    def test_echo_fallback_model_returns_text(self) -> None:
        model = EchoFallbackModel()
        conv = model.create_conversation("sys", "usr")
        turn = model.complete(conv)
        self.assertIsNotNone(turn.text)
        self.assertEqual(turn.tool_calls, [])
        self.assertEqual(turn.stop_reason, "end_turn")

    def test_echo_fallback_custom_note(self) -> None:
        model = EchoFallbackModel(note="custom")
        conv = model.create_conversation("sys", "usr")
        turn = model.complete(conv)
        self.assertEqual(turn.text, "custom")

    # ------------------------------------------------------------------ #
    # 4-8. _extract_content
    # ------------------------------------------------------------------ #
    def test_extract_content_string(self) -> None:
        self.assertEqual(_extract_content("hello"), "hello")

    def test_extract_content_list_of_text_dicts(self) -> None:
        self.assertEqual(
            _extract_content([{"text": "a"}, {"text": "b"}]),
            "a\nb",
        )

    def test_extract_content_list_with_type_text(self) -> None:
        self.assertEqual(
            _extract_content([{"type": "text", "text": "c"}]),
            "c",
        )

    def test_extract_content_mixed(self) -> None:
        self.assertEqual(
            _extract_content([{"text": "a"}, {"type": "text", "text": "b"}, {"other": "x"}]),
            "a\nb",
        )

    def test_extract_content_non_string_non_list(self) -> None:
        self.assertEqual(_extract_content(42), "")

    # ------------------------------------------------------------------ #
    # 9-15. _parse_timestamp
    # ------------------------------------------------------------------ #
    def test_parse_timestamp_int(self) -> None:
        self.assertEqual(_parse_timestamp(1700000000), 1700000000)

    def test_parse_timestamp_float(self) -> None:
        self.assertEqual(_parse_timestamp(1700000000.5), 1700000000)

    def test_parse_timestamp_digit_string(self) -> None:
        self.assertEqual(_parse_timestamp("1700000000"), 1700000000)

    def test_parse_timestamp_iso_string(self) -> None:
        self.assertEqual(_parse_timestamp("2024-01-01T00:00:00Z"), 1704067200)

    def test_parse_timestamp_invalid_string(self) -> None:
        self.assertEqual(_parse_timestamp("not-a-date"), 0)

    def test_parse_timestamp_empty_string(self) -> None:
        self.assertEqual(_parse_timestamp(""), 0)

    def test_parse_timestamp_none(self) -> None:
        self.assertEqual(_parse_timestamp(None), 0)

    # ------------------------------------------------------------------ #
    # 16. _sorted_models
    # ------------------------------------------------------------------ #
    def test_sorted_models_ordering(self) -> None:
        models = [
            {"id": "alpha", "created_ts": 100},
            {"id": "charlie", "created_ts": 300},
            {"id": "bravo", "created_ts": 200},
            {"id": "delta", "created_ts": 300},  # same ts as charlie, id tiebreak
        ]
        result = _sorted_models(models)
        ids = [m["id"] for m in result]
        # Newest first; for equal timestamps, id descending (delta > charlie).
        self.assertEqual(ids, ["delta", "charlie", "bravo", "alpha"])

    # ------------------------------------------------------------------ #
    # 17-19. OpenAICompatibleModel error paths
    # ------------------------------------------------------------------ #
    def test_openai_missing_content_raises(self) -> None:
        def fake_stream_sse(url, method, headers, payload, first_byte_timeout=10, stream_timeout=120, max_retries=3, on_sse_event=None):
            # Return events that accumulate to empty choices
            return [("", {"choices": [{"delta": {}, "finish_reason": "stop"}]})]

        with patch("agent.model._http_stream_sse", fake_stream_sse):
            model = OpenAICompatibleModel(model="m", api_key="k")
            conv = model.create_conversation("sys", "usr")
            # With streaming, empty choices still produces a valid response
            # but with no content and no tool calls
            turn = model.complete(conv)
            self.assertIsNone(turn.text)

    # ------------------------------------------------------------------ #
    # 20-22. AnthropicModel behaviour
    # ------------------------------------------------------------------ #
    def test_anthropic_system_prompt_in_payload(self) -> None:
        captured: dict = {}

        def fake_http_json(url, method, headers, payload=None, timeout_sec=90):  # type: ignore[no-untyped-def]
            captured["payload"] = payload
            return {
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
            }

        with patch("agent.model._http_stream_sse", mock_anthropic_stream(fake_http_json)):
            model = AnthropicModel(model="m", api_key="k")
            conv = model.create_conversation("You are helpful.", "Hi")
            model.complete(conv)
        # System text should be in the "system" field of the payload.
        self.assertEqual(captured["payload"]["system"], "You are helpful.")
        # Conversation should only contain non-system messages.
        for msg in captured["payload"]["messages"]:
            self.assertNotEqual(msg["role"], "system")

    def test_anthropic_tool_use_response_parsed(self) -> None:
        """Verify that tool_use content blocks are parsed into ToolCall objects."""

        def fake_http_json(url, method, headers, payload=None, timeout_sec=90):  # type: ignore[no-untyped-def]
            return {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_123",
                        "name": "read_file",
                        "input": {"path": "foo.txt"},
                    }
                ],
                "stop_reason": "tool_use",
            }

        with patch("agent.model._http_stream_sse", mock_anthropic_stream(fake_http_json)):
            model = AnthropicModel(model="m", api_key="k")
            conv = model.create_conversation("sys", "usr")
            turn = model.complete(conv)
        self.assertEqual(len(turn.tool_calls), 1)
        self.assertEqual(turn.tool_calls[0].name, "read_file")
        self.assertEqual(turn.tool_calls[0].arguments, {"path": "foo.txt"})
        self.assertEqual(turn.stop_reason, "tool_use")

    # ------------------------------------------------------------------ #
    # 23. OpenAI without reasoning_effort omits reasoning key
    # ------------------------------------------------------------------ #
    def test_openai_no_reasoning_effort_omits_field(self) -> None:
        captured: dict = {}

        def fake_http_json(url, method, headers, payload=None, timeout_sec=90):  # type: ignore[no-untyped-def]
            captured["payload"] = payload
            return {
                "choices": [
                    {
                        "message": {"content": "ok", "tool_calls": None},
                        "finish_reason": "stop",
                    }
                ]
            }

        with patch("agent.model._http_stream_sse", mock_openai_stream(fake_http_json)):
            model = OpenAICompatibleModel(model="m", api_key="k", reasoning_effort=None)
            conv = model.create_conversation("sys", "usr")
            model.complete(conv)
        self.assertNotIn("reasoning_effort", captured["payload"])

    # ------------------------------------------------------------------ #
    # 24. Anthropic with invalid effort omits thinking key
    # ------------------------------------------------------------------ #
    def test_anthropic_invalid_effort_omits_thinking(self) -> None:
        captured: dict = {}

        def fake_http_json(url, method, headers, payload=None, timeout_sec=90):  # type: ignore[no-untyped-def]
            captured["payload"] = payload
            return {
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
            }

        with patch("agent.model._http_stream_sse", mock_anthropic_stream(fake_http_json)):
            model = AnthropicModel(model="m", api_key="k", reasoning_effort="invalid")
            conv = model.create_conversation("sys", "usr")
            model.complete(conv)
        self.assertNotIn("thinking", captured["payload"])

    # ------------------------------------------------------------------ #
    # 25. OpenAI tool call response parsed correctly
    # ------------------------------------------------------------------ #
    def test_openai_tool_call_response_parsed(self) -> None:
        def fake_http_json(url, method, headers, payload=None, timeout_sec=90):  # type: ignore[no-untyped-def]
            return {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_abc",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": '{"path": "test.py"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }

        with patch("agent.model._http_stream_sse", mock_openai_stream(fake_http_json)):
            model = OpenAICompatibleModel(model="m", api_key="k")
            conv = model.create_conversation("sys", "usr")
            turn = model.complete(conv)
        self.assertEqual(len(turn.tool_calls), 1)
        self.assertEqual(turn.tool_calls[0].id, "call_abc")
        self.assertEqual(turn.tool_calls[0].name, "read_file")
        self.assertEqual(turn.tool_calls[0].arguments, {"path": "test.py"})
        self.assertIsNone(turn.text)

    # ------------------------------------------------------------------ #
    # 26. OpenAI payload includes tools array
    # ------------------------------------------------------------------ #
    def test_openai_payload_includes_tools(self) -> None:
        captured: dict = {}

        def fake_http_json(url, method, headers, payload=None, timeout_sec=90):  # type: ignore[no-untyped-def]
            captured["payload"] = payload
            return {
                "choices": [
                    {
                        "message": {"content": "ok", "tool_calls": None},
                        "finish_reason": "stop",
                    }
                ]
            }

        with patch("agent.model._http_stream_sse", mock_openai_stream(fake_http_json)):
            model = OpenAICompatibleModel(model="m", api_key="k")
            conv = model.create_conversation("sys", "usr")
            model.complete(conv)
        self.assertIn("tools", captured["payload"])
        tools = captured["payload"]["tools"]
        self.assertIsInstance(tools, list)
        self.assertTrue(len(tools) > 0)
        # Each tool should have the OpenAI format
        self.assertEqual(tools[0]["type"], "function")
        self.assertIn("name", tools[0]["function"])

    # ------------------------------------------------------------------ #
    # 27. Anthropic payload includes tools array
    # ------------------------------------------------------------------ #
    def test_anthropic_payload_includes_tools(self) -> None:
        captured: dict = {}

        def fake_http_json(url, method, headers, payload=None, timeout_sec=90):  # type: ignore[no-untyped-def]
            captured["payload"] = payload
            return {
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
            }

        with patch("agent.model._http_stream_sse", mock_anthropic_stream(fake_http_json)):
            model = AnthropicModel(model="m", api_key="k")
            conv = model.create_conversation("sys", "usr")
            model.complete(conv)
        self.assertIn("tools", captured["payload"])
        tools = captured["payload"]["tools"]
        self.assertIsInstance(tools, list)
        self.assertTrue(len(tools) > 0)
        # Each tool should have the Anthropic format
        self.assertIn("name", tools[0])
        self.assertIn("input_schema", tools[0])


class OpenAIEdgeCaseTests(unittest.TestCase):
    """Edge cases for OpenAICompatibleModel."""

    # ------------------------------------------------------------------ #
    # 28. Broken JSON in tool call arguments → empty dict
    # ------------------------------------------------------------------ #
    def test_openai_broken_json_arguments_yields_empty_dict(self) -> None:
        def fake_http_json(url, method, headers, payload=None, timeout_sec=90):
            return {
                "choices": [{
                    "message": {
                        "content": None,
                        "tool_calls": [{
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": "{broken json!!!",
                            },
                        }],
                    },
                    "finish_reason": "tool_calls",
                }]
            }

        with patch("agent.model._http_stream_sse", mock_openai_stream(fake_http_json)):
            model = OpenAICompatibleModel(model="m", api_key="k")
            conv = model.create_conversation("sys", "usr")
            turn = model.complete(conv)
        self.assertEqual(len(turn.tool_calls), 1)
        self.assertEqual(turn.tool_calls[0].arguments, {})

    # ------------------------------------------------------------------ #
    # 29. Non-dict parsed arguments → empty dict
    # ------------------------------------------------------------------ #
    def test_openai_non_dict_parsed_arguments_yields_empty_dict(self) -> None:
        def fake_http_json(url, method, headers, payload=None, timeout_sec=90):
            return {
                "choices": [{
                    "message": {
                        "content": None,
                        "tool_calls": [{
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "think",
                                "arguments": '"just a string"',
                            },
                        }],
                    },
                    "finish_reason": "tool_calls",
                }]
            }

        with patch("agent.model._http_stream_sse", mock_openai_stream(fake_http_json)):
            model = OpenAICompatibleModel(model="m", api_key="k")
            conv = model.create_conversation("sys", "usr")
            turn = model.complete(conv)
        self.assertEqual(turn.tool_calls[0].arguments, {})

    # ------------------------------------------------------------------ #
    # 30. Whitespace-only text → None
    # ------------------------------------------------------------------ #
    def test_openai_whitespace_text_is_none(self) -> None:
        def fake_http_json(url, method, headers, payload=None, timeout_sec=90):
            return {
                "choices": [{
                    "message": {"content": "   \n  ", "tool_calls": None},
                    "finish_reason": "stop",
                }]
            }

        with patch("agent.model._http_stream_sse", mock_openai_stream(fake_http_json)):
            model = OpenAICompatibleModel(model="m", api_key="k")
            conv = model.create_conversation("sys", "usr")
            turn = model.complete(conv)
        self.assertIsNone(turn.text)

    # ------------------------------------------------------------------ #
    # 31. Tool call with missing fields → defaults
    # ------------------------------------------------------------------ #
    def test_openai_tool_call_missing_fields_defaults(self) -> None:
        def fake_http_json(url, method, headers, payload=None, timeout_sec=90):
            return {
                "choices": [{
                    "message": {
                        "content": None,
                        "tool_calls": [{"function": {}}],
                    },
                    "finish_reason": "tool_calls",
                }]
            }

        with patch("agent.model._http_stream_sse", mock_openai_stream(fake_http_json)):
            model = OpenAICompatibleModel(model="m", api_key="k")
            conv = model.create_conversation("sys", "usr")
            turn = model.complete(conv)
        self.assertEqual(len(turn.tool_calls), 1)
        self.assertEqual(turn.tool_calls[0].id, "")
        self.assertEqual(turn.tool_calls[0].name, "")
        self.assertEqual(turn.tool_calls[0].arguments, {})

    # ------------------------------------------------------------------ #
    # 32. append_assistant_turn increments turn_count
    # ------------------------------------------------------------------ #
    def test_openai_append_assistant_turn_increments_turn_count(self) -> None:
        model = OpenAICompatibleModel(model="m", api_key="k")
        conv = model.create_conversation("sys", "usr")
        self.assertEqual(conv.turn_count, 0)
        turn = ModelTurn(text="hello", stop_reason="stop", raw_response={"role": "assistant", "content": "hello"})
        model.append_assistant_turn(conv, turn)
        self.assertEqual(conv.turn_count, 1)

    # ------------------------------------------------------------------ #
    # 33. append_tool_results adds correct format
    # ------------------------------------------------------------------ #
    def test_openai_append_tool_results_format(self) -> None:
        from agent.model import ToolResult
        model = OpenAICompatibleModel(model="m", api_key="k")
        conv = model.create_conversation("sys", "usr")
        initial_count = len(conv._provider_messages)
        results = [
            ToolResult(tool_call_id="call_1", name="read_file", content="file contents"),
            ToolResult(tool_call_id="call_2", name="think", content="noted"),
        ]
        model.append_tool_results(conv, results)
        self.assertEqual(len(conv._provider_messages), initial_count + 2)
        msg1 = conv._provider_messages[-2]
        self.assertEqual(msg1["role"], "tool")
        self.assertEqual(msg1["tool_call_id"], "call_1")
        self.assertEqual(msg1["name"], "read_file")
        self.assertEqual(msg1["content"], "file contents")

    # ------------------------------------------------------------------ #
    # 34. extra_headers are sent in request
    # ------------------------------------------------------------------ #
    def test_openai_extra_headers_included(self) -> None:
        captured: dict = {}

        def fake_http_json(url, method, headers, payload=None, timeout_sec=90):
            captured["headers"] = headers
            return {
                "choices": [{
                    "message": {"content": "ok", "tool_calls": None},
                    "finish_reason": "stop",
                }]
            }

        with patch("agent.model._http_stream_sse", mock_openai_stream(fake_http_json)):
            model = OpenAICompatibleModel(
                model="m", api_key="k",
                extra_headers={"X-Custom": "value123"},
            )
            conv = model.create_conversation("sys", "usr")
            model.complete(conv)
        self.assertEqual(captured["headers"]["X-Custom"], "value123")

    # ------------------------------------------------------------------ #
    # 35. Multiple tool calls in single turn
    # ------------------------------------------------------------------ #
    def test_openai_multiple_tool_calls_in_turn(self) -> None:
        def fake_http_json(url, method, headers, payload=None, timeout_sec=90):
            return {
                "choices": [{
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_a",
                                "type": "function",
                                "function": {"name": "read_file", "arguments": '{"path": "a.txt"}'},
                            },
                            {
                                "id": "call_b",
                                "type": "function",
                                "function": {"name": "read_file", "arguments": '{"path": "b.txt"}'},
                            },
                        ],
                    },
                    "finish_reason": "tool_calls",
                }]
            }

        with patch("agent.model._http_stream_sse", mock_openai_stream(fake_http_json)):
            model = OpenAICompatibleModel(model="m", api_key="k")
            conv = model.create_conversation("sys", "usr")
            turn = model.complete(conv)
        self.assertEqual(len(turn.tool_calls), 2)
        self.assertEqual(turn.tool_calls[0].id, "call_a")
        self.assertEqual(turn.tool_calls[1].id, "call_b")

    # ------------------------------------------------------------------ #
    # 36. OpenAI create_conversation stores system prompt
    # ------------------------------------------------------------------ #
    def test_openai_create_conversation_stores_system_prompt(self) -> None:
        model = OpenAICompatibleModel(model="m", api_key="k")
        conv = model.create_conversation("You are helpful", "Hello")
        self.assertEqual(conv.system_prompt, "You are helpful")
        self.assertEqual(len(conv._provider_messages), 2)
        self.assertEqual(conv._provider_messages[0]["role"], "system")
        self.assertEqual(conv._provider_messages[1]["role"], "user")

    # ------------------------------------------------------------------ #
    # 37. OpenAI non-retryable ModelError re-raised
    # ------------------------------------------------------------------ #
    def test_openai_non_retryable_error_raised(self) -> None:
        def fake_stream_sse(url, method, headers, payload, first_byte_timeout=10, stream_timeout=120, max_retries=3, on_sse_event=None):
            raise ModelError("HTTP 500 server error")

        with patch("agent.model._http_stream_sse", fake_stream_sse):
            model = OpenAICompatibleModel(model="m", api_key="k", reasoning_effort="high")
            conv = model.create_conversation("sys", "usr")
            with self.assertRaises(ModelError):
                model.complete(conv)


class AnthropicEdgeCaseTests(unittest.TestCase):
    """Edge cases for AnthropicModel."""

    # ------------------------------------------------------------------ #
    # 38. content_blocks not a list → treated as empty
    # ------------------------------------------------------------------ #
    def test_anthropic_non_list_content_blocks(self) -> None:
        def fake_http_json(url, method, headers, payload=None, timeout_sec=90):
            return {
                "content": "not a list",
                "stop_reason": "end_turn",
            }

        with patch("agent.model._http_stream_sse", mock_anthropic_stream(fake_http_json)):
            model = AnthropicModel(model="m", api_key="k")
            conv = model.create_conversation("sys", "usr")
            turn = model.complete(conv)
        self.assertEqual(turn.tool_calls, [])
        self.assertIsNone(turn.text)

    # ------------------------------------------------------------------ #
    # 39. Non-dict content blocks are skipped
    # ------------------------------------------------------------------ #
    def test_anthropic_non_dict_content_blocks_skipped(self) -> None:
        def fake_http_json(url, method, headers, payload=None, timeout_sec=90):
            return {
                "content": [
                    "not a dict",
                    42,
                    {"type": "text", "text": "actual text"},
                ],
                "stop_reason": "end_turn",
            }

        with patch("agent.model._http_stream_sse", mock_anthropic_stream(fake_http_json)):
            model = AnthropicModel(model="m", api_key="k")
            conv = model.create_conversation("sys", "usr")
            turn = model.complete(conv)
        self.assertEqual(turn.text, "actual text")

    # ------------------------------------------------------------------ #
    # 40. Text block with whitespace-only text is skipped
    # ------------------------------------------------------------------ #
    def test_anthropic_whitespace_text_block_skipped(self) -> None:
        def fake_http_json(url, method, headers, payload=None, timeout_sec=90):
            return {
                "content": [{"type": "text", "text": "   "}],
                "stop_reason": "end_turn",
            }

        with patch("agent.model._http_stream_sse", mock_anthropic_stream(fake_http_json)):
            model = AnthropicModel(model="m", api_key="k")
            conv = model.create_conversation("sys", "usr")
            turn = model.complete(conv)
        self.assertIsNone(turn.text)

    # ------------------------------------------------------------------ #
    # 41. tool_use block with non-dict input → empty dict
    # ------------------------------------------------------------------ #
    def test_anthropic_tool_use_non_dict_input(self) -> None:
        def fake_http_json(url, method, headers, payload=None, timeout_sec=90):
            return {
                "content": [{
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "think",
                    "input": "not a dict",
                }],
                "stop_reason": "tool_use",
            }

        with patch("agent.model._http_stream_sse", mock_anthropic_stream(fake_http_json)):
            model = AnthropicModel(model="m", api_key="k")
            conv = model.create_conversation("sys", "usr")
            turn = model.complete(conv)
        self.assertEqual(len(turn.tool_calls), 1)
        self.assertEqual(turn.tool_calls[0].arguments, {})

    # ------------------------------------------------------------------ #
    # 42. append_assistant_turn preserves raw_response
    # ------------------------------------------------------------------ #
    def test_anthropic_append_assistant_turn_preserves_raw(self) -> None:
        model = AnthropicModel(model="m", api_key="k")
        conv = model.create_conversation("sys", "usr")
        raw = [{"type": "thinking", "thinking": "hmm", "signature": "sig123"},
               {"type": "text", "text": "answer"}]
        turn = ModelTurn(text="answer", stop_reason="end_turn", raw_response=raw)
        model.append_assistant_turn(conv, turn)
        self.assertEqual(conv.turn_count, 1)
        last_msg = conv._provider_messages[-1]
        self.assertEqual(last_msg["role"], "assistant")
        self.assertIs(last_msg["content"], raw)

    # ------------------------------------------------------------------ #
    # 43. append_tool_results with is_error=True
    # ------------------------------------------------------------------ #
    def test_anthropic_append_tool_results_with_error(self) -> None:
        from agent.model import ToolResult
        model = AnthropicModel(model="m", api_key="k")
        conv = model.create_conversation("sys", "usr")
        results = [
            ToolResult(tool_call_id="toolu_1", name="read_file", content="not found", is_error=True),
        ]
        model.append_tool_results(conv, results)
        last_msg = conv._provider_messages[-1]
        self.assertEqual(last_msg["role"], "user")
        blocks = last_msg["content"]
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["type"], "tool_result")
        self.assertTrue(blocks[0]["is_error"])

    # ------------------------------------------------------------------ #
    # 44. append_tool_results without error omits is_error key
    # ------------------------------------------------------------------ #
    def test_anthropic_append_tool_results_no_error_omits_key(self) -> None:
        from agent.model import ToolResult
        model = AnthropicModel(model="m", api_key="k")
        conv = model.create_conversation("sys", "usr")
        results = [
            ToolResult(tool_call_id="toolu_1", name="think", content="noted"),
        ]
        model.append_tool_results(conv, results)
        last_msg = conv._provider_messages[-1]
        blocks = last_msg["content"]
        self.assertNotIn("is_error", blocks[0])

    # ------------------------------------------------------------------ #
    # 45. Empty system prompt omitted from payload
    # ------------------------------------------------------------------ #
    def test_anthropic_empty_system_prompt_omitted(self) -> None:
        captured: dict = {}

        def fake_http_json(url, method, headers, payload=None, timeout_sec=90):
            captured["payload"] = payload
            return {
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
            }

        with patch("agent.model._http_stream_sse", mock_anthropic_stream(fake_http_json)):
            model = AnthropicModel(model="m", api_key="k")
            conv = model.create_conversation("", "usr")
            model.complete(conv)
        self.assertNotIn("system", captured["payload"])

    # ------------------------------------------------------------------ #
    # 46. Thinking budget for low and high effort
    # ------------------------------------------------------------------ #
    def test_anthropic_thinking_budget_low(self) -> None:
        captured: dict = {}

        def fake_http_json(url, method, headers, payload=None, timeout_sec=90):
            captured["payload"] = payload
            return {
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
            }

        with patch("agent.model._http_stream_sse", mock_anthropic_stream(fake_http_json)):
            model = AnthropicModel(model="m", api_key="k", reasoning_effort="low")
            conv = model.create_conversation("sys", "usr")
            model.complete(conv)
        self.assertEqual(captured["payload"]["thinking"]["budget_tokens"], 1024)

    def test_anthropic_thinking_budget_high(self) -> None:
        captured: dict = {}

        def fake_http_json(url, method, headers, payload=None, timeout_sec=90):
            captured["payload"] = payload
            return {
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
            }

        with patch("agent.model._http_stream_sse", mock_anthropic_stream(fake_http_json)):
            model = AnthropicModel(model="m", api_key="k", reasoning_effort="high")
            conv = model.create_conversation("sys", "usr")
            model.complete(conv)
        self.assertEqual(captured["payload"]["thinking"]["budget_tokens"], 8192)

    # ------------------------------------------------------------------ #
    # 47. Thinking omits temperature entirely
    # ------------------------------------------------------------------ #
    def test_anthropic_thinking_omits_temperature(self) -> None:
        captured: dict = {}

        def fake_http_json(url, method, headers, payload=None, timeout_sec=90):
            captured["payload"] = payload
            return {
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
            }

        with patch("agent.model._http_stream_sse", mock_anthropic_stream(fake_http_json)):
            model = AnthropicModel(model="m", api_key="k", reasoning_effort="medium", temperature=0.5)
            conv = model.create_conversation("sys", "usr")
            model.complete(conv)
        self.assertNotIn("temperature", captured["payload"])

    # ------------------------------------------------------------------ #
    # 48. Non-thinking preserves custom temperature
    # ------------------------------------------------------------------ #
    def test_anthropic_no_thinking_preserves_temperature(self) -> None:
        captured: dict = {}

        def fake_http_json(url, method, headers, payload=None, timeout_sec=90):
            captured["payload"] = payload
            return {
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
            }

        with patch("agent.model._http_stream_sse", mock_anthropic_stream(fake_http_json)):
            model = AnthropicModel(model="m", api_key="k", temperature=0.7)
            conv = model.create_conversation("sys", "usr")
            model.complete(conv)
        self.assertEqual(captured["payload"]["temperature"], 0.7)

    # ------------------------------------------------------------------ #
    # 49. Anthropic non-retryable ModelError re-raised
    # ------------------------------------------------------------------ #
    def test_anthropic_non_retryable_error_raised(self) -> None:
        def fake_stream_sse(url, method, headers, payload, first_byte_timeout=10, stream_timeout=120, max_retries=3, on_sse_event=None):
            raise ModelError("HTTP 500 server error")

        with patch("agent.model._http_stream_sse", fake_stream_sse):
            model = AnthropicModel(model="m", api_key="k", reasoning_effort="low")
            conv = model.create_conversation("sys", "usr")
            with self.assertRaises(ModelError):
                model.complete(conv)

    # ------------------------------------------------------------------ #
    # 50. Anthropic create_conversation does not include system in messages
    # ------------------------------------------------------------------ #
    def test_anthropic_create_conversation_no_system_in_messages(self) -> None:
        model = AnthropicModel(model="m", api_key="k")
        conv = model.create_conversation("System prompt here", "Hello")
        self.assertEqual(conv.system_prompt, "System prompt here")
        for msg in conv._provider_messages:
            self.assertNotEqual(msg.get("role"), "system")

    # ------------------------------------------------------------------ #
    # 51. Multiple text blocks joined
    # ------------------------------------------------------------------ #
    def test_anthropic_multiple_text_blocks_joined(self) -> None:
        def fake_http_json(url, method, headers, payload=None, timeout_sec=90):
            return {
                "content": [
                    {"type": "text", "text": "first part"},
                    {"type": "text", "text": "second part"},
                ],
                "stop_reason": "end_turn",
            }

        with patch("agent.model._http_stream_sse", mock_anthropic_stream(fake_http_json)):
            model = AnthropicModel(model="m", api_key="k")
            conv = model.create_conversation("sys", "usr")
            turn = model.complete(conv)
        self.assertEqual(turn.text, "first part\nsecond part")


class ScriptedAndFallbackTests(unittest.TestCase):
    """Additional tests for ScriptedModel and EchoFallbackModel."""

    # ------------------------------------------------------------------ #
    # 52. ScriptedModel stores system_prompt in conversation
    # ------------------------------------------------------------------ #
    def test_scripted_model_stores_system_prompt(self) -> None:
        from agent.model import ScriptedModel
        model = ScriptedModel(scripted_turns=[])
        conv = model.create_conversation("My system prompt", "Hello")
        self.assertEqual(conv.system_prompt, "My system prompt")

    # ------------------------------------------------------------------ #
    # 53. ScriptedModel append methods are no-ops
    # ------------------------------------------------------------------ #
    def test_scripted_model_append_methods_no_ops(self) -> None:
        from agent.model import ScriptedModel, ToolResult
        model = ScriptedModel(scripted_turns=[])
        conv = model.create_conversation("sys", "usr")
        initial_messages = list(conv._provider_messages)
        turn = ModelTurn(text="x", stop_reason="end_turn")
        model.append_assistant_turn(conv, turn)
        model.append_tool_results(conv, [ToolResult("id", "name", "content")])
        self.assertEqual(conv._provider_messages, initial_messages)

    # ------------------------------------------------------------------ #
    # 54. EchoFallbackModel default note
    # ------------------------------------------------------------------ #
    def test_echo_fallback_default_note(self) -> None:
        from agent.model import EchoFallbackModel
        model = EchoFallbackModel()
        conv = model.create_conversation("sys", "usr")
        turn = model.complete(conv)
        self.assertIn("No provider API keys configured", turn.text)

    # ------------------------------------------------------------------ #
    # 55. Conversation default values
    # ------------------------------------------------------------------ #
    def test_conversation_defaults(self) -> None:
        from agent.model import Conversation
        conv = Conversation()
        self.assertEqual(conv._provider_messages, [])
        self.assertEqual(conv.system_prompt, "")
        self.assertEqual(conv.turn_count, 0)


if __name__ == "__main__":
    unittest.main()

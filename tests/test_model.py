from __future__ import annotations

import unittest
from unittest.mock import patch

from conftest import mock_anthropic_stream, mock_openai_stream
from agent.model import AnthropicModel, ModelError, OpenAICompatibleModel


class ModelPayloadTests(unittest.TestCase):
    def test_openai_payload_includes_reasoning_effort(self) -> None:
        captured: dict = {}

        def fake_http_json(url, method, headers, payload=None, timeout_sec=90):  # type: ignore[no-untyped-def]
            captured["payload"] = payload
            return {
                "choices": [
                    {
                        "message": {
                            "content": "ok",
                            "tool_calls": None,
                        },
                        "finish_reason": "stop",
                    }
                ]
            }

        with patch("agent.model._http_stream_sse", mock_openai_stream(fake_http_json)):
            model = OpenAICompatibleModel(
                model="gpt-5.2",
                api_key="k",
                reasoning_effort="high",
            )
            conv = model.create_conversation("system", "user msg")
            turn = model.complete(conv)
            self.assertEqual(turn.text, "ok")
            self.assertEqual(captured["payload"]["reasoning_effort"], "high")

    def test_anthropic_payload_includes_thinking_budget(self) -> None:
        """Non-Opus-4.6 models use manual thinking with budget_tokens."""
        captured: dict = {}

        def fake_http_json(url, method, headers, payload=None, timeout_sec=90):  # type: ignore[no-untyped-def]
            captured["payload"] = payload
            return {
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
            }

        with patch("agent.model._http_stream_sse", mock_anthropic_stream(fake_http_json)):
            model = AnthropicModel(
                model="claude-sonnet-4-5",
                api_key="k",
                reasoning_effort="medium",
            )
            conv = model.create_conversation("system", "user msg")
            turn = model.complete(conv)
            self.assertEqual(turn.text, "ok")
            self.assertEqual(captured["payload"]["thinking"]["budget_tokens"], 4096)

    def test_anthropic_opus46_uses_adaptive_thinking(self) -> None:
        """Opus 4.6 uses adaptive thinking with output_config effort."""
        captured: dict = {}

        def fake_http_json(url, method, headers, payload=None, timeout_sec=90):  # type: ignore[no-untyped-def]
            captured["payload"] = payload
            return {
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
            }

        with patch("agent.model._http_stream_sse", mock_anthropic_stream(fake_http_json)):
            model = AnthropicModel(
                model="claude-opus-4-6",
                api_key="k",
                reasoning_effort="high",
            )
            conv = model.create_conversation("system", "user msg")
            turn = model.complete(conv)
            self.assertEqual(turn.text, "ok")
            self.assertEqual(captured["payload"]["thinking"], {"type": "adaptive"})
            self.assertEqual(captured["payload"]["output_config"], {"effort": "high"})
            self.assertNotIn("temperature", captured["payload"])

    def test_openai_retries_without_reasoning_when_unsupported(self) -> None:
        calls: list[dict] = []

        def fake_http_json(url, method, headers, payload=None, timeout_sec=90):  # type: ignore[no-untyped-def]
            calls.append(dict(payload or {}))
            if len(calls) == 1:
                raise ModelError(
                    "HTTP 400 calling https://api.openai.com/v1/chat/completions: "
                    "{\"error\":{\"message\":\"Unsupported parameter: 'reasoning_effort'\","
                    "\"param\":\"reasoning_effort\",\"code\":\"unsupported_parameter\"}}"
                )
            return {
                "choices": [
                    {
                        "message": {"content": "ok", "tool_calls": None},
                        "finish_reason": "stop",
                    }
                ]
            }

        with patch("agent.model._http_stream_sse", mock_openai_stream(fake_http_json)):
            model = OpenAICompatibleModel(
                model="gpt-4.1-mini",
                api_key="k",
                reasoning_effort="high",
            )
            conv = model.create_conversation("system", "user msg")
            turn = model.complete(conv)
            self.assertEqual(turn.text, "ok")
            self.assertIn("reasoning_effort", calls[0])
            self.assertNotIn("reasoning_effort", calls[1])

    def test_anthropic_retries_without_thinking_when_unsupported(self) -> None:
        calls: list[dict] = []

        def fake_http_json(url, method, headers, payload=None, timeout_sec=90):  # type: ignore[no-untyped-def]
            calls.append(dict(payload or {}))
            if len(calls) == 1:
                raise ModelError(
                    "HTTP 400 calling https://api.anthropic.com/v1/messages: "
                    "{\"error\":{\"type\":\"invalid_request_error\","
                    "\"message\":\"Unknown parameter: thinking\"}}"
                )
            return {
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
            }

        with patch("agent.model._http_stream_sse", mock_anthropic_stream(fake_http_json)):
            model = AnthropicModel(
                model="claude-sonnet-4-5",
                api_key="k",
                reasoning_effort="medium",
            )
            conv = model.create_conversation("system", "user msg")
            turn = model.complete(conv)
            self.assertEqual(turn.text, "ok")
            self.assertIn("thinking", calls[0])
            self.assertNotIn("thinking", calls[1])


class OllamaPayloadTests(unittest.TestCase):
    def test_ollama_uses_openai_compatible_format(self) -> None:
        captured: dict = {}

        def fake_http_json(url, method, headers, payload=None, timeout_sec=90):  # type: ignore[no-untyped-def]
            captured["url"] = url
            captured["headers"] = headers
            captured["payload"] = payload
            return {
                "choices": [
                    {
                        "message": {
                            "content": "hello from ollama",
                            "tool_calls": None,
                        },
                        "finish_reason": "stop",
                    }
                ]
            }

        with patch("agent.model._http_stream_sse", mock_openai_stream(fake_http_json)):
            model = OpenAICompatibleModel(
                model="llama3.2",
                api_key="ollama",
                base_url="http://localhost:11434/v1",
                strict_tools=False,
            )
            conv = model.create_conversation("system", "user msg")
            turn = model.complete(conv)
            self.assertEqual(turn.text, "hello from ollama")
            self.assertEqual(captured["payload"]["model"], "llama3.2")
            self.assertIn("localhost:11434", captured["url"])
            self.assertEqual(captured["headers"]["Authorization"], "Bearer ollama")

    def test_ollama_no_strict_tools(self) -> None:
        captured: dict = {}

        def fake_http_json(url, method, headers, payload=None, timeout_sec=90):  # type: ignore[no-untyped-def]
            captured["payload"] = payload
            return {
                "choices": [
                    {
                        "message": {
                            "content": "ok",
                            "tool_calls": None,
                        },
                        "finish_reason": "stop",
                    }
                ]
            }

        with patch("agent.model._http_stream_sse", mock_openai_stream(fake_http_json)):
            model = OpenAICompatibleModel(
                model="llama3.2",
                api_key="ollama",
                base_url="http://localhost:11434/v1",
                strict_tools=False,
            )
            conv = model.create_conversation("system", "user msg")
            model.complete(conv)
            tools = captured["payload"]["tools"]
            for tool in tools:
                func = tool.get("function", {})
                self.assertNotIn("strict", func)


if __name__ == "__main__":
    unittest.main()

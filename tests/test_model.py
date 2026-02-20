from __future__ import annotations
import unittest
from unittest.mock import patch

from conftest import mock_anthropic_stream, mock_openai_stream
from agent.model import AnthropicModel, HTTPModelError, ModelError, OpenAICompatibleModel, RateLimitError


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

    def test_openai_payload_includes_thinking_type(self) -> None:
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
                model="glm-5",
                api_key="k",
                thinking_type="enabled",
            )
            conv = model.create_conversation("system", "user msg")
            turn = model.complete(conv)
            self.assertEqual(turn.text, "ok")
            self.assertEqual(captured["payload"]["thinking"], {"type": "enabled"})

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

    def test_openai_reasoning_content_forwards_as_thinking(self) -> None:
        deltas: list[tuple[str, str]] = []

        def fake_stream_sse(url, method, headers, payload, first_byte_timeout=10, stream_timeout=120, max_retries=3, on_sse_event=None):  # type: ignore[no-untyped-def]
            events = [
                ("", {"choices": [{"delta": {"reasoning_content": "thinking text"}, "finish_reason": None}]}),
                ("", {"choices": [{"delta": {"content": "final text"}, "finish_reason": None}]}),
                ("", {"choices": [{"delta": {}, "finish_reason": "stop"}]}),
            ]
            if on_sse_event:
                for event_type, data in events:
                    on_sse_event(event_type, data)
            return events

        with patch("agent.model._http_stream_sse", fake_stream_sse):
            model = OpenAICompatibleModel(
                model="glm-5",
                api_key="k",
                on_content_delta=lambda delta_type, text: deltas.append((delta_type, text)),
            )
            conv = model.create_conversation("system", "user msg")
            turn = model.complete(conv)
            self.assertEqual(turn.text, "final text")
            self.assertIn(("thinking", "thinking text"), deltas)
            self.assertIn(("text", "final text"), deltas)

    def test_openai_finish_reason_rate_limit_raises_rate_limit_error(self) -> None:
        def fake_http_json(url, method, headers, payload=None, timeout_sec=90):  # type: ignore[no-untyped-def]
            return {
                "choices": [
                    {
                        "message": {"content": "partial", "tool_calls": None},
                        "finish_reason": "rate_limit",
                    }
                ]
            }

        with patch("agent.model._http_stream_sse", mock_openai_stream(fake_http_json)):
            model = OpenAICompatibleModel(model="glm-5", api_key="k")
            conv = model.create_conversation("system", "user msg")
            with self.assertRaises(RateLimitError):
                model.complete(conv)

    def test_zai_endpoint_fallback_updates_base_url(self) -> None:
        persisted: list[str] = []
        calls: list[str] = []

        def fake_stream_sse(url, method, headers, payload, first_byte_timeout=10, stream_timeout=120, max_retries=3, on_sse_event=None):  # type: ignore[no-untyped-def]
            calls.append(url)
            if "/api/paas/v4/" in url:
                raise HTTPModelError(
                    f"HTTP 404 calling {url}: not found",
                    status_code=404,
                    body='{"error":{"message":"not found"}}',
                )
            events = [
                ("", {"choices": [{"delta": {"content": "ok"}, "finish_reason": None}]}),
                ("", {"choices": [{"delta": {}, "finish_reason": "stop"}]}),
            ]
            if on_sse_event:
                for event_type, data in events:
                    on_sse_event(event_type, data)
            return events

        with patch("agent.model._http_stream_sse", fake_stream_sse):
            model = OpenAICompatibleModel(
                model="glm-5",
                api_key="k",
                base_url="https://api.z.ai/api/paas/v4",
                provider="zai",
                on_base_url_persist=persisted.append,
            )
            conv = model.create_conversation("system", "user msg")
            turn = model.complete(conv)
            self.assertEqual(turn.text, "ok")
            self.assertEqual(model.base_url, "https://api.z.ai/api/coding/paas/v4")
            self.assertEqual(persisted, ["https://api.z.ai/api/coding/paas/v4"])
            self.assertGreaterEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()

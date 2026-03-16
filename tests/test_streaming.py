"""Tests for the streaming SSE layer: parsing, accumulation, retry logic."""
from __future__ import annotations

import io
import json
import socket
import unittest
from unittest.mock import MagicMock, patch

from agent.model import (
    ModelError,
    _accumulate_anthropic_stream,
    _accumulate_openai_stream,
    _http_stream_sse,
    _read_sse_events,
)


class ReadSSEEventsTests(unittest.TestCase):
    """Test _read_sse_events with raw byte streams."""

    def _make_resp(self, lines: list[str]) -> io.BytesIO:
        raw = "\n".join(lines).encode("utf-8")
        return io.BytesIO(raw)

    def test_openai_text_stream(self) -> None:
        resp = self._make_resp([
            'data: {"choices":[{"delta":{"content":"Hello"},"finish_reason":null}]}',
            '',
            'data: {"choices":[{"delta":{"content":" world"},"finish_reason":null}]}',
            '',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":5}}',
            '',
            'data: [DONE]',
        ])
        events = _read_sse_events(resp)
        self.assertEqual(len(events), 3)
        self.assertEqual(events[0][1]["choices"][0]["delta"]["content"], "Hello")
        self.assertEqual(events[1][1]["choices"][0]["delta"]["content"], " world")
        self.assertEqual(events[2][1]["usage"]["prompt_tokens"], 10)

    def test_anthropic_stream_with_event_types(self) -> None:
        resp = self._make_resp([
            'event: message_start',
            'data: {"type":"message_start","message":{"usage":{"input_tokens":100}}}',
            '',
            'event: content_block_start',
            'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}',
            '',
            'event: content_block_delta',
            'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hi"}}',
            '',
            'event: content_block_stop',
            'data: {"type":"content_block_stop","index":0}',
            '',
            'event: message_delta',
            'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":50}}',
            '',
            'event: message_stop',
            'data: {"type":"message_stop"}',
            '',
        ])
        events = _read_sse_events(resp)
        self.assertEqual(len(events), 6)
        self.assertEqual(events[0][0], "message_start")
        self.assertEqual(events[1][0], "content_block_start")
        self.assertEqual(events[2][0], "content_block_delta")
        self.assertEqual(events[2][1]["delta"]["text"], "Hi")

    def test_anthropic_error_event_raises(self) -> None:
        resp = self._make_resp([
            'event: error',
            'data: {"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}',
            '',
        ])
        with self.assertRaises(ModelError) as ctx:
            _read_sse_events(resp)
        self.assertIn("Overloaded", str(ctx.exception))

    def test_done_terminates_early(self) -> None:
        resp = self._make_resp([
            'data: {"choices":[{"delta":{"content":"a"}}]}',
            '',
            'data: [DONE]',
            'data: {"choices":[{"delta":{"content":"should not appear"}}]}',
            '',
        ])
        events = _read_sse_events(resp)
        self.assertEqual(len(events), 1)


class AccumulateOpenAIStreamTests(unittest.TestCase):
    """Test _accumulate_openai_stream."""

    def test_text_only(self) -> None:
        events = [
            ("", {"choices": [{"delta": {"content": "Hello"}, "finish_reason": None}]}),
            ("", {"choices": [{"delta": {"content": " world"}, "finish_reason": None}]}),
            ("", {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}),
        ]
        result = _accumulate_openai_stream(events)
        msg = result["choices"][0]["message"]
        self.assertEqual(msg["content"], "Hello world")
        self.assertIsNone(msg["tool_calls"])
        self.assertEqual(result["choices"][0]["finish_reason"], "stop")
        self.assertEqual(result["usage"]["prompt_tokens"], 10)

    def test_tool_calls(self) -> None:
        events = [
            ("", {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "read_file", "arguments": '{"pa'}}]}, "finish_reason": None}]}),
            ("", {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'th": "x.py"}'}}]}, "finish_reason": None}]}),
            ("", {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}),
        ]
        result = _accumulate_openai_stream(events)
        msg = result["choices"][0]["message"]
        self.assertIsNone(msg["content"])
        self.assertEqual(len(msg["tool_calls"]), 1)
        tc = msg["tool_calls"][0]
        self.assertEqual(tc["id"], "call_1")
        self.assertEqual(tc["function"]["name"], "read_file")
        self.assertEqual(tc["function"]["arguments"], '{"path": "x.py"}')

    def test_multiple_tool_calls(self) -> None:
        events = [
            ("", {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_a", "function": {"name": "read_file", "arguments": '{"path":"a"}'}}]}, "finish_reason": None}]}),
            ("", {"choices": [{"delta": {"tool_calls": [{"index": 1, "id": "call_b", "function": {"name": "read_file", "arguments": '{"path":"b"}'}}]}, "finish_reason": None}]}),
            ("", {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}),
        ]
        result = _accumulate_openai_stream(events)
        msg = result["choices"][0]["message"]
        self.assertEqual(len(msg["tool_calls"]), 2)
        self.assertEqual(msg["tool_calls"][0]["id"], "call_a")
        self.assertEqual(msg["tool_calls"][1]["id"], "call_b")


class AccumulateAnthropicStreamTests(unittest.TestCase):
    """Test _accumulate_anthropic_stream."""

    def test_text_only(self) -> None:
        events = [
            ("message_start", {"type": "message_start", "message": {"usage": {"input_tokens": 100}}}),
            ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hello"}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": " world"}}),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 50}}),
            ("message_stop", {"type": "message_stop"}),
        ]
        result = _accumulate_anthropic_stream(events)
        self.assertEqual(len(result["content"]), 1)
        self.assertEqual(result["content"][0]["type"], "text")
        self.assertEqual(result["content"][0]["text"], "Hello world")
        self.assertEqual(result["stop_reason"], "end_turn")
        self.assertEqual(result["usage"]["input_tokens"], 100)
        self.assertEqual(result["usage"]["output_tokens"], 50)

    def test_tool_use(self) -> None:
        events = [
            ("message_start", {"type": "message_start", "message": {"usage": {"input_tokens": 50}}}),
            ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "toolu_1", "name": "read_file"}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": '{"path":'}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": ' "test.py"}'}}),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 20}}),
            ("message_stop", {"type": "message_stop"}),
        ]
        result = _accumulate_anthropic_stream(events)
        self.assertEqual(len(result["content"]), 1)
        block = result["content"][0]
        self.assertEqual(block["type"], "tool_use")
        self.assertEqual(block["id"], "toolu_1")
        self.assertEqual(block["name"], "read_file")
        self.assertEqual(block["input"], {"path": "test.py"})

    def test_thinking_block(self) -> None:
        events = [
            ("message_start", {"type": "message_start", "message": {"usage": {"input_tokens": 10}}}),
            ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "Let me think..."}}),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            ("content_block_start", {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "Answer"}}),
            ("content_block_stop", {"type": "content_block_stop", "index": 1}),
            ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 30}}),
            ("message_stop", {"type": "message_stop"}),
        ]
        result = _accumulate_anthropic_stream(events)
        self.assertEqual(len(result["content"]), 2)
        self.assertEqual(result["content"][0]["type"], "thinking")
        self.assertEqual(result["content"][0]["thinking"], "Let me think...")
        self.assertEqual(result["content"][1]["type"], "text")
        self.assertEqual(result["content"][1]["text"], "Answer")


class HttpStreamSSETests(unittest.TestCase):
    """Test _http_stream_sse retry and error handling."""

    def test_retries_on_timeout(self) -> None:
        call_count = 0

        def fake_urlopen(req, timeout=None):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise socket.timeout("timed out")
            # Return a successful response
            data = 'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n'
            resp = MagicMock()
            resp.__iter__ = lambda self: iter(data.encode().split(b"\n"))
            resp.__enter__ = lambda self: self
            resp.__exit__ = lambda self, *a: None
            resp.fp = MagicMock()
            resp.close = MagicMock()
            return resp

        with patch("agent.model.urllib.request.urlopen", fake_urlopen):
            events = _http_stream_sse(
                url="http://test/v1/chat/completions",
                method="POST",
                headers={},
                payload={"model": "test"},
                first_byte_timeout=1,
                max_retries=3,
            )
        self.assertEqual(call_count, 3)
        self.assertTrue(len(events) > 0)

    def test_gives_up_after_max_retries(self) -> None:
        def fake_urlopen(req, timeout=None):
            raise socket.timeout("timed out")

        with patch("agent.model.urllib.request.urlopen", fake_urlopen):
            with self.assertRaises(ModelError) as ctx:
                _http_stream_sse(
                    url="http://test/v1/chat/completions",
                    method="POST",
                    headers={},
                    payload={"model": "test"},
                    first_byte_timeout=1,
                    max_retries=3,
                )
            self.assertIn("Timed out after 3 attempts", str(ctx.exception))

    def test_no_retry_on_http_error(self) -> None:
        """HTTP 400 errors should raise immediately without retrying."""
        call_count = 0

        def fake_urlopen(req, timeout=None):
            nonlocal call_count
            call_count += 1
            import urllib.error
            raise urllib.error.HTTPError(
                url="http://test",
                code=400,
                msg="Bad Request",
                hdrs={},
                fp=io.BytesIO(b'{"error": "bad request"}'),
            )

        with patch("agent.model.urllib.request.urlopen", fake_urlopen):
            with self.assertRaises(ModelError) as ctx:
                _http_stream_sse(
                    url="http://test/v1/chat/completions",
                    method="POST",
                    headers={},
                    payload={"model": "test"},
                    max_retries=3,
                )
            self.assertIn("HTTP 400", str(ctx.exception))
        # Should only be called once — no retries on HTTP errors
        self.assertEqual(call_count, 1)


if __name__ == "__main__":
    unittest.main()

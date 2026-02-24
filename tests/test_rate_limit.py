"""Tests for HTTP 429 rate-limit retry logic in agent.model."""
from __future__ import annotations

import io
import socket
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from agent.config import AgentConfig
from agent.engine import RLMEngine
from agent.model import (
    AnthropicModel,
    ModelError,
    ModelTurn,
    _http_json,
    _http_stream_sse,
    _notify_retry,
    _parse_retry_after,
    _sleep_with_countdown,
)
from agent.tools import WorkspaceTools


# ---------------------------------------------------------------------------
# _parse_retry_after
# ---------------------------------------------------------------------------


class ParseRetryAfterTests(unittest.TestCase):
    """Tests for the _parse_retry_after pure helper."""

    def _make_exc(self, retry_after: str | None) -> urllib.error.HTTPError:
        headers = {}
        if retry_after is not None:
            headers["Retry-After"] = retry_after
        exc = urllib.error.HTTPError(
            url="http://test",
            code=429,
            msg="Too Many Requests",
            hdrs=headers,
            fp=io.BytesIO(b"{}"),
        )
        return exc

    def test_valid_integer_header(self) -> None:
        exc = self._make_exc("10")
        self.assertEqual(_parse_retry_after(exc), 10)

    def test_missing_header_uses_default(self) -> None:
        exc = self._make_exc(None)
        self.assertEqual(_parse_retry_after(exc), 5)

    def test_missing_header_custom_default(self) -> None:
        exc = self._make_exc(None)
        self.assertEqual(_parse_retry_after(exc, default=30), 30)

    def test_clamped_below_floor(self) -> None:
        exc = self._make_exc("0")
        self.assertEqual(_parse_retry_after(exc), 1)

    def test_clamped_above_cap(self) -> None:
        exc = self._make_exc("999")
        self.assertEqual(_parse_retry_after(exc), 120)

    def test_non_integer_uses_default(self) -> None:
        exc = self._make_exc("not-a-number")
        self.assertEqual(_parse_retry_after(exc), 5)

    def test_negative_value_clamped_to_floor(self) -> None:
        exc = self._make_exc("-5")
        self.assertEqual(_parse_retry_after(exc), 1)


# ---------------------------------------------------------------------------
# _notify_retry
# ---------------------------------------------------------------------------


class NotifyRetryTests(unittest.TestCase):
    """Tests for the _notify_retry callback wrapper."""

    def test_calls_callback_with_message(self) -> None:
        cb = MagicMock()
        _notify_retry(cb, "test message")
        cb.assert_called_once_with("test message")

    def test_none_callback_is_noop(self) -> None:
        # Should not raise
        _notify_retry(None, "test message")

    def test_swallows_callback_exception(self) -> None:
        def broken_cb(msg: str) -> None:
            raise RuntimeError("boom")

        # Should not raise
        _notify_retry(broken_cb, "test message")


# ---------------------------------------------------------------------------
# _sleep_with_countdown
# ---------------------------------------------------------------------------


class SleepWithCountdownTests(unittest.TestCase):
    """Tests for the _sleep_with_countdown helper."""

    @patch("agent.model.time.sleep")
    def test_sleeps_correct_number_of_seconds(self, mock_sleep: MagicMock) -> None:
        cb = MagicMock()
        _sleep_with_countdown(seconds=3, attempt=1, max_attempts=5, on_retry=cb)
        self.assertEqual(mock_sleep.call_count, 3)
        mock_sleep.assert_has_calls([call(1), call(1), call(1)])

    @patch("agent.model.time.sleep")
    def test_countdown_messages_descend(self, mock_sleep: MagicMock) -> None:
        cb = MagicMock()
        _sleep_with_countdown(seconds=3, attempt=2, max_attempts=5, on_retry=cb)
        messages = [c.args[0] for c in cb.call_args_list]
        self.assertEqual(len(messages), 3)
        self.assertIn("3s", messages[0])
        self.assertIn("2s", messages[1])
        self.assertIn("1s", messages[2])
        # All messages should include attempt info
        for msg in messages:
            self.assertIn("attempt 2/5", msg)

    @patch("agent.model.time.sleep")
    def test_none_callback_still_sleeps(self, mock_sleep: MagicMock) -> None:
        _sleep_with_countdown(seconds=2, attempt=1, max_attempts=5, on_retry=None)
        self.assertEqual(mock_sleep.call_count, 2)


# ---------------------------------------------------------------------------
# _http_stream_sse — 429 retry logic
# ---------------------------------------------------------------------------


def _make_successful_response() -> MagicMock:
    """Create a mock HTTP response that yields a valid SSE stream."""
    data = 'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n'
    resp = MagicMock()
    resp.__iter__ = lambda self: iter(data.encode().split(b"\n"))
    resp.__enter__ = lambda self: self
    resp.__exit__ = lambda self, *a: None
    resp.fp = MagicMock()
    resp.close = MagicMock()
    return resp


def _make_429_error(retry_after: str | None = "5") -> urllib.error.HTTPError:
    """Create a 429 HTTPError with optional Retry-After header."""
    headers = {}
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(
        url="http://test",
        code=429,
        msg="Too Many Requests",
        hdrs=headers,
        fp=io.BytesIO(b'{"type":"error","error":{"type":"rate_limit_error","message":"rate limited"}}'),
    )


class HttpStreamSSE429Tests(unittest.TestCase):
    """Tests for 429 retry logic in _http_stream_sse."""

    @patch("agent.model.time.sleep")
    def test_429_retries_and_succeeds(self, mock_sleep: MagicMock) -> None:
        """First call returns 429, second succeeds."""
        call_count = 0

        def fake_urlopen(req, timeout=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise _make_429_error("2")
            return _make_successful_response()

        with patch("agent.model.urllib.request.urlopen", fake_urlopen):
            events = _http_stream_sse(
                url="http://test/v1/chat/completions",
                method="POST",
                headers={},
                payload={"model": "test"},
                max_rate_limit_retries=5,
            )
        self.assertEqual(call_count, 2)
        self.assertTrue(len(events) > 0)

    @patch("agent.model.time.sleep")
    def test_429_exhausts_retries_raises_model_error(self, mock_sleep: MagicMock) -> None:
        """All attempts return 429 → ModelError with retry count."""

        def fake_urlopen(req, timeout=None):
            raise _make_429_error("1")

        with patch("agent.model.urllib.request.urlopen", fake_urlopen):
            with self.assertRaises(ModelError) as ctx:
                _http_stream_sse(
                    url="http://test/v1/chat/completions",
                    method="POST",
                    headers={},
                    payload={"model": "test"},
                    max_rate_limit_retries=3,
                )
            msg = str(ctx.exception)
            self.assertIn("429", msg)
            self.assertIn("3", msg)  # retry count in message

    @patch("agent.model.time.sleep")
    def test_429_on_retry_callback_invoked_with_countdown(self, mock_sleep: MagicMock) -> None:
        """on_retry callback receives countdown messages during 429 wait."""
        call_count = 0
        retry_messages: list[str] = []

        def fake_urlopen(req, timeout=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise _make_429_error("2")
            return _make_successful_response()

        def on_retry_cb(msg: str) -> None:
            retry_messages.append(msg)

        with patch("agent.model.urllib.request.urlopen", fake_urlopen):
            _http_stream_sse(
                url="http://test/v1/chat/completions",
                method="POST",
                headers={},
                payload={"model": "test"},
                on_retry=on_retry_cb,
                max_rate_limit_retries=5,
            )
        # Should have countdown messages (2s, 1s)
        self.assertEqual(len(retry_messages), 2)
        self.assertIn("2s", retry_messages[0])
        self.assertIn("1s", retry_messages[1])

    def test_non_429_http_error_raises_immediately(self) -> None:
        """HTTP 400 errors should raise immediately without retrying."""
        call_count = 0

        def fake_urlopen(req, timeout=None):
            nonlocal call_count
            call_count += 1
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
                    max_rate_limit_retries=5,
                )
            self.assertIn("HTTP 400", str(ctx.exception))
        self.assertEqual(call_count, 1)

    @patch("agent.model.time.sleep")
    def test_connection_retry_and_429_retry_are_independent(self, mock_sleep: MagicMock) -> None:
        """Connection retries exhaust independently, then 429 retry kicks in."""
        call_count = 0

        def fake_urlopen(req, timeout=None):
            nonlocal call_count
            call_count += 1
            # First 2 calls: connection timeout (uses connection retry budget)
            if call_count <= 2:
                raise socket.timeout("timed out")
            # Third call succeeds on connection but gets 429
            if call_count == 3:
                raise _make_429_error("1")
            # Fourth call succeeds
            return _make_successful_response()

        with patch("agent.model.urllib.request.urlopen", fake_urlopen):
            events = _http_stream_sse(
                url="http://test/v1/chat/completions",
                method="POST",
                headers={},
                payload={"model": "test"},
                max_retries=3,
                max_rate_limit_retries=5,
            )
        self.assertEqual(call_count, 4)
        self.assertTrue(len(events) > 0)

    @patch("agent.model.time.sleep")
    def test_429_without_retry_after_uses_fallback(self, mock_sleep: MagicMock) -> None:
        """429 without Retry-After header falls back to 5-second wait."""
        call_count = 0

        def fake_urlopen(req, timeout=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise _make_429_error(None)  # No Retry-After header
            return _make_successful_response()

        with patch("agent.model.urllib.request.urlopen", fake_urlopen):
            _http_stream_sse(
                url="http://test/v1/chat/completions",
                method="POST",
                headers={},
                payload={"model": "test"},
                max_rate_limit_retries=5,
            )
        # Default fallback is 5 seconds → 5 sleep calls
        self.assertEqual(mock_sleep.call_count, 5)


# ---------------------------------------------------------------------------
# _http_json — 429 retry logic
# ---------------------------------------------------------------------------


class HttpJson429Tests(unittest.TestCase):
    """Tests for 429 retry logic in _http_json."""

    @patch("agent.model.time.sleep")
    def test_429_retries_silently_and_succeeds(self, mock_sleep: MagicMock) -> None:
        """_http_json retries on 429 without any callback."""
        call_count = 0

        def fake_urlopen(req, timeout=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise _make_429_error("1")
            resp = MagicMock()
            resp.read.return_value = b'{"data": "ok"}'
            resp.__enter__ = lambda self: self
            resp.__exit__ = lambda self, *a: None
            return resp

        with patch("agent.model.urllib.request.urlopen", fake_urlopen):
            result = _http_json(
                url="http://test/v1/models",
                method="GET",
                headers={},
                max_rate_limit_retries=5,
            )
        self.assertEqual(call_count, 2)
        self.assertEqual(result["data"], "ok")

    @patch("agent.model.time.sleep")
    def test_429_exhausts_retries_raises_model_error(self, mock_sleep: MagicMock) -> None:
        def fake_urlopen(req, timeout=None):
            raise _make_429_error("1")

        with patch("agent.model.urllib.request.urlopen", fake_urlopen):
            with self.assertRaises(ModelError) as ctx:
                _http_json(
                    url="http://test/v1/models",
                    method="GET",
                    headers={},
                    max_rate_limit_retries=3,
                )
            msg = str(ctx.exception)
            self.assertIn("429", msg)
            self.assertIn("3", msg)


# ---------------------------------------------------------------------------
# Engine integration — on_retry wiring
# ---------------------------------------------------------------------------


class EngineOnRetryWiringTests(unittest.TestCase):
    """Verify the engine sets/clears model.on_retry and messages reach on_event."""

    @patch("agent.model.time.sleep")
    def test_engine_on_event_receives_retry_messages(self, mock_sleep: MagicMock) -> None:
        """A 429 during model.complete() should surface retry messages via on_event."""
        call_count = 0

        def fake_urlopen(req, timeout=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise _make_429_error("1")
            # Second call: return a valid Anthropic SSE response
            data = (
                'event: message_start\ndata: {"type":"message_start","message":{"usage":{"input_tokens":10}}}\n\n'
                'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n'
                'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"done"}}\n\n'
                'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n'
                'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":5}}\n\n'
                'event: message_stop\ndata: {"type":"message_stop"}\n\n'
            )
            resp = MagicMock()
            resp.__iter__ = lambda self: iter(data.encode().split(b"\n"))
            resp.__enter__ = lambda self: self
            resp.__exit__ = lambda self, *a: None
            resp.fp = MagicMock()
            resp.close = MagicMock()
            return resp

        events_received: list[str] = []

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = AgentConfig(workspace=root, max_depth=0, max_steps_per_call=1)
            tools = WorkspaceTools(root=root)
            model = AnthropicModel(model="test-model", api_key="test-key")
            engine = RLMEngine(model=model, tools=tools, config=cfg)

            with patch("agent.model.urllib.request.urlopen", fake_urlopen):
                engine.solve(
                    "test objective",
                    on_event=lambda msg: events_received.append(msg),
                )

        # The retry message should appear in the event stream with depth/step prefix
        retry_events = [e for e in events_received if "Rate limited" in e]
        self.assertTrue(len(retry_events) > 0, f"Expected retry events, got: {events_received}")
        self.assertIn("1s", retry_events[0])
        self.assertRegex(retry_events[0], r"\[d\d+/s\d+\]")

        # on_retry should be cleared after complete() returns
        self.assertIsNone(model.on_retry)


if __name__ == "__main__":
    unittest.main()

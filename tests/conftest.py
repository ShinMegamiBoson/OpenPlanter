"""Shared test helpers and fixtures for the OpenPlanter agent test suite."""

from __future__ import annotations

from typing import Any

from agent.model import ToolCall


def _tc(name: str, **kwargs) -> ToolCall:
    """Shorthand to create a ToolCall with a dummy id."""
    return ToolCall(id=f"call_{name}", name=name, arguments=kwargs)


def _openai_dict_to_events(
    resp: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    """Convert a non-streaming OpenAI response dict into SSE-style events."""
    events: list[tuple[str, dict[str, Any]]] = []
    choice = resp.get("choices", [{}])[0] if resp.get("choices") else {}
    message = choice.get("message", {})
    finish_reason = choice.get("finish_reason")

    # Content delta
    content = message.get("content")
    if content:
        events.append(("", {
            "choices": [{"delta": {"content": content}, "finish_reason": None}],
        }))

    # Tool call deltas
    tool_calls = message.get("tool_calls")
    if tool_calls and isinstance(tool_calls, list):
        for i, tc in enumerate(tool_calls):
            func = tc.get("function", {})
            events.append(("", {
                "choices": [{
                    "delta": {
                        "tool_calls": [{
                            "index": i,
                            "id": tc.get("id", ""),
                            "function": {
                                "name": func.get("name", ""),
                                "arguments": func.get("arguments", "{}"),
                            },
                        }],
                    },
                    "finish_reason": None,
                }],
            }))

    # Final chunk with finish_reason + usage
    final: dict[str, Any] = {
        "choices": [{"delta": {}, "finish_reason": finish_reason}],
    }
    if "usage" in resp:
        final["usage"] = resp["usage"]
    events.append(("", final))
    return events


def _anthropic_dict_to_events(
    resp: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    """Convert a non-streaming Anthropic response dict into SSE-style events."""
    events: list[tuple[str, dict[str, Any]]] = []

    # message_start
    usage = resp.get("usage", {})
    events.append(("message_start", {
        "type": "message_start",
        "message": {"usage": {"input_tokens": usage.get("input_tokens", 0)}},
    }))

    # Content blocks
    content = resp.get("content", [])
    if isinstance(content, list):
        for i, block in enumerate(content):
            if not isinstance(block, dict):
                continue
            btype = block.get("type", "text")

            if btype == "text":
                events.append(("content_block_start", {
                    "type": "content_block_start",
                    "index": i,
                    "content_block": {"type": "text", "text": ""},
                }))
                text = block.get("text", "")
                if text:
                    events.append(("content_block_delta", {
                        "type": "content_block_delta",
                        "index": i,
                        "delta": {"type": "text_delta", "text": text},
                    }))
                events.append(("content_block_stop", {
                    "type": "content_block_stop",
                    "index": i,
                }))

            elif btype == "tool_use":
                import json as _json
                events.append(("content_block_start", {
                    "type": "content_block_start",
                    "index": i,
                    "content_block": {
                        "type": "tool_use",
                        "id": block.get("id", ""),
                        "name": block.get("name", ""),
                    },
                }))
                inp = block.get("input", {})
                if inp and isinstance(inp, dict):
                    events.append(("content_block_delta", {
                        "type": "content_block_delta",
                        "index": i,
                        "delta": {
                            "type": "input_json_delta",
                            "partial_json": _json.dumps(inp),
                        },
                    }))
                events.append(("content_block_stop", {
                    "type": "content_block_stop",
                    "index": i,
                }))

            elif btype == "thinking":
                events.append(("content_block_start", {
                    "type": "content_block_start",
                    "index": i,
                    "content_block": {"type": "thinking", "thinking": ""},
                }))
                thinking_text = block.get("thinking", "")
                if thinking_text:
                    events.append(("content_block_delta", {
                        "type": "content_block_delta",
                        "index": i,
                        "delta": {"type": "thinking_delta", "thinking": thinking_text},
                    }))
                # Emit signature_delta (required by API for round-tripping thinking blocks)
                signature = block.get("signature", "fake-sig-for-test")
                events.append(("content_block_delta", {
                    "type": "content_block_delta",
                    "index": i,
                    "delta": {"type": "signature_delta", "signature": signature},
                }))
                events.append(("content_block_stop", {
                    "type": "content_block_stop",
                    "index": i,
                }))

    # message_delta
    events.append(("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": resp.get("stop_reason", "")},
        "usage": {"output_tokens": usage.get("output_tokens", 0)},
    }))

    # message_stop
    events.append(("message_stop", {"type": "message_stop"}))
    return events


def mock_openai_stream(fake_http_json_fn):
    """Wrap a _http_json-style mock into a _http_stream_sse-style mock for OpenAI."""
    def wrapper(url, method, headers, payload, first_byte_timeout=10, stream_timeout=120, max_retries=3, on_sse_event=None):
        result = fake_http_json_fn(url, method, headers, payload=payload, timeout_sec=stream_timeout)
        return _openai_dict_to_events(result)
    return wrapper


def mock_anthropic_stream(fake_http_json_fn):
    """Wrap a _http_json-style mock into a _http_stream_sse-style mock for Anthropic."""
    def wrapper(url, method, headers, payload, first_byte_timeout=10, stream_timeout=120, max_retries=3, on_sse_event=None):
        result = fake_http_json_fn(url, method, headers, payload=payload, timeout_sec=stream_timeout)
        return _anthropic_dict_to_events(result)
    return wrapper

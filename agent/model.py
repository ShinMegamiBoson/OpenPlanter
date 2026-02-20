from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from .tool_defs import to_anthropic_tools, to_openai_tools


class ModelError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Core data types
# ---------------------------------------------------------------------------

@dataclass
class ToolCall:
    """A single tool invocation requested by the model."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """Result of executing a tool call."""
    tool_call_id: str
    name: str
    content: str
    is_error: bool = False


@dataclass
class ModelTurn:
    """One assistant turn from the model."""
    tool_calls: list[ToolCall] = field(default_factory=list)
    text: str | None = None
    stop_reason: str = ""
    raw_response: Any = None
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class Conversation:
    """Opaque conversation state owned by the model layer."""
    _provider_messages: list[Any] = field(default_factory=list)
    system_prompt: str = ""
    turn_count: int = 0
    stop_sequences: list[str] = field(default_factory=list)

    def get_messages(self) -> list[Any]:
        """Return a shallow copy of the provider messages list."""
        return list(self._provider_messages)


# ---------------------------------------------------------------------------
# BaseModel protocol
# ---------------------------------------------------------------------------

class BaseModel(Protocol):
    def create_conversation(self, system_prompt: str, initial_user_message: str) -> Conversation: ...
    def complete(self, conversation: Conversation) -> ModelTurn: ...
    def append_assistant_turn(self, conversation: Conversation, turn: ModelTurn) -> None: ...
    def append_tool_results(self, conversation: Conversation, results: list[ToolResult]) -> None: ...


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _extract_content(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            maybe_text = part.get("text")
            if isinstance(maybe_text, str):
                text_parts.append(maybe_text)
                continue
            if part.get("type") == "text":
                nested = part.get("text")
                if isinstance(nested, str):
                    text_parts.append(nested)
        return "\n".join(text_parts)
    return ""


def _http_json(
    url: str,
    method: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None = None,
    timeout_sec: int = 90,
) -> dict[str, Any]:
    req = urllib.request.Request(
        url=url,
        data=(json.dumps(payload).encode("utf-8") if payload is not None else None),
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:  # pragma: no cover - network path
        body = exc.read().decode("utf-8", errors="replace")
        raise ModelError(f"HTTP {exc.code} calling {url}: {body}") from exc
    except urllib.error.URLError as exc:  # pragma: no cover - network path
        raise ModelError(f"Connection error calling {url}: {exc}") from exc
    except OSError as exc:  # pragma: no cover - bare socket.timeout, etc.
        raise ModelError(f"Network error calling {url}: {exc}") from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ModelError(f"Non-JSON response from {url}: {raw[:500]}") from exc
    if not isinstance(parsed, dict):
        raise ModelError(f"Unexpected non-object JSON from {url}: {type(parsed)!r}")
    return parsed


def _extend_socket_timeout(resp: Any, timeout: float) -> None:
    """Best-effort extension of the underlying socket timeout after first byte."""
    try:
        resp.fp.raw._sock.settimeout(timeout)
    except (AttributeError, OSError):
        pass


def _read_sse_events(
    resp: Any,
    on_sse_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """Read SSE lines from an HTTP response, returning (event_type, data_dict) pairs."""
    events: list[tuple[str, dict[str, Any]]] = []
    current_event = ""
    current_data_lines: list[str] = []

    for raw_line in resp:
        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")

        if line.startswith("event:"):
            current_event = line[len("event:"):].strip()
            continue

        if line.startswith("data:"):
            data_str = line[len("data:"):].strip()
            if data_str == "[DONE]":
                break
            current_data_lines.append(data_str)
            continue

        # Empty line = end of SSE message
        if not line:
            if current_data_lines:
                joined = "\n".join(current_data_lines)
                try:
                    data_dict = json.loads(joined)
                except json.JSONDecodeError:
                    data_dict = {"_raw": joined}
                if isinstance(data_dict, dict):
                    # Check for Anthropic error events
                    if data_dict.get("type") == "error":
                        err_msg = data_dict.get("error", {}).get("message", str(data_dict))
                        raise ModelError(f"Stream error: {err_msg}")
                    events.append((current_event, data_dict))
                    if on_sse_event:
                        try:
                            on_sse_event(current_event, data_dict)
                        except Exception:
                            pass
                current_data_lines = []
                current_event = ""
            continue

    # Flush any remaining data (some servers don't end with empty line)
    if current_data_lines:
        joined = "\n".join(current_data_lines)
        try:
            data_dict = json.loads(joined)
        except json.JSONDecodeError:
            data_dict = {"_raw": joined}
        if isinstance(data_dict, dict):
            if data_dict.get("type") == "error":
                err_msg = data_dict.get("error", {}).get("message", str(data_dict))
                raise ModelError(f"Stream error: {err_msg}")
            events.append((current_event, data_dict))
            if on_sse_event:
                try:
                    on_sse_event(current_event, data_dict)
                except Exception:
                    pass

    return events


def _http_stream_sse(
    url: str,
    method: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    first_byte_timeout: float = 10,
    stream_timeout: float = 120,
    max_retries: int = 3,
    on_sse_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """Stream an SSE endpoint with first-byte timeout and retry logic."""
    data = json.dumps(payload).encode("utf-8")

    last_exc: Exception | None = None
    for _attempt in range(max_retries):
        req = urllib.request.Request(url=url, data=data, headers=headers, method=method)
        try:
            resp = urllib.request.urlopen(req, timeout=first_byte_timeout)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ModelError(f"HTTP {exc.code} calling {url}: {body}") from exc
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            # Timeout or connection error — retry
            last_exc = exc
            continue

        # First byte received — extend timeout for the rest of the stream
        _extend_socket_timeout(resp, stream_timeout)
        try:
            return _read_sse_events(resp, on_sse_event=on_sse_event)
        finally:
            resp.close()

    raise ModelError(
        f"Timed out after {max_retries} attempts calling {url}: {last_exc}"
    )


def _accumulate_openai_stream(
    events: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    """Reconstruct an OpenAI non-streaming response dict from SSE delta chunks."""
    text_parts: list[str] = []
    tool_calls_by_index: dict[int, dict[str, Any]] = {}
    finish_reason = ""
    usage: dict[str, Any] = {}

    for _event_type, chunk in events:
        # Usage may appear in a dedicated chunk or alongside the last delta
        if chunk.get("usage"):
            usage = chunk["usage"]

        choices = chunk.get("choices")
        if not choices:
            continue
        choice = choices[0]
        fr = choice.get("finish_reason")
        if fr:
            finish_reason = fr

        delta = choice.get("delta", {})
        if not delta:
            continue

        # Text content
        content = delta.get("content")
        if content:
            text_parts.append(content)

        # Tool calls (streamed incrementally)
        tc_deltas = delta.get("tool_calls")
        if tc_deltas:
            for tc_delta in tc_deltas:
                idx = tc_delta.get("index", 0)
                if idx not in tool_calls_by_index:
                    tool_calls_by_index[idx] = {
                        "id": tc_delta.get("id", ""),
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    }
                tc = tool_calls_by_index[idx]
                if tc_delta.get("id"):
                    tc["id"] = tc_delta["id"]
                func = tc_delta.get("function", {})
                if func.get("name"):
                    tc["function"]["name"] = func["name"]
                if func.get("arguments"):
                    tc["function"]["arguments"] += func["arguments"]

    # Build the final message
    message: dict[str, Any] = {
        "role": "assistant",
        "content": "".join(text_parts) if text_parts else None,
    }
    if tool_calls_by_index:
        message["tool_calls"] = [
            tool_calls_by_index[i] for i in sorted(tool_calls_by_index)
        ]
    else:
        message["tool_calls"] = None

    result: dict[str, Any] = {
        "choices": [{"message": message, "finish_reason": finish_reason}],
    }
    if usage:
        result["usage"] = usage
    return result


def _accumulate_anthropic_stream(
    events: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    """Reconstruct an Anthropic non-streaming response dict from SSE events."""
    content_blocks: list[dict[str, Any]] = []
    # Track in-progress blocks by index
    blocks_by_index: dict[int, dict[str, Any]] = {}
    stop_reason = ""
    usage: dict[str, Any] = {}

    for event_type, data in events:
        msg_type = data.get("type", event_type)

        if msg_type == "message_start":
            msg = data.get("message", {})
            msg_usage = msg.get("usage", {})
            if msg_usage:
                usage.update(msg_usage)

        elif msg_type == "content_block_start":
            idx = data.get("index", len(blocks_by_index))
            block = data.get("content_block", {})
            btype = block.get("type", "text")
            if btype == "text":
                blocks_by_index[idx] = {"type": "text", "text": block.get("text", "")}
            elif btype == "tool_use":
                blocks_by_index[idx] = {
                    "type": "tool_use",
                    "id": block.get("id", ""),
                    "name": block.get("name", ""),
                    "input": {},
                    "_input_json": "",
                }
            elif btype == "thinking":
                blocks_by_index[idx] = {
                    "type": "thinking",
                    "thinking": block.get("thinking", ""),
                }
            else:
                blocks_by_index[idx] = dict(block)

        elif msg_type == "content_block_delta":
            idx = data.get("index", 0)
            delta = data.get("delta", {})
            delta_type = delta.get("type", "")
            block = blocks_by_index.get(idx)
            if block is None:
                continue
            if delta_type == "text_delta":
                block["text"] = block.get("text", "") + delta.get("text", "")
            elif delta_type == "input_json_delta":
                block["_input_json"] = block.get("_input_json", "") + delta.get(
                    "partial_json", ""
                )
            elif delta_type == "thinking_delta":
                block["thinking"] = block.get("thinking", "") + delta.get(
                    "thinking", ""
                )
            elif delta_type == "signature_delta":
                block["signature"] = delta.get("signature", "")

        elif msg_type == "content_block_stop":
            idx = data.get("index", 0)
            block = blocks_by_index.get(idx)
            if block and block.get("type") == "tool_use":
                raw_json = block.pop("_input_json", "")
                if raw_json:
                    try:
                        block["input"] = json.loads(raw_json)
                    except json.JSONDecodeError:
                        block["input"] = {}

        elif msg_type == "message_delta":
            delta = data.get("delta", {})
            if delta.get("stop_reason"):
                stop_reason = delta["stop_reason"]
            delta_usage = data.get("usage", {})
            if delta_usage:
                usage.update(delta_usage)

        elif msg_type == "message_stop":
            pass  # End of stream

    # Finalize content blocks in index order
    for idx in sorted(blocks_by_index):
        block = blocks_by_index[idx]
        # Clean up internal fields
        block.pop("_input_json", None)
        content_blocks.append(block)

    return {
        "content": content_blocks,
        "stop_reason": stop_reason,
        "usage": usage,
    }


def _parse_timestamp(value: object) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return 0
        if text.isdigit():
            return int(text)
        iso_candidate = text.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(iso_candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            return 0
    return 0


def _sorted_models(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        models,
        key=lambda m: (
            int(m.get("created_ts") or 0),
            str(m.get("id") or ""),
        ),
        reverse=True,
    )


# ---------------------------------------------------------------------------
# Model listing functions
# ---------------------------------------------------------------------------

def list_openai_models(
    api_key: str,
    base_url: str = "https://api.openai.com/v1",
    timeout_sec: int = 60,
) -> list[dict[str, Any]]:
    parsed = _http_json(
        url=base_url.rstrip("/") + "/models",
        method="GET",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout_sec=timeout_sec,
    )
    rows: list[dict[str, Any]] = []
    data = parsed.get("data")
    if isinstance(data, list):
        for row in data:
            if not isinstance(row, dict):
                continue
            model_id = str(row.get("id", "")).strip()
            if not model_id:
                continue
            created = _parse_timestamp(row.get("created") or row.get("created_at"))
            rows.append(
                {
                    "provider": "openai",
                    "id": model_id,
                    "created_ts": created,
                    "raw": row,
                }
            )
    return _sorted_models(rows)


def list_anthropic_models(
    api_key: str,
    base_url: str = "https://api.anthropic.com/v1",
    timeout_sec: int = 60,
) -> list[dict[str, Any]]:
    parsed = _http_json(
        url=base_url.rstrip("/") + "/models",
        method="GET",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        timeout_sec=timeout_sec,
    )
    rows: list[dict[str, Any]] = []
    data = parsed.get("data")
    if isinstance(data, list):
        for row in data:
            if not isinstance(row, dict):
                continue
            model_id = str(row.get("id", "")).strip()
            if not model_id:
                continue
            created = _parse_timestamp(
                row.get("created_at") or row.get("created") or row.get("released_at")
            )
            rows.append(
                {
                    "provider": "anthropic",
                    "id": model_id,
                    "created_ts": created,
                    "raw": row,
                }
            )
    return _sorted_models(rows)


def list_openrouter_models(
    api_key: str,
    base_url: str = "https://openrouter.ai/api/v1",
    timeout_sec: int = 60,
) -> list[dict[str, Any]]:
    parsed = _http_json(
        url=base_url.rstrip("/") + "/models",
        method="GET",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout_sec=timeout_sec,
    )
    rows: list[dict[str, Any]] = []
    data = parsed.get("data")
    if isinstance(data, list):
        for row in data:
            if not isinstance(row, dict):
                continue
            model_id = str(row.get("id", "")).strip()
            if not model_id:
                continue
            top_provider = row.get("top_provider")
            top_provider_created = (
                top_provider.get("created") if isinstance(top_provider, dict) else None
            )
            created = _parse_timestamp(
                row.get("created")
                or row.get("created_at")
                or top_provider_created
                or row.get("updated_at")
            )
            rows.append(
                {
                    "provider": "openrouter",
                    "id": model_id,
                    "created_ts": created,
                    "raw": row,
                }
            )
    return _sorted_models(rows)


# ---------------------------------------------------------------------------
# OpenAI-compatible model (native tool calling)
# ---------------------------------------------------------------------------

@dataclass
class OpenAICompatibleModel:
    model: str
    api_key: str
    base_url: str = "https://api.openai.com/v1"
    temperature: float = 0.0
    reasoning_effort: str | None = None
    timeout_sec: int = 300
    extra_headers: dict[str, str] = field(default_factory=dict)
    strict_tools: bool = True
    tool_defs: list[dict[str, Any]] | None = None
    on_content_delta: Callable[[str, str], None] | None = None

    def _is_reasoning_model(self) -> bool:
        """OpenAI reasoning models (o-series, gpt-5 series) have different API constraints."""
        lower = self.model.lower()
        if (
            lower.startswith("o1-") or lower == "o1"
            or lower.startswith("o3-") or lower == "o3"
            or lower.startswith("o4-") or lower == "o4"
        ):
            return True
        # GPT-5 series also supports reasoning_effort and uses max_completion_tokens.
        if lower.startswith("gpt-5"):
            return True
        return False

    def create_conversation(self, system_prompt: str, initial_user_message: str) -> Conversation:
        messages: list[Any] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": initial_user_message},
        ]
        return Conversation(_provider_messages=messages, system_prompt=system_prompt)

    def complete(self, conversation: Conversation) -> ModelTurn:
        is_reasoning = self._is_reasoning_model()

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": conversation._provider_messages,
            "tools": to_openai_tools(defs=self.tool_defs, strict=self.strict_tools),
            "tool_choice": "auto",
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        if conversation.stop_sequences:
            payload["stop"] = conversation.stop_sequences

        # Reasoning models (o-series) don't support temperature.
        if not is_reasoning:
            payload["temperature"] = self.temperature

        # Chat Completions API uses flat `reasoning_effort` (not the nested
        # `reasoning: {effort: ...}` format which is for the Responses API).
        effort = (self.reasoning_effort or "").strip().lower()
        if effort:
            payload["reasoning_effort"] = effort

        url = self.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }

        # Build SSE event forwarder for streaming text deltas to TUI
        def _forward_delta(_event_type: str, data: dict[str, Any]) -> None:
            cb = self.on_content_delta
            if cb is None:
                return
            choices = data.get("choices")
            if not choices:
                return
            delta = choices[0].get("delta", {})
            if not delta:
                return
            content = delta.get("content")
            if content:
                cb("text", content)

        sse_cb = _forward_delta if self.on_content_delta else None

        try:
            events = _http_stream_sse(
                url=url,
                method="POST",
                headers=headers,
                payload=payload,
                stream_timeout=self.timeout_sec,
                on_sse_event=sse_cb,
            )
            parsed = _accumulate_openai_stream(events)
        except ModelError as exc:
            text = str(exc).lower()
            unsupported_reasoning = effort and (
                "reasoning_effort" in text
                and ("unsupported_parameter" in text or "unknown" in text)
            )
            if not unsupported_reasoning:
                raise
            payload = dict(payload)
            payload.pop("reasoning_effort", None)
            events = _http_stream_sse(
                url=url,
                method="POST",
                headers=headers,
                payload=payload,
                stream_timeout=self.timeout_sec,
                on_sse_event=sse_cb,
            )
            parsed = _accumulate_openai_stream(events)

        try:
            message = parsed["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelError(f"Model response missing content: {parsed}") from exc

        finish_reason = parsed["choices"][0].get("finish_reason", "")

        # Parse tool calls
        raw_tool_calls = message.get("tool_calls")
        tool_calls: list[ToolCall] = []
        if raw_tool_calls and isinstance(raw_tool_calls, list):
            for tc in raw_tool_calls:
                func = tc.get("function", {})
                args_str = func.get("arguments", "{}")
                try:
                    args = json.loads(args_str)
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(ToolCall(
                    id=tc.get("id", ""),
                    name=func.get("name", ""),
                    arguments=args if isinstance(args, dict) else {},
                ))

        # Extract text content
        text_content = _extract_content(message.get("content", "")) or None
        if text_content is not None and not text_content.strip():
            text_content = None

        # Extract token usage
        usage = parsed.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0) if isinstance(usage, dict) else 0
        output_tokens = usage.get("completion_tokens", 0) if isinstance(usage, dict) else 0

        return ModelTurn(
            tool_calls=tool_calls,
            text=text_content,
            stop_reason=finish_reason,
            raw_response=message,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def append_assistant_turn(self, conversation: Conversation, turn: ModelTurn) -> None:
        # Replay the raw OpenAI message object to preserve tool_calls array
        conversation._provider_messages.append(turn.raw_response)
        conversation.turn_count += 1

    def append_tool_results(self, conversation: Conversation, results: list[ToolResult]) -> None:
        for r in results:
            conversation._provider_messages.append({
                "role": "tool",
                "tool_call_id": r.tool_call_id,
                "name": r.name,
                "content": r.content,
            })

    def condense_conversation(self, conversation: Conversation, keep_recent_turns: int = 4) -> int:
        """Replace old tool result contents with a short placeholder.

        Returns the number of messages condensed.
        """
        msgs = conversation._provider_messages
        # Find indices of tool-role messages.
        tool_indices = [i for i, m in enumerate(msgs) if isinstance(m, dict) and m.get("role") == "tool"]
        if len(tool_indices) <= keep_recent_turns:
            return 0
        to_condense = tool_indices[:-keep_recent_turns]
        condensed = 0
        placeholder = "[earlier tool output condensed]"
        for idx in to_condense:
            msg = msgs[idx]
            if msg.get("content") != placeholder:
                msg["content"] = placeholder
                condensed += 1
        return condensed


# ---------------------------------------------------------------------------
# Anthropic model (native tool calling)
# ---------------------------------------------------------------------------

@dataclass
class AnthropicModel:
    model: str
    api_key: str
    base_url: str = "https://api.anthropic.com/v1"
    temperature: float = 0.0
    reasoning_effort: str | None = None
    max_tokens: int = 16384
    timeout_sec: int = 300
    tool_defs: list[dict[str, Any]] | None = None
    on_content_delta: Callable[[str, str], None] | None = None

    def create_conversation(self, system_prompt: str, initial_user_message: str) -> Conversation:
        messages: list[Any] = [
            {"role": "user", "content": initial_user_message},
        ]
        return Conversation(_provider_messages=messages, system_prompt=system_prompt)

    def _is_opus_46(self) -> bool:
        return "opus-4-6" in self.model.lower() or "opus-4.6" in self.model.lower()

    def complete(self, conversation: Conversation) -> ModelTurn:
        effort = (self.reasoning_effort or "").strip().lower()
        use_thinking = effort in {"low", "medium", "high"}

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": conversation._provider_messages,
            "tools": to_anthropic_tools(defs=self.tool_defs),
            "stream": True,
        }

        if conversation.stop_sequences:
            payload["stop_sequences"] = conversation.stop_sequences

        # Thinking is incompatible with temperature — omit it entirely.
        if not use_thinking:
            payload["temperature"] = self.temperature
        if use_thinking:
            if self._is_opus_46():
                # Opus 4.6: adaptive thinking (manual mode deprecated).
                payload["thinking"] = {"type": "adaptive"}
                payload["output_config"] = {"effort": effort}
            else:
                # Older models: manual thinking with explicit budget.
                budget = {"low": 1024, "medium": 4096, "high": 8192}[effort]
                if payload["max_tokens"] <= budget:
                    payload["max_tokens"] = budget + 8192
                payload["thinking"] = {"type": "enabled", "budget_tokens": budget}
        if conversation.system_prompt:
            payload["system"] = conversation.system_prompt

        url = self.base_url.rstrip("/") + "/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        # Build SSE event forwarder for streaming deltas to TUI
        def _forward_delta(_event_type: str, data: dict[str, Any]) -> None:
            cb = self.on_content_delta
            if cb is None:
                return
            msg_type = data.get("type", _event_type)
            if msg_type != "content_block_delta":
                return
            delta = data.get("delta", {})
            delta_type = delta.get("type", "")
            if delta_type == "thinking_delta":
                text = delta.get("thinking", "")
                if text:
                    cb("thinking", text)
            elif delta_type == "text_delta":
                text = delta.get("text", "")
                if text:
                    cb("text", text)

        sse_cb = _forward_delta if self.on_content_delta else None

        try:
            events = _http_stream_sse(
                url=url,
                method="POST",
                headers=headers,
                payload=payload,
                stream_timeout=self.timeout_sec,
                on_sse_event=sse_cb,
            )
            parsed = _accumulate_anthropic_stream(events)
        except ModelError as exc:
            text = str(exc).lower()
            unsupported_thinking = use_thinking and (
                "thinking" in text
                and ("unknown" in text or "unsupported" in text or "invalid" in text)
            )
            if not unsupported_thinking:
                raise
            payload = dict(payload)
            payload.pop("thinking", None)
            payload.pop("output_config", None)
            events = _http_stream_sse(
                url=url,
                method="POST",
                headers=headers,
                payload=payload,
                stream_timeout=self.timeout_sec,
                on_sse_event=sse_cb,
            )
            parsed = _accumulate_anthropic_stream(events)

        stop_reason = parsed.get("stop_reason", "")
        content_blocks = parsed.get("content", [])
        if not isinstance(content_blocks, list):
            content_blocks = []

        # Parse content blocks
        tool_calls: list[ToolCall] = []
        text_parts: list[str] = []
        for block in content_blocks:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type", "")
            if block_type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.get("id", ""),
                    name=block.get("name", ""),
                    arguments=block.get("input", {}) if isinstance(block.get("input"), dict) else {},
                ))
            elif block_type == "text":
                t = block.get("text", "")
                if isinstance(t, str) and t.strip():
                    text_parts.append(t)

        text_content = "\n".join(text_parts) if text_parts else None

        # Extract token usage
        usage = parsed.get("usage", {})
        input_tokens = usage.get("input_tokens", 0) if isinstance(usage, dict) else 0
        output_tokens = usage.get("output_tokens", 0) if isinstance(usage, dict) else 0

        return ModelTurn(
            tool_calls=tool_calls,
            text=text_content,
            stop_reason=stop_reason,
            raw_response=content_blocks,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def append_assistant_turn(self, conversation: Conversation, turn: ModelTurn) -> None:
        # Replay the full content block array (including thinking blocks)
        conversation._provider_messages.append({
            "role": "assistant",
            "content": turn.raw_response,
        })
        conversation.turn_count += 1

    def append_tool_results(self, conversation: Conversation, results: list[ToolResult]) -> None:
        tool_result_blocks = []
        for r in results:
            block: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": r.tool_call_id,
                "content": r.content,
            }
            if r.is_error:
                block["is_error"] = True
            tool_result_blocks.append(block)
        conversation._provider_messages.append({
            "role": "user",
            "content": tool_result_blocks,
        })

    def condense_conversation(self, conversation: Conversation, keep_recent_turns: int = 4) -> int:
        """Replace old tool result contents with a short placeholder.

        Anthropic tool results are nested inside user messages as content blocks
        with type "tool_result". We preserve tool_use_id (required by the API)
        but replace the content string.
        """
        msgs = conversation._provider_messages
        placeholder = "[earlier tool output condensed]"
        # Find indices of user messages that contain tool_result blocks.
        tool_msg_indices: list[int] = []
        for i, m in enumerate(msgs):
            if not isinstance(m, dict) or m.get("role") != "user":
                continue
            content = m.get("content")
            if isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in content
            ):
                tool_msg_indices.append(i)
        if len(tool_msg_indices) <= keep_recent_turns:
            return 0
        to_condense = tool_msg_indices[:-keep_recent_turns]
        condensed = 0
        for idx in to_condense:
            content = msgs[idx].get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                if block.get("content") != placeholder:
                    block["content"] = placeholder
                    condensed += 1
        return condensed


# ---------------------------------------------------------------------------
# Test / fallback models
# ---------------------------------------------------------------------------

@dataclass
class ScriptedModel:
    """Model that returns pre-scripted ModelTurn responses for testing."""
    scripted_turns: list[ModelTurn] = field(default_factory=list)

    def create_conversation(self, system_prompt: str, initial_user_message: str) -> Conversation:
        return Conversation(
            _provider_messages=[{"role": "user", "content": initial_user_message}],
            system_prompt=system_prompt,
        )

    def complete(self, conversation: Conversation) -> ModelTurn:
        if not self.scripted_turns:
            raise ModelError("ScriptedModel exhausted; no responses left.")
        return self.scripted_turns.pop(0)

    def append_assistant_turn(self, conversation: Conversation, turn: ModelTurn) -> None:
        pass

    def append_tool_results(self, conversation: Conversation, results: list[ToolResult]) -> None:
        pass

    def condense_conversation(self, conversation: Conversation, keep_recent_turns: int = 4) -> int:
        return 0


@dataclass
class EchoFallbackModel:
    note: str = (
        "No provider API keys configured. Set OpenAI/Anthropic/OpenRouter/Gemini keys to use a live LLM."
    )

    def create_conversation(self, system_prompt: str, initial_user_message: str) -> Conversation:
        return Conversation(
            _provider_messages=[{"role": "user", "content": initial_user_message}],
            system_prompt=system_prompt,
        )

    def complete(self, conversation: Conversation) -> ModelTurn:
        return ModelTurn(text=self.note, stop_reason="end_turn")

    def append_assistant_turn(self, conversation: Conversation, turn: ModelTurn) -> None:
        pass

    def append_tool_results(self, conversation: Conversation, results: list[ToolResult]) -> None:
        pass

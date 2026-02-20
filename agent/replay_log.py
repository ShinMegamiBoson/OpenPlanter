"""Replay-capable LLM interaction logging with delta encoding."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class ReplayLogger:
    """Logs every LLM API call so any individual call can be replayed exactly.

    Uses delta encoding: seq 0 stores a full messages snapshot, seq 1+
    store only messages appended since the previous call.

    Each conversation (root + subtasks) gets its own conversation_id.
    All records append to the same JSONL file in chronological order.
    """

    path: Path
    conversation_id: str = "root"
    _seq: int = field(default=0, init=False)
    _last_msg_count: int = field(default=0, init=False)

    def child(self, depth: int, step: int) -> ReplayLogger:
        """Create a child logger for a subtask conversation."""
        child_id = f"{self.conversation_id}/d{depth}s{step}"
        return ReplayLogger(path=self.path, conversation_id=child_id)

    def write_header(
        self,
        *,
        provider: str,
        model: str,
        base_url: str,
        system_prompt: str,
        tool_defs: list[Any],
        reasoning_effort: str | None = None,
        temperature: float | None = None,
    ) -> None:
        record: dict[str, Any] = {
            "type": "header",
            "conversation_id": self.conversation_id,
            "provider": provider,
            "model": model,
            "base_url": base_url,
            "system_prompt": system_prompt,
            "tool_defs": tool_defs,
        }
        if reasoning_effort is not None:
            record["reasoning_effort"] = reasoning_effort
        if temperature is not None:
            record["temperature"] = temperature
        self._append(record)

    def log_call(
        self,
        *,
        depth: int,
        step: int,
        messages: list[Any],
        response: Any,
        input_tokens: int = 0,
        output_tokens: int = 0,
        elapsed_sec: float = 0.0,
    ) -> None:
        record: dict[str, Any] = {
            "type": "call",
            "conversation_id": self.conversation_id,
            "seq": self._seq,
            "depth": depth,
            "step": step,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        if self._seq == 0:
            record["messages_snapshot"] = messages
        else:
            record["messages_delta"] = messages[self._last_msg_count:]
        record["response"] = response
        record["input_tokens"] = input_tokens
        record["output_tokens"] = output_tokens
        record["elapsed_sec"] = round(elapsed_sec, 3)

        self._last_msg_count = len(messages)
        self._seq += 1
        self._append(record)

    def _append(self, record: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=True, default=str) + "\n")

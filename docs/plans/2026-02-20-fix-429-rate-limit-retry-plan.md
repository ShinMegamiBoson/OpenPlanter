---
title: "fix: Graceful 429 rate limit retry with countdown"
type: fix
status: completed
date: 2026-02-20
deepened: 2026-02-20
brainstorm: docs/brainstorms/2026-02-20-429-rate-limit-handling-brainstorm.md
---

# fix: Graceful 429 Rate Limit Retry with Countdown

## Enhancement Summary

**Deepened on:** 2026-02-20
**Sections enhanced:** 6
**Research agents used:** architecture-strategist, kieran-python-reviewer,
code-simplicity-reviewer, performance-oracle, security-sentinel,
pattern-recognition-specialist, best-practices-researcher,
framework-docs-researcher

### Key Improvements

1. Extract `_parse_retry_after()` and `_sleep_with_countdown()` as pure/reusable
   helpers -- keeps the retry loop body clean and individually testable
2. `on_retry` fires at ALL depths (not depth-gated like `on_content_delta`) so
   rate-limit messages always reach the TUI regardless of recursion depth
3. Truncate HTTP error response bodies to 8 KB before embedding in `ModelError`
   messages to prevent memory issues from large error payloads

### New Considerations Discovered

- Anthropic uses HTTP 529 for `overloaded_error` (separate from 429
  `rate_limit_error`). Out of scope for v1 but the architecture accommodates it
  trivially by adding `exc.code in (429, 529)`.
- The worst-case hang is 5 rate-limit retries x 120s cap = ~10 minutes per call.
  Document as known limitation; a total wall-clock timeout can be added later.
- `on_retry` callback must be wrapped in try/except (matching `_emit` pattern)
  so a broken callback never kills the retry loop.
- `import time` is not currently in `agent/model.py` and must be added.
- Tests must patch `time.sleep` via `unittest.mock.patch("agent.model.time.sleep")`
  to avoid actually sleeping.

## Overview

When the app receives an HTTP 429 from the Anthropic API, it crashes the solve
loop. This plan adds retry logic with `Retry-After` header support and a visible
TUI countdown, so the user sees what's happening and the app recovers
automatically.

## Problem Statement

`_http_stream_sse()` catches `urllib.error.HTTPError` and immediately raises
`ModelError` regardless of status code. The engine's `_solve_recursive()` catches
that `ModelError` and terminates the task. The user sees an error and must
re-submit. Rate limits are transient -- the app should wait and retry.

## Proposed Solution

Add 429 detection and retry-with-countdown inline in both transport functions
(`_http_stream_sse` and `_http_json`). Honor the `Retry-After` header. Fire
status messages through an `on_retry` callback for TUI display.

**Key design decisions (from brainstorm):**

- **Generic 429 handling** in shared transport functions. The code checks
  `exc.code == 429` regardless of provider. "Anthropic only" refers to testing
  scope, not implementation restriction.
- **Separate retry budget** from connection-timeout retries. 429 retries (max 5)
  and connection retries (existing max 3) are independent counters.
- **`on_retry` callback signature:** `Callable[[str], None]` -- receives a
  human-readable status message. Matches the `on_event` pattern. The transport
  function generates the string; the caller decides how to display it.
- **`on_retry` lifecycle:** Follows the `on_content_delta` pattern -- set as a
  field on model instances, managed by the engine before/after `complete()`.
- **`_http_json()` retries silently** for now. No callback threading through the
  4-function model-listing chain. Countdown display is for streaming calls only.
- **No parallel worker coordination.** Each worker retries independently.
  Document as a known limitation.

## Technical Considerations

### `Retry-After` header parsing

- Parse as integer seconds only (Anthropic's format). If missing or unparseable,
  fall back to **5 seconds**.
- **Floor:** 1 second. **Cap:** 120 seconds. Prevents tight loops and absurd waits.
- Access via `exc.headers.get("Retry-After")` on `urllib.error.HTTPError`.

#### Research Insights

**Anthropic API behavior (confirmed from official docs):**

- 429 error body: `{"type": "error", "error": {"type": "rate_limit_error", "message": "..."}}`
- `Retry-After` header: integer seconds format (not HTTP-date)
- Additional headers on every response: `anthropic-ratelimit-requests-limit`,
  `anthropic-ratelimit-requests-remaining`, `anthropic-ratelimit-requests-reset`,
  and matching `tokens-*` variants. These can inform proactive throttling in a
  future enhancement but are not needed for v1.
- HTTP 529 (`overloaded_error`) is a separate status code. Not handled in v1.

**Implementation: Extract `_parse_retry_after()` as a pure function:**

```python
def _parse_retry_after(exc: urllib.error.HTTPError, default: int = 5) -> int:
    """Parse Retry-After header from an HTTPError, clamped to [1, 120]."""
    raw = exc.headers.get("Retry-After")
    if raw is None:
        return default
    try:
        return max(1, min(120, int(raw)))
    except (ValueError, TypeError):
        return default
```

This is independently testable without mocking any HTTP machinery.

### Retry loop architecture in `_http_stream_sse()`

The existing function has a retry loop for connection errors. The 429 retry wraps
the entire existing attempt logic as an outer concern:

```
for rate_limit_attempt in range(max_rate_limit_retries):  # new outer loop (5)
    for attempt in range(max_retries):                     # existing inner loop (3)
        try:
            resp = urlopen(req, ...)
        except HTTPError as exc:
            if exc.code == 429:
                break  # break inner, trigger outer retry with sleep
            raise ModelError(...)
        except (timeout, URLError, OSError):
            continue  # existing connection retry
    else:
        # connection retries exhausted
        raise ModelError(...)
    if got_429:
        sleep with countdown
        continue  # outer loop retry
    return events  # success
```

#### Research Insights

**Nested loop sentinel pattern:** The `got_429` sentinel variable mediates
between the inner `break` and the outer `continue`. This is the simplest pattern
that keeps the two retry budgets independent. An alternative (extracting the
inner loop into `_urlopen_with_retries()`) was considered but adds a function
boundary without reducing complexity for the current scope.

**Callback safety:** The `on_retry` callback must be wrapped in try/except to
prevent a broken callback from killing the retry loop:

```python
def _notify_retry(on_retry: "Callable[[str], None] | None", msg: str) -> None:
    if on_retry is not None:
        try:
            on_retry(msg)
        except Exception:
            pass  # never let a callback kill the retry loop
```

**Sleep with countdown helper:**

```python
def _sleep_with_countdown(
    seconds: int,
    attempt: int,
    max_attempts: int,
    on_retry: "Callable[[str], None] | None",
) -> None:
    """Sleep for `seconds`, firing on_retry with a countdown each second."""
    for remaining in range(seconds, 0, -1):
        _notify_retry(
            on_retry,
            f"Rate limited (attempt {attempt}/{max_attempts}). "
            f"Retrying in {remaining}s...",
        )
        time.sleep(1)
```

### Threading safety

- `time.sleep()` blocks the calling thread. Safe on main thread (TUI refresh
  runs on its own thread). Safe on worker threads (they're dedicated to their
  task).
- `on_retry` callback fires from the sleeping thread. The existing `on_event`
  callback is already called from worker threads (in `_run_one_tool`), so the
  TUI's console locking handles concurrent output.
- `KeyboardInterrupt` during `time.sleep()` propagates naturally. The engine's
  `finally` block clears `on_content_delta`/`on_retry`. Verify `_ThinkingDisplay`
  stops cleanly.

### TUI interaction

- During a 429 wait, the `_ThinkingDisplay` ("Thinking...") may still be active.
  The retry countdown fires through `on_event`, which appears in the event log.
  This is adequate for v1 -- a more polished approach (stopping the thinking
  display and replacing it with a countdown widget) can follow later.

### Security considerations

#### Research Insights

- **Truncate error response bodies:** HTTP error responses can contain large
  payloads. Cap at 8 KB before embedding in `ModelError` messages to prevent
  memory issues. Apply in both `_http_stream_sse` and `_http_json`.
- **Keep `on_retry` messages application-controlled:** The retry message strings
  are generated by our code, not echoed from the server response. This prevents
  any server-supplied content from reaching the TUI unescaped.
- **No credentials in error messages:** The existing pattern already strips
  `Authorization` headers from error context. No changes needed.

## System-Wide Impact

- **Interaction graph:** `_http_stream_sse()` is called by
  `OpenAICompatibleModel.complete()` and `AnthropicModel.complete()`, both of
  which have a fallback retry path for unsupported parameters. All 4 call sites
  (2 primary + 2 fallback) need `on_retry` threaded through.
- **Error propagation:** After 5 retries, `ModelError` propagates exactly as
  today. The error message includes the retry count for debuggability. Format:
  `"HTTP 429 calling {url}: rate limited, exhausted {N} retries"` (matches
  existing `"HTTP {code} calling {url}: {detail}"` pattern).
- **State lifecycle risks:** None. The retry loop is stateless -- it only reads
  the `Retry-After` header and sleeps. No persistent state is created or modified.
- **API surface parity:** `_http_json()` gets the same retry logic but without
  the callback (silent retry). `_http_stream_sse()` gets retry + callback.
- **Test helpers:** `mock_openai_stream` and `mock_anthropic_stream` in
  `conftest.py` must accept the new `on_retry` parameter.

#### Research Insights

- **`on_retry` depth gating:** Unlike `on_content_delta` (which only fires at
  `depth == 0`), `on_retry` should fire at ALL depths. Rate-limit messages are
  operational status, not content -- the user should always see them regardless
  of recursion depth. Wire it unconditionally in `_solve_recursive()`.
- **`finally` block parity:** The `finally` block in `_solve_recursive()` must
  clear both `on_content_delta` and `on_retry`. Use the existing `hasattr` guard
  pattern.
- **Worst-case timing:** 5 rate-limit retries x 120s cap = ~10 minutes max hang
  per single `_http_stream_sse` call. With the inner connection retry loop, the
  theoretical ceiling is 5 x (3 connection attempts + 120s sleep) but in practice
  connection retries are fast failures. Document as known limitation.

## Acceptance Criteria

### Functional

- [x] 429 with `Retry-After: N` header triggers automatic retry after N seconds
- [x] Missing `Retry-After` header falls back to 5-second wait
- [x] `Retry-After` values are clamped to [1, 120] seconds
- [x] Max 5 retry attempts before raising `ModelError`
- [x] `on_retry` callback receives messages like `"Rate limited (attempt 2/5). Retrying in 8s..."`
- [x] Countdown ticks once per second (`"...7s"`, `"...6s"`, etc.)
- [x] Non-429 HTTP errors still raise immediately (no regression)
- [x] Connection-timeout retries still work independently of 429 retries
- [x] `_http_json()` retries 429 silently (no callback, same retry logic)
- [x] After exhausting retries, error message includes retry count
- [x] Parameter-fallback retry paths (`reasoning_effort`, `thinking`) also get
      429 protection on their second `_http_stream_sse()` call

### Non-Functional

- [x] Thread-safe: parallel workers can retry independently without corruption
- [x] `KeyboardInterrupt` during sleep cancels cleanly (no TUI corruption)
- [x] No new dependencies (stdlib `time.sleep` only)
- [x] Error response bodies truncated to 8 KB in `ModelError` messages
- [x] `on_retry` callback failures never kill the retry loop

## MVP

### Step 1: Add 429 retry to `_http_stream_sse()`

**`agent/model.py`**

Add `import time` at top of file. Add `_parse_retry_after()`,
`_notify_retry()`, and `_sleep_with_countdown()` as module-level helpers. Add
`on_retry` and `max_rate_limit_retries` parameters to `_http_stream_sse()`.
Restructure the retry loop with an outer 429-retry layer.

```python
# agent/model.py - new helpers (above _http_stream_sse)

def _parse_retry_after(exc: urllib.error.HTTPError, default: int = 5) -> int:
    """Parse Retry-After header from an HTTPError, clamped to [1, 120]."""
    raw = exc.headers.get("Retry-After")
    if raw is None:
        return default
    try:
        return max(1, min(120, int(raw)))
    except (ValueError, TypeError):
        return default


def _notify_retry(on_retry: "Callable[[str], None] | None", msg: str) -> None:
    """Fire on_retry callback, swallowing any exception."""
    if on_retry is not None:
        try:
            on_retry(msg)
        except Exception:
            pass


def _sleep_with_countdown(
    seconds: int,
    attempt: int,
    max_attempts: int,
    on_retry: "Callable[[str], None] | None",
) -> None:
    """Sleep for `seconds`, firing on_retry with a countdown each second."""
    for remaining in range(seconds, 0, -1):
        _notify_retry(
            on_retry,
            f"Rate limited (attempt {attempt}/{max_attempts}). "
            f"Retrying in {remaining}s...",
        )
        time.sleep(1)
```

```python
# agent/model.py - _http_stream_sse signature
def _http_stream_sse(
    url: str,
    method: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    first_byte_timeout: float = 10,
    stream_timeout: float = 120,
    max_retries: int = 3,
    on_sse_event: "Callable[[str, dict[str, Any]], None] | None" = None,
    on_retry: "Callable[[str], None] | None" = None,        # NEW
    max_rate_limit_retries: int = 5,                         # NEW
) -> list[tuple[str, dict[str, Any]]]:
```

### Step 2: Add 429 retry to `_http_json()`

**`agent/model.py`**

Add a retry loop to `_http_json()` for 429 responses. Silent (no callback) since
the model-listing call chain doesn't pass callbacks.

```python
# agent/model.py - _http_json with retry loop
def _http_json(
    url: str,
    method: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None = None,
    timeout_sec: int = 90,
    max_rate_limit_retries: int = 5,                         # NEW
) -> dict[str, Any]:
```

### Step 3: Thread `on_retry` through model classes

**`agent/model.py`**

Add `on_retry: Callable[[str], None] | None = None` field to both
`OpenAICompatibleModel` and `AnthropicModel` (alongside existing
`on_content_delta`). Pass it through to `_http_stream_sse()` in `complete()` --
all 4 call sites (2 primary + 2 fallback).

### Step 4: Wire `on_retry` in the engine

**`agent/engine.py`**

Set `model.on_retry` in `_solve_recursive()` before calling `model.complete()`,
and clear it in the `finally` block. Wire it **unconditionally** (not gated by
`depth == 0` like `on_content_delta`) so rate-limit messages always reach the TUI.

```python
# engine.py - in _solve_recursive, alongside on_content_delta setup
# NOTE: on_retry fires at ALL depths (not depth-gated)
model.on_retry = (lambda msg: self._emit(msg, on_event)) if on_event else None
```

```python
# engine.py - in finally block, clear both callbacks
if hasattr(model, "on_content_delta"):
    model.on_content_delta = None
if hasattr(model, "on_retry"):
    model.on_retry = None
```

### Step 5: Update test helpers

**`tests/conftest.py`**

Update `mock_openai_stream` and `mock_anthropic_stream` wrapper signatures to
accept `on_retry=None` and `max_rate_limit_retries=5`.

### Step 6: Write tests (TDD -- these come first in practice)

**`tests/test_rate_limit.py`** (new file)

Tests must patch `time.sleep` via `unittest.mock.patch("agent.model.time.sleep")`
to avoid actually sleeping during test runs.

- `test_parse_retry_after_with_valid_header`
- `test_parse_retry_after_missing_header_uses_default`
- `test_parse_retry_after_clamped_to_bounds`
- `test_parse_retry_after_non_integer_uses_default`
- `test_429_retries_and_succeeds`
- `test_429_exhausts_retries_raises_model_error`
- `test_429_on_retry_callback_invoked_with_countdown`
- `test_non_429_http_error_raises_immediately` (regression guard)
- `test_429_in_http_json_retries_silently`
- `test_connection_retry_and_429_retry_are_independent`
- `test_notify_retry_swallows_callback_exceptions`

## Known Limitations

- **Parallel worker stampede:** Multiple `ThreadPoolExecutor` workers can hit 429
  simultaneously and all retry at the same Retry-After expiry. No coordination
  between workers. Acceptable for v1; consider adding jitter later.
- **`_ThinkingDisplay` overlap:** During a 429 wait, the thinking spinner
  continues showing "Thinking..." alongside the rate-limit event message. A
  dedicated countdown widget can be added in a follow-up.
- **`_http_json()` retries silently:** No countdown for `/model list`. Acceptable
  since model listing is a quick, infrequent operation.
- **SSE-level rate limit errors** (Anthropic `overloaded_error` in-stream) are
  not covered. Only HTTP-level 429 is handled.
- **HTTP 529 (`overloaded_error`)** is not retried. The architecture supports
  adding `exc.code in (429, 529)` trivially in a follow-up.
- **Worst-case hang:** 5 retries x 120s cap = ~10 minutes per call with no
  total wall-clock timeout. Acceptable for v1; a cumulative timeout can be added.

## References

- Brainstorm: `docs/brainstorms/2026-02-20-429-rate-limit-handling-brainstorm.md`
- Transport functions: `agent/model.py:98` (`_http_json`), `agent/model.py:206`
  (`_http_stream_sse`)
- Engine error handling: `agent/engine.py:329`
- Existing retry tests: `tests/test_streaming.py:195`
- Test helpers: `tests/conftest.py:164`
- Anthropic rate limits docs: https://docs.anthropic.com/en/api/rate-limits
- Anthropic error types: https://docs.anthropic.com/en/api/errors

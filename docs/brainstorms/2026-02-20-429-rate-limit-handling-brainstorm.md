# Brainstorm: Graceful 429 Rate Limit Handling

**Date:** 2026-02-20
**Status:** Ready for planning

## What We're Building

Retry logic for HTTP 429 (rate limit) responses from the Anthropic API. When the
app hits a rate limit, it should wait using the `Retry-After` header and retry
automatically — up to 5 attempts — with a visible countdown in the TUI so the
user knows what's happening.

## Why This Approach

**Problem:** The app currently treats 429 as a fatal error. `_http_stream_sse()`
catches `HTTPError` and immediately raises `ModelError`, which terminates the
engine's solve loop. The user sees an error and has to restart.

**Approach A (inline retry)** was chosen over a retry decorator or model-layer
retry because:

- The existing `_http_stream_sse()` already has a retry loop for connection
  errors — extending it for 429 is natural
- Only two call sites need updating (`_http_stream_sse` and `_http_json`), which
  doesn't justify a new abstraction
- Keeps HTTP retry concerns in the HTTP transport layer where they belong

## Key Decisions

1. **Scope: Anthropic 429 only (for now).** Other providers and other transient
   errors (5xx) are out of scope. The shared code path means expanding later is
   straightforward.

2. **Retry strategy: Respect `Retry-After` header, max 5 attempts.** Anthropic
   includes this header in 429 responses. We honor it directly rather than
   implementing our own exponential backoff.

3. **UX: Visible countdown.** During the wait, show a live countdown
   (e.g., "Rate limited. Retrying in 8s... 7s... 6s...") in the TUI event stream
   so the user knows the app hasn't hung.

4. **Both call paths covered.** Retry logic goes in both `_http_stream_sse()`
   (streaming LLM calls) and `_http_json()` (model listing).

5. **Failure mode: ModelError as today.** After 5 failed attempts, raise the same
   `ModelError` the app raises now. No new exception subclasses.

6. **Implementation: Inline in transport functions.** No decorators, no new
   abstractions. Extend the existing retry pattern.

## Affected Code

| File | Function | Change |
|------|----------|--------|
| `agent/model.py` | `_http_stream_sse()` | Add 429 detection in HTTPError handler, parse Retry-After, sleep with countdown, loop |
| `agent/model.py` | `_http_json()` | Same pattern |
| `agent/model.py` | Both functions' signatures | Add optional `on_retry` callback for countdown display |
| `agent/engine.py` | Call sites of above | Thread `on_event` through as `on_retry` callback |

## Open Questions

None — all questions resolved during brainstorming.

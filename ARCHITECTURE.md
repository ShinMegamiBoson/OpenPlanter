# Architecture

This document describes the high-level architecture of OpenPlanter, a recursive
language model investigation agent with a terminal UI. It is intended for
developers extending the codebase and AI agents navigating it. Read this first,
then use symbol search (`Cmd+T` / `osgrep`) to locate specifics.

## Bird's Eye View

OpenPlanter solves a specific problem: given a workspace full of heterogeneous
datasets (corporate registries, campaign finance records, lobbying disclosures,
government contracts), resolve entities across them and surface non-obvious
connections through evidence-backed analysis.

The core paradigm is a **recursive language model agent loop**. A user submits
an objective. The engine feeds it to an LLM with tool definitions. The LLM
returns tool calls (read files, run shell commands, search the web, spawn
sub-agents). The engine executes them, appends observations, and loops until
the LLM produces a final text answer or the step budget is exhausted.

Key design principles:

- **Provider-agnostic.** OpenAI, Anthropic, OpenRouter, and Cerebras are
  first-class providers behind a shared `BaseModel` protocol. No SDK
  dependencies -- all HTTP is raw `urllib`.
- **Recursive delegation.** The top-level agent can spawn sub-agents via
  `subtask` (same or lower-tier model) and `execute` (leaf executor, cheapest
  model). Sub-agents share workspace state but get independent conversations.
- **Zero runtime dependencies beyond stdlib + Rich.** Only three PyPI packages:
  `rich`, `prompt_toolkit`, `pyfiglet` (all for the TUI). The agent core,
  model layer, and tools use only the Python standard library.
- **Workspace-sandboxed.** All file operations are confined to the workspace
  root. Path traversal is blocked at the tool layer.

```
 +--------------+
 |   CLI / TUI  |  __main__.py, tui.py
 +------+-------+
        | objective
 +------v-------+
 | SessionRuntime|  runtime.py -- persistence, replay logging
 +------+-------+
        | solve()
 +------v-------+
 |  RLMEngine   |  engine.py -- recursive step loop
 |  +---------+ |
 |  | BaseModel| |  model.py -- provider-agnostic LLM protocol
 |  +---------+ |
 |  +---------+ |
 |  |  Tools  | |  tools.py -- workspace I/O, shell, web search
 |  +---------+ |
 +--------------+
```

## High-Level Data Flow

```
User objective (text)
  |
  v
__main__.main() -- parse args, load credentials, build engine
  |
  v
SessionRuntime.solve() -- open/resume session, wrap event callbacks
  |
  v
RLMEngine.solve_with_context() -- enter recursive step loop
  |
  +-> model.complete(conversation) -- LLM API call (SSE streaming)
  |     returns ModelTurn { tool_calls[], text, tokens }
  |
  +-> if tool_calls: dispatch each via _apply_tool_call()
  |     +- file tools -> WorkspaceTools methods
  |     +- shell tools -> subprocess with timeout
  |     +- web tools -> Exa API
  |     +- subtask -> _solve_recursive(depth+1, same/lower model)
  |     +- execute -> _solve_recursive(depth+1, cheapest model)
  |     +- think -> no-op (recorded as observation)
  |
  +-> append observations to conversation, loop
  |
  +-> if no tool_calls + text present: return final answer
```

## Codemap

### `agent/` -- Core Agent Package (~6,200 lines)

| File | Lines | Purpose |
|------|------:|---------|
| `engine.py` | 935 | Recursive step loop (`RLMEngine`), tool dispatch, context condensation, sub-agent spawning, acceptance criteria judging, budget warnings, plan injection |
| `model.py` | 1020 | Provider-agnostic LLM abstraction: `BaseModel` protocol, `OpenAICompatibleModel`, `AnthropicModel`, SSE streaming, model listing APIs, `ScriptedModel` for tests |
| `tools.py` | 845 | Workspace-sandboxed tool implementations: file I/O, shell execution (fg/bg), ripgrep search, repo map with symbol extraction, Exa web search, parallel write conflict detection |
| `tui.py` | 820 | Rich terminal UI: ASCII splash art, thinking display with streaming, step tree rendering, slash commands (`/model`, `/reasoning`, `/status`), `RichREPL` main loop |
| `__main__.py` | 585 | CLI entry point: argparse, credential loading cascade, provider resolution, engine construction, headless task mode, plain REPL fallback |
| `tool_defs.py` | 537 | Provider-neutral JSON schemas for all 19 tools, converters to OpenAI and Anthropic formats, strict-mode enforcement for OpenAI |
| `prompts.py` | 350 | System prompt assembly: base prompt (epistemic discipline, hard rules, data ingestion), recursive REPL section, acceptance criteria section, demo mode section |
| `runtime.py` | 345 | Session lifecycle: `SessionStore` (create/resume/list sessions, persist state, append JSONL events, write artifacts), `SessionRuntime` (wraps engine with persistence) |
| `credentials.py` | 270 | Credential management: `CredentialBundle`, `CredentialStore` (workspace-level), `UserCredentialStore` (`~/.openplanter/`), `.env` parsing, interactive prompting |
| `patching.py` | 260 | Codex-style patch parser and applier: `AddFileOp`, `DeleteFileOp`, `UpdateFileOp`, whitespace-normalized subsequence matching |
| `builder.py` | 195 | Engine/model factory: provider inference from model name, model construction, `build_engine()`, `build_model_factory()` for sub-agent creation |
| `settings.py` | 115 | Persistent workspace defaults: `PersistentSettings`, `SettingsStore` (`.openplanter/settings.json`), per-provider model defaults |
| `demo.py` | 110 | Demo mode: `DemoCensor` replaces workspace path segments with block characters, `DemoRenderHook` intercepts Rich renderables before display |
| `config.py` | 103 | `AgentConfig` dataclass with ~30 fields, `from_env()` factory reading `OPENPLANTER_*` environment variables |
| `replay_log.py` | 95 | `ReplayLogger`: delta-encoded JSONL log of every LLM API call for replay/debugging, child loggers for subtask conversations |
| `__init__.py` | 35 | Public API re-exports |

### `tests/` -- Test Suite (~8,000 lines, 25 files)

Tests use pytest with no external test dependencies. `conftest.py` provides
`_tc()` shorthand for `ToolCall` creation and `mock_openai_stream` /
`mock_anthropic_stream` helpers that convert non-streaming response dicts into
SSE event lists for monkey-patching. Key test files:

- `test_user_stories.py` (1115 lines) -- end-to-end user story scenarios
- `test_model_complex.py` (836 lines) -- provider model edge cases
- `test_engine_complex.py` (645 lines) -- recursive delegation, budget, judging
- `test_integration.py` (642 lines) -- full solve cycles with `ScriptedModel`
- `test_patching.py` / `test_patching_complex.py` -- Codex patch format
- `test_live_models.py` / `test_integration_live.py` -- live API tests (skipped by default)

### `skills/openplanter/` -- Claude Code Skill

Investigation methodology extracted for use as a Claude Code skill. Contains:
- `SKILL.md` -- Epistemic framework, entity resolution protocol, Admiralty
  confidence tiers, ACH methodology, output standards
- `scripts/` -- Python stdlib-only helpers: `init_workspace.py`,
  `entity_resolver.py`, `cross_reference.py`, `evidence_chain.py`,
  `confidence_scorer.py`
- `references/` -- Entity resolution patterns, investigation methodology,
  output templates

## Named Entities

### Core Types

- `RLMEngine` -- The recursive language model engine. Central class that owns
  the step loop, tool dispatch, sub-agent spawning, and budget management.
- `BaseModel` -- Protocol defining the LLM interface: `create_conversation`,
  `complete`, `append_assistant_turn`, `append_tool_results`.
- `OpenAICompatibleModel` -- Covers OpenAI, OpenRouter, and Cerebras providers.
  Handles SSE streaming, reasoning effort, strict tool schemas.
- `AnthropicModel` -- Anthropic-specific model with thinking/adaptive mode,
  content blocks, and tool_use blocks.
- `Conversation` -- Opaque message list wrapper. Provider-specific internals
  hidden behind a common interface.
- `ModelTurn` -- One assistant response: tool calls, text, stop reason, token
  counts, raw response for round-tripping.
- `ToolCall` / `ToolResult` -- Request/response pair for tool invocations.
- `WorkspaceTools` -- All 19 tool implementations, workspace-sandboxed.
- `AgentConfig` -- ~30-field dataclass for all runtime configuration.
- `ExternalContext` -- Accumulates observations across recursive calls for
  cross-depth context sharing.
- `SessionRuntime` -- Wraps `RLMEngine` with session persistence, event
  logging, and replay capture.
- `SessionStore` -- Filesystem-backed session storage under `.openplanter/sessions/`.
- `CredentialBundle` -- Six API keys (OpenAI, Anthropic, OpenRouter, Cerebras,
  Exa, Voyage) with merge and serialization logic.
- `PersistentSettings` -- Workspace-level defaults for model and reasoning effort.
- `ReplayLogger` -- Delta-encoded JSONL logger for LLM call replay.

### Key Functions

- `build_engine()` in `builder.py` -- Constructs `RLMEngine` from `AgentConfig`.
- `build_model_factory()` -- Returns a callable that creates models by name,
  used by the engine to spawn sub-agents at different tiers.
- `build_system_prompt()` in `prompts.py` -- Assembles the system prompt from
  base + optional recursive/acceptance/demo sections.
- `get_tool_definitions()` in `tool_defs.py` -- Returns filtered tool schemas
  based on mode (recursive vs flat, with/without acceptance criteria).
- `_solve_recursive()` -- The inner step loop in `RLMEngine`. Manages the
  conversation, dispatches tool calls, handles budget warnings, context
  condensation, and plan injection.
- `_model_tier()` -- Maps model names to capability tiers (1=opus, 2=sonnet,
  3=haiku) for delegation policy enforcement.
- `_lowest_tier_model()` -- Returns the cheapest model name for `execute` calls.
- `infer_provider_for_model()` -- Regex-based provider inference from model name.

## Architectural Invariants

1. **All file access is workspace-sandboxed.** `WorkspaceTools._resolve_path()`
   raises `ToolError` if a resolved path escapes the workspace root. There are
   no exceptions to this.

2. **Existing files cannot be overwritten without being read first.**
   `write_file()` blocks writes to existing files not in `_files_read`. This
   prevents the LLM from destroying workspace data by hallucinating content.

3. **Sub-agents can only delegate DOWN the model tier chain.** `subtask()`
   enforces that the requested model's tier is >= the current model's tier
   (opus -> sonnet -> haiku, never haiku -> opus). This prevents cost explosions.

4. **No SDK dependencies for LLM providers.** All HTTP is raw
   `urllib.request` with manual JSON serialization and SSE parsing. This is
   deliberate -- it eliminates version conflicts and keeps the dependency
   footprint minimal.

5. **Shell commands cannot use heredocs or interactive programs.** Runtime
   policy in `WorkspaceTools._check_shell_policy()` blocks `<< EOF` syntax
   and programs like `vim`, `nano`, `less`, `top`. These would hang the
   non-interactive environment.

6. **Identical shell commands are blocked after 2 repetitions at the same
   depth.** `_runtime_policy_check()` in the engine prevents infinite retry
   loops.

7. **Tool definitions are the single source of truth.** `TOOL_DEFINITIONS` in
   `tool_defs.py` is the canonical list. `to_openai_tools()` and
   `to_anthropic_tools()` are pure converters. Tool behavior in `engine.py`
   must match the schemas in `tool_defs.py`.

8. **Session state is append-only JSONL.** Events are appended to
   `events.jsonl`, never rewritten. State snapshots go to `state.json`.
   Replay logs go to `replay.jsonl` with delta encoding.

## Layer Boundaries

### CLI Entry (`__main__.py`) -> Engine (`engine.py`)

The CLI parses arguments, resolves credentials through a 5-level cascade
(CLI flags > env vars > `.env` file > workspace store > user store), builds
an `AgentConfig`, and calls `build_engine()`. It never touches the model or
tools directly. The `ChatContext` dataclass bundles `SessionRuntime`, `AgentConfig`,
and `SettingsStore` for the TUI layer.

### Engine (`engine.py`) -> Model (`model.py`)

The engine interacts with models exclusively through the `BaseModel` protocol.
It never constructs HTTP requests or parses provider-specific responses.
Streaming deltas are forwarded via the `on_content_delta` callback, which
the engine installs only for depth-0 calls.

### Engine (`engine.py`) -> Tools (`tools.py`)

Tool dispatch happens in `_apply_tool_call()`, a ~200-line method that
pattern-matches on tool name and delegates to `WorkspaceTools` methods.
Tools return `(is_final: bool, observation: str)`. The engine clips
observations to `max_observation_chars` and appends them to the conversation.

### Session Layer (`runtime.py`) -> Engine

`SessionRuntime.solve()` wraps `RLMEngine.solve_with_context()` with event
persistence, replay logging, and patch artifact capture. It manages the
`ExternalContext` across multiple `solve()` calls within a session.

## Cross-Cutting Concerns

### Credential Management

Six API keys flow through a 5-level resolution cascade defined in
`_load_credentials()` in `__main__.py`:

1. CLI flags (`--openai-api-key`, etc.)
2. Environment variables (`OPENAI_API_KEY` or `OPENPLANTER_OPENAI_API_KEY`)
3. `.env` file in workspace root
4. Workspace credential store (`.openplanter/credentials.json`)
5. User credential store (`~/.openplanter/credentials.json`)

Higher levels override lower. Credential files are chmod 600.

### Demo Mode

When `--demo` is active, three mechanisms cooperate:
1. `DemoCensor` replaces workspace path segments (excluding generic parts
   like "Users", "Desktop") with block characters in all TUI output.
2. `DemoRenderHook` intercepts Rich renderables before display.
3. The system prompt instructs the LLM to censor entity names in its own
   output using block characters.

### Context Condensation

When input tokens exceed 75% of the model's context window, the engine calls
`condense_conversation()` on the model. Both `OpenAICompatibleModel` and
`AnthropicModel` implement this by replacing old tool result contents with
`[earlier tool output condensed]`, preserving required IDs for API compliance.

### Budget Management

The engine injects timestamp, step counter, and context usage tags into the
first tool result of each step. When the step budget falls below 50%, a
warning is appended. Below 25%, a critical warning demands immediate output.
The system prompt reinforces these constraints.

### Parallel Execution

`subtask` and `execute` tool calls are dispatched in parallel via
`ThreadPoolExecutor`. A parallel write conflict detector in `WorkspaceTools`
prevents sibling sub-agents from writing to the same file. All other tools
run sequentially.

### Session Persistence

Each session lives under `.openplanter/sessions/{session_id}/` and contains:
- `metadata.json` -- timestamps, workspace path
- `state.json` -- serialized `ExternalContext` observations
- `events.jsonl` -- append-only trace of all objectives, steps, and results
- `replay.jsonl` -- delta-encoded LLM call log for exact replay
- `artifacts/` -- captured patches and other artifacts
- `*.plan.md` -- investigation plans (newest is auto-injected into context)

### Acceptance Criteria

When enabled, `subtask` and `execute` require an `acceptance_criteria`
parameter. After the child agent completes, a lightweight judge model
(cheapest tier) evaluates the result against the criteria and appends
`PASS` or `FAIL`. The system prompt includes the IMPLEMENT-THEN-VERIFY
pattern to enforce uncorrelated verification.

## Common Questions

**Where do I add a new tool?**
1. Add the schema to `TOOL_DEFINITIONS` in `tool_defs.py`.
2. Implement the method in `WorkspaceTools` in `tools.py`.
3. Add the dispatch case in `_apply_tool_call()` in `engine.py`.

**Where do I add a new LLM provider?**
1. Add the model class in `model.py` (implement `BaseModel` protocol).
2. Add provider regex to `builder.py` and extend `build_engine()` / `build_model_factory()`.
3. Add credential fields to `CredentialBundle`, `AgentConfig`, and `__main__.py`.
4. Add default model to `PROVIDER_DEFAULT_MODELS` in `config.py`.

**Where is the system prompt?**
`prompts.py`. It is assembled from four sections: `SYSTEM_PROMPT_BASE` (always),
`RECURSIVE_SECTION` (if recursive mode), `ACCEPTANCE_CRITERIA_SECTION` (if
acceptance criteria enabled), `DEMO_SECTION` (if demo mode).

**How does sub-agent model routing work?**
`_model_tier()` assigns tiers (1=opus, 2=sonnet, 3=haiku). `subtask` can
request any model at equal or lower tier. `execute` always uses
`_lowest_tier_model()` (haiku for Claude, same model for OpenAI). The
`model_factory` in `RLMEngine` creates model instances on demand, cached by
`(model_name, reasoning_effort)` tuple.

**How do I run tests?**
`python -m pytest tests/` (skip live tests with `--ignore=tests/test_live_models.py
--ignore=tests/test_integration_live.py`). Tests use `ScriptedModel` and
monkey-patched `_http_stream_sse` -- no API keys required.

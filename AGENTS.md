# OpenPlanter

A recursive-language-model investigation agent with a terminal UI. OpenPlanter ingests heterogeneous datasets (corporate registries, campaign finance records, lobbying disclosures, government contracts), resolves entities across them, and surfaces non-obvious connections through evidence-backed analysis. It operates autonomously with file I/O, shell execution, web search, and recursive sub-agent delegation. Open-source alternative to Palantir for investigative journalists, NGOs, OSINT analysts, and researchers.

## Commands

- **Install**: `pip install -e .`
- **Test (offline)**: `python -m pytest tests/ --ignore=tests/test_live_models.py --ignore=tests/test_integration_live.py`
- **Test (full, requires API keys)**: `python -m pytest tests/`
- **Run (TUI)**: `openplanter-agent --workspace DIR`
- **Run (headless)**: `openplanter-agent --task "OBJECTIVE" --workspace DIR`
- **Configure keys**: `openplanter-agent --configure-keys`
- **Docker**: `docker compose up` (mounts `./workspace`, reads `.env`)

## Structure

- `agent/` -- Core agent package (entry point, engine, tools, TUI)
  - `__main__.py` -- CLI entry point and REPL
  - `engine.py` -- Recursive language model engine (sub-agent spawning via `subtask`/`execute`)
  - `runtime.py` -- Session persistence and lifecycle
  - `model.py` -- Provider-agnostic LLM abstraction (OpenAI, Anthropic, OpenRouter, Cerebras)
  - `builder.py` -- Engine/model factory
  - `tools.py` -- 19 workspace tools (file ops, shell, web search, planning, delegation)
  - `tool_defs.py` -- Tool JSON schemas
  - `prompts.py` -- System prompt construction (investigation methodology, entity resolution protocol)
  - `config.py` -- `AgentConfig` dataclass with env var resolution
  - `credentials.py` -- Credential management (5-tier priority: CLI > env > .env > workspace store > user store)
  - `tui.py` -- Rich terminal UI with prompt_toolkit
  - `demo.py` -- Demo mode (entity/path censoring)
  - `patching.py` -- File patching utilities
  - `settings.py` -- Persistent workspace settings
  - `replay_log.py` -- Session replay logging
- `tests/` -- Unit and integration tests (~8,600 LOC, 24 test files)
  - `test_live_models.py`, `test_integration_live.py` -- Live API tests (skip in CI)
  - All other `test_*.py` -- Offline unit tests
- `skills/openplanter/` -- Investigation methodology skill for Claude Code
  - `scripts/` -- Stdlib-only Python scripts (entity resolver, cross-reference, evidence chain, confidence scorer, workspace init)
  - `references/` -- Entity resolution patterns, investigation methodology, output templates

## Conventions

- **Python 3.10+** required. No runtime dependencies beyond `rich`, `prompt_toolkit`, and `pyfiglet`.
- **TUI**: `rich` for rendering, `prompt_toolkit` for input. No curses.
- **Skill scripts**: Python stdlib only. Zero external dependencies. Located in `skills/openplanter/scripts/`.
- **Dataclasses with `slots=True`**: All config and data containers use `@dataclass(slots=True)`.
- **Provider abstraction**: `model.py` handles all LLM providers behind a unified interface. Never import provider SDKs directly in other modules.
- **Env var naming**: All runtime settings accept `OPENPLANTER_*` prefix (e.g. `OPENPLANTER_MAX_DEPTH=8`). API keys also accept standard names (e.g. `OPENAI_API_KEY`).
- **Session data**: Stored in `.openplanter/` within the workspace directory.
- **Type hints**: Use `from __future__ import annotations` for deferred evaluation. Union syntax: `str | None`, not `Optional[str]`.
- **Test isolation**: Live API tests are in dedicated files (`test_live_models.py`, `test_integration_live.py`) so they can be excluded with `--ignore`.

## Provider Configuration

| Provider | Default Model | Env Var | Base URL Override |
|----------|---------------|---------|-------------------|
| OpenAI | `gpt-5.2` | `OPENAI_API_KEY` | `OPENPLANTER_OPENAI_BASE_URL` |
| Anthropic | `claude-opus-4-6` | `ANTHROPIC_API_KEY` | `OPENPLANTER_ANTHROPIC_BASE_URL` |
| OpenRouter | `anthropic/claude-sonnet-4-5` | `OPENROUTER_API_KEY` | `OPENPLANTER_OPENROUTER_BASE_URL` |
| Cerebras | `qwen-3-235b-a22b-instruct-2507` | `CEREBRAS_API_KEY` | `OPENPLANTER_CEREBRAS_BASE_URL` |

**Service keys**: `EXA_API_KEY` (Exa web search), `VOYAGE_API_KEY` (Voyage embeddings).

Key resolution priority (highest wins):
1. CLI flags (`--openai-api-key`, etc.)
2. Environment variables (`OPENAI_API_KEY` or `OPENPLANTER_OPENAI_API_KEY`)
3. `.env` file in the workspace
4. Workspace credential store (`.openplanter/credentials.json`)
5. User credential store (`~/.openplanter/credentials.json`)

## Boundaries

- **Always**: Run `python -m pytest tests/ --ignore=tests/test_live_models.py --ignore=tests/test_integration_live.py` before committing
- **Always**: Maintain provider abstraction -- all LLM calls go through `model.py`
- **Always**: Keep skill scripts stdlib-only (no pip dependencies in `skills/`)
- **Ask**: Before adding new runtime dependencies to `pyproject.toml`
- **Ask**: Before changing the tool schema format in `tool_defs.py` (affects all providers)
- **Ask**: Before modifying credential resolution order in `credentials.py`
- **Never**: Commit API keys, `.env` files, or `credentials.json`
- **Never**: Import provider-specific SDKs outside `model.py`
- **Never**: Break the `--ignore` convention for live tests (CI must run without API keys)

## Troubleshooting

- **No API keys found**: Run `openplanter-agent --configure-keys` or set env vars. Keys are resolved from 5 sources (see Provider Configuration).
- **Docker can't find keys**: Copy `.env.example` to `.env` and fill in keys. The container reads `.env` via `env_file` in `docker-compose.yml`.
- **Tests fail with import errors**: Ensure editable install with `pip install -e .` from the project root.
- **Live tests fail**: Expected if no API keys are set. Use `--ignore=tests/test_live_models.py --ignore=tests/test_integration_live.py` to skip them.
- **Session state corruption**: Delete `.openplanter/` in the workspace directory to reset.

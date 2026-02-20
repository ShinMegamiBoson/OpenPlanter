# OpenPlanter

Recursive LLM investigation agent for entity resolution across heterogeneous datasets (corporate registries, campaign finance, lobbying disclosures). Builds evidence chains through autonomous sub-agent delegation. Supports 4 providers: OpenAI, Anthropic, OpenRouter, Cerebras.

## Stack

Python 3.10+, rich, prompt_toolkit, pyfiglet. Skill scripts use stdlib only (zero deps).

## Commands

- **Install**: `pip install -e .`
- **Run**: `openplanter-agent --workspace DIR`
- **Headless**: `openplanter-agent --task "objective" --workspace DIR`
- **Test**: `python -m pytest tests/ --ignore=tests/test_live_models.py --ignore=tests/test_integration_live.py`
- **Docker**: `docker compose up`

## Structure

- `agent/` -- core engine, provider abstraction, tools, TUI
- `tests/` -- unit and integration tests
- `skills/openplanter/` -- Claude Code skill (stdlib-only scripts)

## Key Files

| File | Purpose |
|------|---------|
| `agent/engine.py` | Recursive investigation engine |
| `agent/model.py` | Provider-agnostic LLM abstraction |
| `agent/tools.py` | 19 workspace tools (file I/O, shell, web, delegation) |
| `agent/prompts.py` | System prompt construction |
| `agent/tui.py` | Rich terminal UI |

## Conventions

- Agent code uses rich/prompt_toolkit for TUI
- Skill scripts use Python stdlib only -- no third-party imports
- `.claude/settings.json` disables AI commit attribution

## Provider Config

| Provider | Env Var |
|----------|---------|
| OpenAI | `OPENAI_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |
| OpenRouter | `OPENROUTER_API_KEY` |
| Cerebras | `CEREBRAS_API_KEY` |

Additional: `EXA_API_KEY` (web search), `VOYAGE_API_KEY` (embeddings). All keys support `OPENPLANTER_` prefix.

## Stop Checklist

Before completing a task, check each item:

- Did you take advantage of ALL applicable skills?
- Did you take advantage of ALL applicable subagents?
- Don't guess about the state of the code or any APIs unless explicitly asked to
- If something doesn't work, your first priority must always be determine WHY it doesn't work unless doing so is impossible
- If you have written or modified code, ensure all components have been deterministically validated to be functioning as intended via breaking up any given process or change into the most granular steps possible and validating the conditions at the entry and exit of each of those steps
- Do not ask the user to perform an action to validate the correctness of your work, you need to validate it yourself
- If the feature is functionally complete, create a temporary commit now. We'll squash the commits later as needed.

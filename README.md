# OpenPlanter

A recursive-language-model investigation agent with a terminal UI. OpenPlanter ingests heterogeneous datasets — corporate registries, campaign finance records, lobbying disclosures, government contracts, and more — resolves entities across them, and surfaces non-obvious connections through evidence-backed analysis. It operates autonomously with file I/O, shell execution, web search, and recursive sub-agent delegation.

## Quickstart

```bash
# Install
pip install -e .

# Configure API keys (interactive prompt)
openplanter-agent --configure-keys

# Launch the TUI
openplanter-agent --workspace /path/to/your/project
```

Or run a single task headlessly:

```bash
openplanter-agent --task "Cross-reference vendor payments against lobbying disclosures and flag overlaps" --workspace ./data
```

### Docker

```bash
# Add your API keys to .env, then:
docker compose up
```

The container mounts `./workspace` as the agent's working directory.

## Supported Providers

| Provider | Default Model | Env Var |
|----------|---------------|---------|
| OpenAI | `gpt-5.2` | `OPENAI_API_KEY` |
| Anthropic | `claude-opus-4-6` | `ANTHROPIC_API_KEY` |
| OpenRouter | `anthropic/claude-sonnet-4-5` | `OPENROUTER_API_KEY` |
| Cerebras | `qwen-3-235b-a22b-instruct-2507` | `CEREBRAS_API_KEY` |
| Ollama | `llama3.2` | (none — local) |

### Local Models (Ollama)

[Ollama](https://ollama.com) runs models locally with no API key. Install Ollama, pull a model (`ollama pull llama3.2`), then:

```bash
openplanter-agent --provider ollama
openplanter-agent --provider ollama --model mistral
openplanter-agent --provider ollama --list-models
```

The base URL defaults to `http://localhost:11434/v1` and can be overridden with `OPENPLANTER_OLLAMA_BASE_URL` or `--base-url`.

Additional service keys: `EXA_API_KEY` (web search), `VOYAGE_API_KEY` (embeddings).

All keys can also be set with an `OPENPLANTER_` prefix (e.g. `OPENPLANTER_OPENAI_API_KEY`), via `.env` files in the workspace, or via CLI flags.

## Agent Tools

The agent has access to 19 tools, organized around its investigation workflow:

**Dataset ingestion & workspace** — `list_files`, `search_files`, `repo_map`, `read_file`, `write_file`, `edit_file`, `hashline_edit`, `apply_patch` — load, inspect, and transform source datasets; write structured findings.

**Shell execution** — `run_shell`, `run_shell_bg`, `check_shell_bg`, `kill_shell_bg` — run analysis scripts, data pipelines, and validation checks.

**Web** — `web_search` (Exa), `fetch_url` — pull public records, verify entities, and retrieve supplementary data.

**Planning & delegation** — `think`, `subtask`, `execute`, `list_artifacts`, `read_artifact` — decompose investigations into focused sub-tasks, each with acceptance criteria and independent verification.

In **recursive mode** (the default), the agent spawns sub-agents via `subtask` and `execute` to parallelize entity resolution, cross-dataset linking, and evidence-chain construction across large investigations.

## CLI Reference

```
openplanter-agent [options]
```

### Workspace & Session

| Flag | Description |
|------|-------------|
| `--workspace DIR` | Workspace root (default: `.`) |
| `--session-id ID` | Use a specific session ID |
| `--resume` | Resume the latest (or specified) session |
| `--list-sessions` | List saved sessions and exit |

### Model Selection

| Flag | Description |
|------|-------------|
| `--provider NAME` | `auto`, `openai`, `anthropic`, `openrouter`, `cerebras`, `ollama` |
| `--model NAME` | Model name or `newest` to auto-select |
| `--reasoning-effort LEVEL` | `low`, `medium`, `high`, or `none` |
| `--list-models` | Fetch available models from the provider API |

### Execution

| Flag | Description |
|------|-------------|
| `--task OBJECTIVE` | Run a single task and exit (headless) |
| `--recursive` | Enable recursive sub-agent delegation |
| `--acceptance-criteria` | Judge subtask results with a lightweight model |
| `--max-depth N` | Maximum recursion depth (default: 4) |
| `--max-steps N` | Maximum steps per call (default: 100) |
| `--timeout N` | Shell command timeout in seconds (default: 45) |

### UI

| Flag | Description |
|------|-------------|
| `--no-tui` | Plain REPL (no colors or spinner) |
| `--headless` | Non-interactive mode (for CI) |
| `--demo` | Censor entity names and workspace paths in output |

### Persistent Defaults

Use `--default-model`, `--default-reasoning-effort`, or per-provider variants like `--default-model-openai` to save workspace defaults to `.openplanter/settings.json`. View them with `--show-settings`.

## TUI Commands

Inside the interactive REPL:

| Command | Action |
|---------|--------|
| `/model` | Show current model and provider |
| `/model NAME` | Switch model (aliases: `opus`, `sonnet`, `gpt5`, etc.) |
| `/model NAME --save` | Switch and persist as default |
| `/model list [all]` | List available models |
| `/reasoning LEVEL` | Change reasoning effort |
| `/status` | Show session status and token usage |
| `/clear` | Clear the screen |
| `/quit` | Exit |

## Configuration

Keys are resolved in this priority order (highest wins):

1. CLI flags (`--openai-api-key`, etc.)
2. Environment variables (`OPENAI_API_KEY` or `OPENPLANTER_OPENAI_API_KEY`)
3. `.env` file in the workspace
4. Workspace credential store (`.openplanter/credentials.json`)
5. User credential store (`~/.openplanter/credentials.json`)

All runtime settings can also be set via `OPENPLANTER_*` environment variables (e.g. `OPENPLANTER_MAX_DEPTH=8`).

## Project Structure

```
agent/
  __main__.py    CLI entry point and REPL
  engine.py      Recursive language model engine
  runtime.py     Session persistence and lifecycle
  model.py       Provider-agnostic LLM abstraction
  builder.py     Engine/model factory
  tools.py       Workspace tool implementations
  tool_defs.py   Tool JSON schemas
  prompts.py     System prompt construction
  config.py      Configuration dataclass
  credentials.py Credential management
  tui.py         Rich terminal UI
  demo.py        Demo mode (output censoring)
  patching.py    File patching utilities
  settings.py    Persistent settings
tests/           Unit and integration tests
```

## Development

```bash
# Install in editable mode
pip install -e .

# Run tests
python -m pytest tests/

# Skip live API tests
python -m pytest tests/ --ignore=tests/test_live_models.py --ignore=tests/test_integration_live.py
```

Requires Python 3.10+. Dependencies: `rich`, `prompt_toolkit`, `pyfiglet`.

## License

See [VISION.md](VISION.md) for the project's design philosophy and roadmap.

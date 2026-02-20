# Contributing to OpenPlanter

Thanks for your interest in contributing. This guide covers setup, conventions, and the pull request process.

## Development Setup

```bash
# Clone the repository
git clone https://github.com/ShinMegamiBoson/OpenPlanter.git
cd OpenPlanter

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install in editable mode with dev dependencies
pip install -e ".[dev]"
```

Requires Python 3.10+.

## Running Tests

```bash
# Full test suite (excludes live API tests)
pytest tests/ --ignore=tests/test_live_models.py --ignore=tests/test_integration_live.py

# Single test file
pytest tests/test_engine.py

# With verbose output
pytest tests/test_tools.py -v
```

Live API tests require real provider keys and are excluded by default. To run them:

```bash
pytest tests/test_live_models.py
```

## Linting and Type Checking

```bash
# Lint
ruff check agent/ tests/

# Auto-fix lint issues
ruff check --fix agent/ tests/

# Type check
mypy agent/
```

## Pull Request Process

1. **Fork and branch.** Create a feature branch from `main`:
   ```bash
   git checkout -b feat/your-feature main
   ```

2. **Keep changes focused.** One PR should do one thing. If you find an unrelated issue while working, file it separately.

3. **Write tests.** If your change alters behaviour, add or update tests. Prefer fast unit tests over integration tests.

4. **Run checks locally** before pushing:
   ```bash
   ruff check agent/ tests/
   mypy agent/
   pytest tests/ --ignore=tests/test_live_models.py --ignore=tests/test_integration_live.py
   ```

5. **Write a clear commit message.** Use the format `<type>: <description>` where type is one of: `feat`, `fix`, `refactor`, `docs`, `chore`, `test`. Keep the first line under 72 characters.

6. **Open the PR** against `main` with a description of what changed and why.

## Branch Naming

Use the pattern `<type>/<short-description>`:

- `feat/async-model-support`
- `fix/sse-flush-on-eof`
- `docs/contributing-guide`
- `refactor/tool-dispatch-registry`

## What to Contribute

Good first contributions:

- Bug fixes with a failing test
- Documentation improvements
- New test coverage for untested paths
- Performance improvements with benchmarks

Larger contributions (new tools, provider integrations, architectural changes) benefit from opening an issue first to discuss the approach.

## Code of Conduct

This project follows the [Contributor Covenant](https://www.contributor-covenant.org/version/2/1/code_of_conduct/), version 2.1. In short:

- Be respectful and constructive.
- No harassment, trolling, or personal attacks.
- Assume good intent; ask before assuming.
- Maintainers may remove contributions or ban participants who violate these standards.

Report issues to the maintainers via GitHub Issues.

## License

By contributing, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE).

.PHONY: help lint format type test clean install

help:
	@echo "OpenPlanter development targets:"
	@echo "  make install        Install dev dependencies"
	@echo "  make lint           Run ruff linter"
	@echo "  make format         Format code with ruff"
	@echo "  make type           Run mypy type checker"
	@echo "  make test           Run pytest"
	@echo "  make clean          Remove build artifacts"

install:
	pip install -e ".[dev]"

lint:
	ruff check agent/ tests/

format:
	ruff format agent/ tests/

type:
	mypy agent/

test:
	pytest tests/ --ignore=tests/test_live_models.py --ignore=tests/test_integration_live.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name *.egg-info -exec rm -rf {} + 2>/dev/null || true

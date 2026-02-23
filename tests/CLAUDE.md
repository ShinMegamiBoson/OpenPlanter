# Tests Directory

pytest test suite organized by test type.

## Structure

```
tests/
├── conftest.py           # Global fixtures
├── unit/                 # Single component tests
├── integration/          # Multiple components together
└── e2e/                  # Full system tests
```

## Running Tests

```bash
# All tests
pytest tests/ -v

# By type
pytest tests/unit/ -v
pytest tests/integration/ -v
pytest tests/e2e/ -v

# By plan (if using plan markers)
pytest --plan N tests/

# Single test
pytest tests/unit/test_example.py::TestClass::test_method -v
```

## Test Types

| Type | Purpose | Speed |
|------|---------|-------|
| **Unit** | Single class/function | Fast |
| **Integration** | Multiple components | Medium |
| **E2E** | Full system | Slow |

## Conventions

1. **Use fixtures** from `conftest.py` for common setup
2. **Real tests preferred** - Avoid mocks when possible
3. **Fast execution** - Unit suite should run in seconds
4. **Mark with plan** - Use `@pytest.mark.plans(N)` to link to plans

## Adding Tests

1. Add unit tests for new logic
2. Add integration test if multiple components involved
3. Mark tests with plan number if implementing a plan
4. Run full suite before PR: `pytest tests/ -v`

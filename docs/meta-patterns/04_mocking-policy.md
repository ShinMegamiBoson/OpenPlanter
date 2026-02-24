# Pattern: Mocking Policy

## Philosophy

**Real tests, not mock tests.** Mocks can hide real failures. Prefer real dependencies and accept time/cost tradeoffs.

## The Hierarchy

1. **Prefer real** - Use actual dependencies whenever possible
2. **Accept cost** - Real LLM calls cost money; that's acceptable for realistic tests
3. **Mock external only** - When mocking, mock external boundaries (APIs, network)
4. **Never mock internal** - Don't mock your own code; if you need to, the design is wrong
5. **Justify exceptions** - Every mock needs explicit justification

## When Mocking is Acceptable

| Scenario | Mock OK? | Example |
|----------|----------|---------|
| External API in unit test | Yes | Mock HTTP responses |
| LLM in smoke tests | Yes | Speed/cost for CI |
| Time-dependent tests | Yes | Mock `time.time()` |
| Network errors | Yes | Simulate timeout |
| Your own classes | **No** | Never mock `Ledger`, `Agent` |
| Database in unit test | Sometimes | Prefer in-memory DB |

## Enforcement

### The `# mock-ok:` Comment

Any mock of internal code requires justification:

```python
# mock-ok: Testing error handling when LLM unavailable
@patch("src.agents.agent.Agent._call_llm")
def test_handles_llm_failure(self, mock_llm):
    mock_llm.side_effect = ConnectionError()
    ...
```

Without this comment, CI fails:

```bash
python scripts/check_mock_usage.py --strict
# FAILED: Suspicious mock patterns detected
```

### Suspicious Patterns

The script flags these patterns:

```python
# SUSPICIOUS - mocking your own code
@patch("src.world.ledger.Ledger.transfer")  # Why not use real Ledger?

# SUSPICIOUS - MagicMock as internal return
mock_agent.propose_action.return_value = MagicMock()  # Use real ActionIntent

# OK - mocking external API
@patch("requests.get")  # External, fine to mock

# OK - mocking time
@patch("time.sleep")  # Avoids slow tests
```

### CI Integration

```yaml
mock-usage:
  runs-on: ubuntu-latest
  steps:
    - run: python scripts/check_mock_usage.py --strict
```

## Best Practices

### 1. Use Fixtures Over Mocks

```python
# BAD - mock the database
@patch("src.world.artifacts.ArtifactStore.save")
def test_save(self, mock_save):
    ...

# GOOD - use a real in-memory store
def test_save(self, temp_artifact_store):
    # temp_artifact_store is a real ArtifactStore with temp directory
    ...
```

### 2. Test Boundaries, Not Internals

```python
# BAD - testing implementation
@patch("src.agents.agent.Agent._format_prompt")
def test_prompt_formatting(self, mock_format):
    ...

# GOOD - testing behavior
def test_agent_produces_valid_action(self, real_agent):
    action = real_agent.propose_action(world_state)
    assert action.type in ["noop", "read", "write", "invoke"]
```

### 3. Accept Real LLM Costs

```python
# For realistic tests, use real LLM
@pytest.mark.external
def test_agent_with_real_llm(self, real_config):
    """Costs ~$0.01 per run but catches real issues."""
    runner = SimulationRunner(real_config)
    world = runner.run_sync()
    assert world.tick >= 1
```

### 4. Isolate Mocked Tests

Keep mocked tests separate from real tests:

```
tests/
├── e2e/
│   ├── test_smoke.py      # Mocked LLM (CI)
│   └── test_real_e2e.py   # Real LLM (pre-release)
```

## File-Level Justification

For files that legitimately need many mocks (e.g., testing error paths):

```python
# tests/unit/test_error_handling.py
"""Error handling tests.

# mock-ok: These tests verify error handling when external services fail.
# All mocks are for simulating external failures, not avoiding real code.
"""
```

This blanket justification covers all mocks in the first 20 lines.

## Escape Hatches

### Skip Mock Check for Specific File

If a file has unusual needs:

```python
# tests/special/test_weird_case.py
# mock-ok: File-level justification for unusual test pattern.
# Reason: [explain why this file needs to mock internal code]
```

### Run Without Strict Mode

For local development:

```bash
python scripts/check_mock_usage.py  # Report only, don't fail
```

## The Check Script

```bash
# Report all mock usage
python scripts/check_mock_usage.py

# Fail on suspicious patterns (CI mode)
python scripts/check_mock_usage.py --strict

# Just list files with mocks
python scripts/check_mock_usage.py --list
```

## Origin

Adopted after discovering tests that passed but production failed. The tests mocked internal components, hiding real integration issues. The policy ensures tests exercise real code paths.

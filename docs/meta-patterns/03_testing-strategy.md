# Pattern: Testing Strategy

## Philosophy

**Thin slices over big bang.** Every feature must prove it works end-to-end before declaring success. Unit tests passing with integration failing is a false positive.

**TDD as default.** Tests defined before implementation starts. Escape hatches exist for exploratory work.

**Real over mocked.** Prefer real dependencies. Mock only external APIs or when explicitly justified.

**Explicit markers over directory semantics.** Tests map to features via `@pytest.mark.feature("X")` markers, not directory structure. This enables multi-dimensional associations and is more navigable for AI coding assistants.

## The Thin Slice Principle

### Problem

Without mandatory E2E verification:
- All unit tests pass
- All integration tests pass
- Real system doesn't work
- Issues accumulate until a painful "big bang" integration

### Solution

Every feature (plan) must:
1. Define E2E acceptance criteria
2. Have at least one E2E test that exercises the feature
3. Pass E2E before marking Complete

```
Feature -> E2E Test -> Verified
         (not)
Feature -> Unit Tests Only -> "Complete" -> Broken in production
```

## Test Organization

### Structure

```
tests/
├── conftest.py              # Global fixtures + markers
├── unit/                    # Single-component tests
│   └── test_ledger.py       # Can be marked with @pytest.mark.plans([1, 11])
├── integration/             # Multi-component tests
│   ├── test_escrow.py       # Can be marked with @pytest.mark.plans([6])
│   └── test_*_acceptance.py # Feature acceptance tests (AC-mapped)
└── e2e/                     # Full system tests
    ├── test_smoke.py        # Generic smoke (mocked LLM)
    └── test_real_e2e.py     # Real LLM ($$$)
```

### Why Type-Based with Markers?

| Approach | Pros | Cons |
|----------|------|------|
| Type-first with markers | Explicit associations, queryable, AI-friendly | Requires discipline |
| Plan-first directories | Visual feature mapping | Duplication, lifecycle mismatch |

**Key insight:** Directory structure implies single-dimensional organization. Markers support multi-dimensional associations (a test can belong to multiple acceptance_gates/plans).

For AI coding assistants:
- Explicit metadata (markers) > implicit directory semantics
- `@pytest.mark.feature("escrow")` is greppable and machine-readable
- Feature specs (`acceptance_gates/*.yaml`) remain authoritative source

### Pytest Markers

Register custom markers in `conftest.py`:

```python
# tests/conftest.py
import pytest

def pytest_configure(config):
    config.addinivalue_line(
        "markers", "plans(nums): mark test as belonging to plan number(s)"
    )
    config.addinivalue_line(
        "markers", "feature(name): mark test as belonging to a feature. "
        "Usage: @pytest.mark.feature('escrow') - maps to acceptance_gates/<name>.yaml"
    )
    config.addinivalue_line(
        "markers", "feature_type(type): mark test as 'feature', 'enabler', or 'refactor'"
    )
```

Use in tests:

```python
# tests/integration/test_escrow_acceptance.py
import pytest

@pytest.mark.feature("escrow")
class TestEscrowFeature:
    """Tests mapping to acceptance_gates/escrow.yaml acceptance criteria."""

    def test_ac_1_successful_artifact_sale(self):
        """AC-1: Successful artifact sale via escrow."""
        ...
```

Query with:
```bash
# Run all tests for a feature
pytest --feature escrow tests/

# Run all tests for a plan
pytest --plan 6 tests/

# Or use the check script
python scripts/check_plan_tests.py --plan 6
```

### Acceptance Tests

Feature acceptance tests live in `tests/integration/test_*_acceptance.py`:

| File | Feature | Maps To |
|------|---------|---------|
| `test_escrow_acceptance.py` | escrow | acceptance_gates/escrow.yaml |
| `test_rate_limiting_acceptance.py` | rate_limiting | acceptance_gates/rate_limiting.yaml |
| `test_agent_loop_acceptance.py` | agent_loop | acceptance_gates/agent_loop.yaml |

**Naming convention:** Test functions map to acceptance criteria:
- `test_ac_1_*` → AC-1 from feature spec
- `test_ac_2_*` → AC-2 from feature spec

## TDD Policy

### Default: Tests Before Implementation

1. **Define tests** in plan's `## Required Tests` section
2. **Create test stubs** (they will fail)
3. **Implement** until tests pass
4. **Add acceptance test** with `@pytest.mark.feature("X")` marker
5. **Verify with script** before marking complete

### Escape Hatch 1: Exploratory Work

For plans that require exploration before test definition:

1. Start implementation without tests
2. **Before completion**, define and implement tests
3. Document why TDD was skipped in the plan

```markdown
## Notes

TDD skipped: Required exploration to understand the API surface.
Tests added post-implementation: test_foo.py, test_bar.py
```

### Escape Hatch 2: Enabler Plans

Enabler plans (tooling, process, documentation) may not have feature E2E tests:

```bash
# Use --skip-e2e for enabler plans
python scripts/complete_plan.py --plan 32 --skip-e2e
```

Mark in plan:
```markdown
**Type:** Enabler (no feature E2E required)
```

## Plan Types

| Type | Definition | E2E Required? | Example |
|------|------------|---------------|---------|
| **Feature** | Delivers user-visible capability | Yes | Rate limiting, Escrow |
| **Enabler** | Improves dev process | No (validation script instead) | Dev tooling, ADR governance |
| **Refactor** | Changes internals, not behavior | Existing E2E must pass | Terminology cleanup |

## Enforcement Mechanisms

### 1. CI Gates Plan Tests

```yaml
# .github/workflows/ci.yml
plan-tests:
  runs-on: ubuntu-latest
  # NO continue-on-error - this is strict
  steps:
    - run: python scripts/check_plan_tests.py --all
```

### 2. Completion Script Requires Tests

```bash
# This runs E2E tests before allowing completion
python scripts/complete_plan.py --plan N
```

The script:
1. Runs unit tests
2. Runs E2E smoke tests
3. Checks doc-coupling
4. Records evidence in plan file
5. Only then updates status to Complete

### 3. Plan Test Definition Validation

The `check_plan_tests.py` script validates:
- Plans with status "In Progress" or "Complete" have tests defined
- Defined tests exist in the test files
- Defined tests pass

### 4. Pre-Merge Checklist

Before merging a plan PR:

```bash
# All must pass
pytest tests/ -v
python scripts/check_plan_tests.py --plan N
python scripts/complete_plan.py --plan N --dry-run
```

## Writing Good Acceptance Tests

### Feature Acceptance Test Template

```python
# tests/integration/test_feature_acceptance.py
"""Feature acceptance tests for [feature] - maps to acceptance_gates/[feature].yaml.

Run with: pytest --feature [feature] tests/
"""

import pytest

@pytest.mark.feature("[feature]")
class TestFeatureFeature:
    """Tests mapping to acceptance_gates/[feature].yaml acceptance criteria."""

    def test_ac_1_description(self, fixture):
        """AC-1: [Acceptance criterion from feature spec]."""
        # Arrange
        ...

        # Act
        ...

        # Assert - acceptance criterion assertions
        assert [acceptance criterion condition]

    def test_ac_2_description(self, fixture):
        """AC-2: [Another acceptance criterion]."""
        ...

@pytest.mark.feature("[feature]")
class TestFeatureEdgeCases:
    """Additional edge case tests for [feature] robustness."""

    def test_edge_case(self):
        """Edge case not in feature spec."""
        ...
```

### What Makes a Good Acceptance Test

| Good | Bad |
|------|-----|
| Tests user-visible behavior | Tests internal implementation |
| Maps to feature spec ACs | Arbitrary test scenarios |
| Minimal mocking | Mocks everything |
| Specific assertions | "Doesn't crash" only |
| Documents the acceptance criteria | Cryptic test names |
| Uses `@pytest.mark.feature()` | No markers (hidden association) |

## Mocking Policy

See [Mocking Policy](./04_mocking-policy.md) for details.

**Summary:**
- No mocks by default
- Mock external APIs (LLM, network) when needed for speed/cost
- Require `# mock-ok: <reason>` comment for justified mocks
- CI fails on suspicious mock patterns without justification

## Metrics

Track testing health with:

```bash
# Plan test coverage
python scripts/check_plan_tests.py --list

# Mock usage
python scripts/check_mock_usage.py

# Overall coverage (if using coverage.py)
pytest --cov=src tests/
```

## Migration from Big Bang

If your codebase has accumulated untested "complete" plans:

1. **Audit**: Run `python scripts/plan_progress.py --summary`
2. **Identify gaps**: Plans marked Complete with 0% test progress
3. **Prioritize**: Focus on high-priority plans first
4. **Add acceptance tests**: Create `tests/integration/test_*_acceptance.py` with markers
5. **Update verification**: Run `complete_plan.py` to record evidence

## Origin

Adopted after discovering multiple "Complete" plans had never been E2E tested. The cost of late integration (debugging across multiple accumulated changes) exceeded the overhead of per-feature E2E verification.

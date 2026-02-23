# Pattern: Acceptance Gate Linkage

How to structure relationships between ADRs, acceptance gates, code, tests, and documentation for full traceability.

> **Note:** This pattern uses the `acceptance_gates/` directory and `features.yaml` filename for historical reasons.
> The authoritative term is "acceptance gate" - see [META-ADR-0001](../adr/0001-acceptance-gate-terminology.md).
>
> **Status:** `features.yaml` as described here is not yet implemented. The project uses
> individual `acceptance_gates/*.yaml` files (Pattern 13) and `scripts/relationships.yaml`
> (Pattern 09) instead. This pattern describes the intended unified linkage architecture.

## Complete Linkage Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              CURRENT STATE (Problematic)                         │
└─────────────────────────────────────────────────────────────────────────────────┘

    ┌───────────┐                                           ┌───────────┐
    │   ADRs    │                                           │   Plans   │
    │ (5 exist) │                                           │(34 exist) │
    └─────┬─────┘                                           └─────┬─────┘
          │                                                       │
          │ governance.yaml                                       │ (weak soft
          │ (SPARSE: only 5 files!)                               │  coupling)
          ▼                                                       ▼
    ┌─────────────────────────────────────────────────────────────────────────┐
    │                           SOURCE FILES (src/)                            │
    │                                                                          │
    │   ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐     │
    │   │ledger.py │ │escrow.py │ │runner.py │ │agent.py  │ │ ??? .py  │     │
    │   │ mapped   │ │ mapped   │ │NOT mapped│ │NOT mapped│ │NOT mapped│     │
    │   └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘     │
    └─────────────────────────────────────────────────────────────────────────┘
          │
          │ doc_coupling.yaml (MANUAL, incomplete)
          ▼
    ┌───────────┐         ┌───────────┐
    │   DOCS    │    ?    │   TESTS   │  ← No mapping to acceptance_gates/plans
    └───────────┘         └───────────┘


┌─────────────────────────────────────────────────────────────────────────────────┐
│                              OPTIMAL STATE (New)                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

                         ┌─────────────────────────────────┐
                         │         features.yaml           │
                         │    (SINGLE SOURCE OF TRUTH)     │
                         └────────────────┬────────────────┘
                                          │
           ┌──────────────────────────────┼──────────────────────────────┐
           │                              │                              │
           ▼                              ▼                              ▼
    ┌─────────────┐               ┌─────────────┐               ┌─────────────┐
    │    GATE:    │               │    GATE:    │               │    GATE:    │
    │   escrow    │               │   ledger    │               │rate_limiting│
    └──────┬──────┘               └──────┬──────┘               └──────┬──────┘
           │                              │                              │
           ▼                              ▼                              ▼
    ┌─────────────────────────────────────────────────────────────────────────┐
    │                    ACCEPTANCE GATE CONTENTS                              │
    │                                                                          │
    │   problem         → WHY this gate exists                                 │
    │   acceptance_criteria → Given/When/Then specs (LOCKED before impl)       │
    │   out_of_scope    → Explicit exclusions (prevents AI drift)              │
    │   adrs            → [1, 3] constraints from architecture decisions       │
    │   code            → [escrow.py, ...] source files                        │
    │   tests           → [test_escrow.py, ...] verification                   │
    │   docs            → [genesis.md, ...] documentation                      │
    └─────────────────────────────────────────────────────────────────────────┘
                                          │
                    ┌─────────────────────┬┴───────────────────┐
                    │                     │                    │
                    ▼                     ▼                    ▼
           ┌──────────────┐      ┌──────────────┐      ┌──────────────┐
           │   DERIVED:   │      │   DERIVED:   │      │   DERIVED:   │
           │  governance  │      │ doc-coupling │      │ test-mapping │
           │ (file → ADR) │      │ (file → doc) │      │(file → test) │
           └──────────────┘      └──────────────┘      └──────────────┘


                         QUERIES NOW POSSIBLE
    ┌─────────────────────────────────────┬───────────────────────────────┐
    │  QUERY                              │  LOOKUP PATH                  │
    ├─────────────────────────────────────┼───────────────────────────────┤
    │  "What ADRs apply to escrow.py?"    │  file → gate → adrs           │
    │  "What tests cover escrow?"         │  gate → tests                 │
    │  "What gate owns runner.py?"        │  file → gate                  │
    │  "Is escrow fully tested?"          │  gate.tests all pass?         │
    │  "What docs need update?"           │  file → gate → docs           │
    │  "What does ADR-1 govern?"          │  reverse: adrs → gates        │
    └─────────────────────────────────────┴───────────────────────────────┘
```

## Problem

### Sparse, Disconnected Mappings

See "CURRENT STATE" in the diagram above. Key issues:

- `governance.yaml` only maps ~5 files to ADRs
- Most source files have NO ADR mapping
- `doc_coupling.yaml` is manual and incomplete
- Plans are administrative, not linked to code
- No Acceptance Gate concept linking code + tests + docs + ADRs
- Tests have no mapping to gates or plans

### What's Missing

| Query | Can Answer? |
|-------|-------------|
| "What ADRs apply to this file?" | Only if file is in sparse mapping |
| "What tests cover this gate?" | No |
| "Which plan owns this file?" | No |
| "Is this gate fully tested?" | No |
| "What docs need updating if I change X?" | Partial |

## Solution

### Acceptance Gate as Central Entity

See "OPTIMAL STATE" in the diagram above. **Acceptance Gate** becomes the single source of truth connecting:

- **ADRs** - Architectural constraints
- **Code** - Source files implementing the gate
- **Tests** - Verification that gate works
- **Docs** - Documentation explaining the gate

All other mappings (governance, doc-coupling, test-mapping) are **derived** from features.yaml (the gate definition file).

### Features.yaml Schema (Gate Definitions)

```yaml
gates:
  escrow:
    description: "Trustless artifact trading"

    # Constraints
    adrs: [1, 3]  # ADR-0001, ADR-0003

    # Implementation
    code:
      - src/world/escrow.py
      - src/world/contracts/escrow_contract.py

    # Verification
    tests:
      - tests/unit/test_escrow.py
      - tests/e2e/test_escrow.py

    # Documentation
    docs:
      - docs/architecture/current/genesis_artifacts.md

  rate_limiting:
    description: "Token bucket rate limiting for resources"
    adrs: [2]
    code:
      - src/world/rate_tracker.py
    tests:
      - tests/unit/test_rate_tracker.py
    docs:
      - docs/architecture/current/resources.md

  # ... all gates
```

## Derived Mappings

From `features.yaml` (the gate definition file), derive all other mappings:

### File → ADR (replaces governance.yaml)

```python
def get_adrs_for_file(filepath: str) -> list[int]:
    """Given a file, return which ADRs govern it."""
    for gate in gates.values():
        if filepath in gate['code']:
            return gate['adrs']
    return []
```

### File → Doc (replaces doc_coupling.yaml)

```python
def get_docs_for_file(filepath: str) -> list[str]:
    """Given a file, return which docs should be updated."""
    for gate in gates.values():
        if filepath in gate['code']:
            return gate['docs']
    return []
```

### Gate → Tests

```python
def get_tests_for_gate(gate_name: str) -> list[str]:
    """Given a gate, return its tests."""
    return gates[gate_name]['tests']
```

### File → Gate (reverse lookup)

```python
def get_gate_for_file(filepath: str) -> str | None:
    """Given a file, return which gate owns it."""
    for name, gate in gates.items():
        if filepath in gate['code']:
            return name
    return None
```

## Queries Now Possible

| Query | How |
|-------|-----|
| "What ADRs apply to this file?" | `get_adrs_for_file(path)` |
| "What tests cover this gate?" | `get_tests_for_gate(name)` |
| "What gate owns this file?" | `get_gate_for_file(path)` |
| "Is this gate fully tested?" | Check all tests in gate pass |
| "What docs need updating?" | `get_docs_for_file(path)` |
| "What files does ADR-X govern?" | Reverse lookup through gates |

## Handling Edge Cases

### Shared Utilities

Files used by multiple gates:

```yaml
shared:
  utils:
    description: "Shared utility functions"
    code:
      - src/utils.py
      - src/common/helpers.py
    # No specific ADRs - inherits from all gates that use it
    # Tests in unit tests, not gate tests
    tests:
      - tests/unit/test_utils.py
```

### Code Not Yet Assigned

Temporary state during migration:

```yaml
unassigned:
  description: "Code not yet assigned to a gate"
  code:
    - src/legacy/old_module.py
  # Flagged in CI as needing assignment
```

### Multiple Gates for One File

If a file legitimately belongs to multiple gates (rare):

```yaml
ledger:
  code:
    - src/world/ledger.py  # Primary

escrow:
  code:
    - src/world/ledger.py  # Also uses (secondary)
```

Resolution: Primary gate's ADRs apply. Both gates' tests must pass.

## Migration Path

### From Current State

1. **Audit existing code** - List all files in `src/`
2. **Identify gates** - Group files by capability
3. **Create features.yaml** - Define gates with code mappings
4. **Add ADR mappings** - Which ADRs apply to each gate
5. **Add test mappings** - Which tests verify each gate
6. **Deprecate old configs** - Replace governance.yaml, doc_coupling.yaml

## Files

| File | Purpose |
|------|---------|
| `features.yaml` | Single source of truth (gate definitions) |

## Benefits

| Before | After |
|--------|-------|
| Sparse ADR mapping | Complete coverage via gates |
| Manual doc_coupling.yaml | Derived from gates |
| "What owns this file?" - unknown | Gate lookup |
| "Is gate tested?" - unknown | Gate.tests check |
| Plans as organization | Gates as organization, plans as tasks |

## Related Patterns

- [Acceptance-Gate-Driven Development](13_acceptance-gate-driven-development.md) - The complete meta-process
- [ADR Governance](08_adr-governance.md) - Now derived from gates
- [Doc-Code Coupling](10_doc-code-coupling.md) - Now derived from gates
- [Documentation Graph](09_documentation-graph.md) - Gates as nodes

## Related Meta-Process ADRs

- [META-ADR-0001: Acceptance Gate Terminology](../adr/0001-acceptance-gate-terminology.md) - Why "acceptance gate" not "feature"
- [META-ADR-0004: Gate YAML Is Documentation](../adr/0004-gate-yaml-is-documentation.md) - YAML as single source

## Origin

Identified during meta-process design when analyzing why ADR conformance checking would fail - the linkage from files to ADRs was too sparse to be useful. Gate-centric organization provides complete coverage.

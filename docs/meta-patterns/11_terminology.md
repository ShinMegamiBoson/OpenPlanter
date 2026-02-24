# Pattern: Project Terminology

## Why Terminology Matters

Inconsistent terminology causes:
- Miscommunication between team members
- Documentation that contradicts itself
- Confusion about what's being tracked

This document defines the canonical terms for project organization.

## Core Hierarchy

```
Phase (optional grouping)
└── Acceptance Gate (E2E verification checkpoint)
    └── Plan(s) (work coordination documents)
        └── Task (atomic work item)
```

### Definitions

| Term | Definition | Identifier | Tests At Level |
|------|------------|------------|----------------|
| **Acceptance Gate** | E2E-verifiable functional capability | `acceptance_gates/NAME.yaml` | E2E required |
| **Plan** | Work coordination document | `docs/plans/NN_name.md` | Unit/integration tests |
| **Task** | Atomic work item within a plan | Checklist item | May have unit test |
| **Phase** | Optional grouping of related gates | "Phase 1" | No tests (just grouping) |

### Why "Acceptance Gate" Not "Feature"

See [META-ADR-0001](../adr/0001-acceptance-gate-terminology.md) for full rationale.

1. **"Feature" is overloaded** - means different things everywhere (product feature, feature flag, feature branch)
2. **"Acceptance gate" conveys mechanism** - it's a gate you must pass, not an optional checkpoint
3. **Name encodes discipline** - not a suggestion, a requirement

### Key Insight: Gates vs Plans

**Acceptance gates** and **Plans** serve different purposes:

| Concept | Purpose | Relationship |
|---------|---------|--------------|
| **Acceptance Gate** | E2E acceptance verification | "Does it actually work?" |
| **Plan** | Work coordination, file locking | "Who works on what?" |

- Multiple **plans** can contribute to one **acceptance gate**
- A plan can be "complete" while its gate is still not passed
- Gate passed = the REAL checkpoint (E2E passes with no mocks)

```
Acceptance Gate: "Escrow Trading"    # E2E verification checkpoint
    └── Plan: 08_escrow_basic.md     # First implementation
    └── Plan: 15_escrow_timeout.md   # Adds timeout handling
    └── Plan: 22_escrow_multi.md     # Adds multi-party support
```

See [Acceptance-Gate-Driven Development](13_acceptance-gate-driven-development.md) for the full pattern.

## Plan Types

Not all plans contribute to acceptance gates. Distinguish between:

| Type | Definition | E2E Required? | Examples |
|------|------------|---------------|----------|
| **Gate Plan** | Delivers testable capability | Yes | Rate limiting, Escrow, MCP servers |
| **Enabler Plan** | Improves dev process | No | Dev tooling, ADR governance |
| **Refactor Plan** | Changes internals, not behavior | Existing E2E must pass | Terminology cleanup |

Mark in plan header:
```markdown
**Type:** Gate  # or Enabler, Refactor
```

## Status Terms

| Status | Emoji | Meaning |
|--------|-------|---------|
| **Planned** | 📋 | Has implementation design, ready to start |
| **In Progress** | 🚧 | Actively being implemented |
| **Blocked** | ⏸️ | Waiting on dependency |
| **Needs Plan** | ❌ | Gap identified, needs design work |
| **Complete** | ✅ | Implemented, tested, documented |

## Resource Terms

See `docs/GLOSSARY.md` for canonical resource terminology:

| Use | Not | Why |
|-----|-----|-----|
| `scrip` | `credits` | Consistency with economics literature |
| `principal` | `account` | Principals include artifacts, not just agents |
| `tick` | `turn` | Game theory convention |
| `artifact` | `object/entity` | Everything is an artifact |

## Test Organization Terms

| Term | Definition |
|------|------------|
| **Unit test** | Tests single component in isolation |
| **Integration test** | Tests multiple components together |
| **E2E test** | Tests full system end-to-end |
| **Smoke test** | Basic E2E that verifies system runs |
| **Plan test** | Test(s) required for a specific plan |

## Enforcement

Terminology is enforced through:

1. **Code review** - Reviewers flag incorrect terms
2. **Glossary reference** - `docs/GLOSSARY.md` is authoritative
3. **Search and replace** - Periodic terminology audits
4. **CI (future)** - Could add terminology linting

## Usage Examples

### Correct

> "Plan #6 (Unified Ontology) is a gate plan that delivers artifact-backed agents."

> "Task: Create the TokenBucket class (part of Plan #1)"

> "Phase 1 includes Plans #1, #2, and #3"

> "The escrow acceptance gate requires three E2E tests to pass."

### Incorrect

> "Feature #6 is blocked" (use "Plan #6" or "the escrow acceptance gate")

> "The rate limiting task needs E2E tests" (tasks don't have E2E; gates do)

> "The credits system" (use "scrip")

## Related ADRs

- [META-ADR-0001: Acceptance Gate Terminology](../adr/0001-acceptance-gate-terminology.md)
- [META-ADR-0002: Thin-Slice Enforcement](../adr/0002-thin-slice-enforcement.md)
- [META-ADR-0003: Plan-Gate Hierarchy](../adr/0003-plan-gate-hierarchy.md)

## Origin

Defined to resolve confusion between "feature", "acceptance gate", "plan", "gap", and "task" during coordination.

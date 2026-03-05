# Pattern: Documentation Graph

> **STATUS: IMPLEMENTED** - Plan #215 (2026-01-25)
> `relationships.yaml` is now the unified source of truth.
> Scripts read from relationships.yaml with fallback to legacy configs.

## Problem

Documentation relationships are scattered across multiple config files:
- `governance.yaml` maps ADRs → code
- `doc_coupling.yaml` maps code → docs

This makes it impossible to trace: ADR → target architecture → current architecture → gaps → plans → code. Adding new relationship types requires new config files.

## Solution

Unify all documentation relationships into a single `relationships.yaml` with a nodes/edges schema.

**Implementation:** `scripts/relationships.yaml` contains:
- `adrs`: ADR metadata (number → title, file)
- `governance`: ADR → source mappings (used by sync_governance.py)
- `couplings`: source → doc mappings (used by check_doc_coupling.py)

## Files

| File | Purpose |
|------|---------|
| `scripts/relationships.yaml` | Single source of truth for all doc relationships |
| `scripts/sync_governance.py` | Reads `governs` edges, embeds headers in code |
| `scripts/check_doc_coupling.py` | Reads `documented_by` edges with `coupling: strict` |
| `scripts/validate_plan.py` | Queries graph before implementation (the "gate") |

## Schema

```yaml
# scripts/relationships.yaml
version: 1

# Node namespaces - glob patterns for doc categories
nodes:
  adr: docs/adr/*.md
  target: docs/architecture/target/*.md
  current: docs/architecture/current/*.md
  plans: docs/plans/*.md
  gaps: docs/architecture/gaps/*.yaml
  source: src/**/*.py

# Edge types
edge_types:
  governs:      # ADR governs code/docs (embeds headers)
  implements:   # Plan implements toward target
  documented_by: # Code documented by architecture doc (CI enforcement)
  vision_for:   # Target doc that current implements toward
  details:      # Plan linked to detailed gap analysis

# Relationships
edges:
  - from: adr/0001-everything-is-artifact
    to: [target/01_README, source/src/world/artifacts.py]
    type: governs

  - from: source/src/world/ledger.py
    to: current/resources
    type: documented_by
    coupling: strict  # CI fails if not updated together
```

## Setup

1. **Create relationships.yaml** from existing configs:
```bash
# Merge governance.yaml + doc_coupling.yaml into relationships.yaml
python scripts/migrate_to_relationships.py  # (not yet implemented — merge manually)
```

2. **Update scripts** to read new format (or use existing scripts until migrated)

3. **Deprecate old configs** once migration complete

## Usage

```bash
# Governance headers (same as before)
python scripts/sync_governance.py --check
python scripts/sync_governance.py --apply

# Doc coupling (same as before)
python scripts/check_doc_coupling.py --strict

# NEW: Plan validation gate
python scripts/validate_plan.py --plan 28
# Shows: ADRs that govern, docs to update, uncertainties to resolve
```

## Relationship to Other Patterns

| Pattern | Status | Relationship |
|---------|--------|--------------|
| [ADR Governance](08_adr-governance.md) | Subsumed | `governs` edges replace `governance.yaml` |
| [Doc-Code Coupling](10_doc-code-coupling.md) | Subsumed | `documented_by` edges replace `doc_coupling.yaml` |
| [Conceptual Modeling](27_conceptual-modeling.md) | Complementary | Ontology/glossary are compression layers routed by this graph |

Both patterns remain valid until migration is complete. After migration, they become implementation details of this unified pattern.

**Rationale:** See [META-ADR-0005](../adr/0005-hierarchical-context-compression.md) — the documentation graph is the routing layer for hierarchical context compression. Each documentation layer (glossary, ontology, domain model, ADRs, architecture docs) is a lossy compression of the codebase at a different zoom level. This graph determines which compression to inject for a given task.

## Limitations

- **Migration required** - Existing scripts need updating to read new format
- **Single large file** - All relationships in one file (could split by namespace if too large)
- **Learning curve** - Contributors must understand edge types

## Complementary: Validation Gate

The graph enables a pre-implementation validation workflow:

```bash
$ python scripts/validate_plan.py --plan 28
Checking Plan #28 against relationship graph...
- ADRs that govern affected files: [0001, 0003]
- Target docs to check consistency: [target/05_contracts.md]
- Current docs that need updating: [current/artifacts_executor.md]
- DESIGN_CLARIFICATIONS <70% items: [#7 Event system]

⚠️  1 uncertainty found - discuss with user before implementing
```

The graph is the map; validation is the gate.

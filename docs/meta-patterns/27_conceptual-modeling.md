# Pattern: Conceptual Modeling

## Problem

AI coding assistants accumulate misconceptions about a codebase:
- Use terms inconsistently ("owner" when the system has no ownership concept)
- Build mental models that diverge from the actual architecture
- Make decisions based on assumed structures that don't exist
- Propagate errors when these models are inherited by new sessions

Documentation helps, but:
- Glossaries define terms but not relationships
- Architecture docs describe implementation but not the conceptual primitives
- Without a formal model, each session reconstructs understanding from scratch

## Solution

Create a **Conceptual Model** that defines:
1. **Primitives** - The fundamental building blocks (what exists)
2. **Properties** - Structural characteristics that distinguish types
3. **Relationships** - How primitives relate to each other
4. **Non-Existence** - Terms that DO NOT exist in the system (critical for AI)
5. **Open Questions** - Uncertainties that haven't been resolved

The model is:
- **Formal** - Uses structured format (YAML preferred) for unambiguous parsing
- **Authoritative** - Single source of truth for "what things ARE"
- **Versioned** - Lives in git, evolves with the system

### What Goes in a Conceptual Model

| Section | Purpose | Example |
|---------|---------|---------|
| Primitives | Fundamental entities | "Artifact is the primal entity" |
| Properties | Distinguishing characteristics | "executable: has runnable code" |
| Labels | Convenience names (non-exclusive) | "agent, contract, service" |
| Non-Existence | Terms that cause confusion | "owner - DOES NOT EXIST" |
| System Layers | Where responsibilities live | "kernel stores state, artifacts define policy" |
| Open Questions | Unresolved uncertainties | "What metadata does kernel provide?" |

### What Does NOT Go in a Conceptual Model

- Implementation details (how code works)
- API signatures (those go in code/docs)
- Configuration options (those go in schema)
- Historical decisions (those go in ADRs)

## Files

| File | Purpose |
|------|---------|
| `docs/ONTOLOGY.yaml` | The formal model (renamed from CONCEPTUAL_MODEL.yaml) |
| `docs/GLOSSARY.md` | Term definitions (references model) |
| `docs/architecture/` | Implementation docs (use model terms) |

## Setup

### 1. Create the ontology file

```yaml
# docs/ONTOLOGY.yaml (or docs/CONCEPTUAL_MODEL.yaml - both names are valid)
version: "1.0"
last_updated: "2026-01-28"

# What exists in this system
primitives:
  artifact:
    definition: "The fundamental entity in the system"
    required_interface:
      - id: "Unique identifier"
      - content: "The artifact's data"
      - contract_id: "Reference to governing contract"

# Structural properties that distinguish types
properties:
  executable:
    definition: "Has runnable code"
    examples: ["services", "contracts", "agents"]
  has_standing:
    definition: "Can hold resources and be party to transactions"
    examples: ["agents", "escrow contracts"]

# Convenience labels (non-exclusive)
labels:
  agent:
    definition: "Artifact with has_standing + external LLM access"
    properties: ["executable", "has_standing"]
  contract:
    definition: "Artifact that governs access to another artifact"
    properties: ["executable"]

# CRITICAL: Terms that DO NOT exist
non_existence:
  owner:
    status: "DOES NOT EXIST"
    why: "Causes confusion - rights are governed by contracts, not ownership"
    use_instead: "The contract on artifact X permits Y to Z"

# Unresolved questions
open_questions:
  - question: "What metadata does the kernel provide to contracts?"
    status: "open"
    context: "Contracts need caller identity; what else?"
```

### 2. Reference from CLAUDE.md

```markdown
## Ontology

The authoritative model for "what things ARE" lives in `docs/ONTOLOGY.yaml`.

**Before using any term, verify it exists in the model.** Terms in `non_existence` MUST NOT be used.
```

### 3. Create validation script (optional)

```python
#!/usr/bin/env python3
"""Validate that code uses conceptual model terms correctly."""

import yaml
from pathlib import Path

def load_model():
    model_path = Path("docs/ONTOLOGY.yaml")
    return yaml.safe_load(model_path.read_text())

def check_non_existence(model, text):
    """Flag usage of terms that should not exist."""
    violations = []
    for term, info in model.get("non_existence", {}).items():
        if term.lower() in text.lower():
            violations.append(f"Used '{term}' - {info['why']}")
    return violations
```

## Usage

### When to Create/Update the Model

| Trigger | Action |
|---------|--------|
| New project | Create initial model with core primitives |
| Term confusion | Add to `non_existence` with clear explanation |
| New primitive type | Add to `primitives` with definition |
| Recurring question | Add to `open_questions` to track |
| Question resolved | Move to appropriate section with resolution |

### The Question-Driven Process

Conceptual models emerge from questions:

1. **Surface confusion**: "Wait, who owns this artifact?"
2. **Investigate**: Read code to find actual mechanism
3. **Model**: Add finding to conceptual model
4. **Prohibit**: If term causes confusion, add to `non_existence`

### Example Session

```
Human: "The artifact owner should..."
AI: *checks model* "Note: 'owner' is in non_existence - the system
    uses contracts to govern access. Let me rephrase: 'The contract
    on artifact X permits agent Y to...'"
```

## Customization

### Model Format

YAML is recommended for:
- Structured data (parseable by tools)
- Comments (explain reasoning)
- Git-friendly (line-based diffs)

Alternatives:
- JSON (if tooling requires)
- Markdown with YAML frontmatter (if human readability is priority)

### Level of Detail

| Project Type | Model Depth |
|--------------|-------------|
| Simple CRUD | Just primitives + relationships |
| Domain-heavy | Full model with properties, labels, layers |
| Research/novel | Include open_questions section |

## Limitations

- **Not implementation docs**: Don't duplicate architecture docs
- **Requires maintenance**: Stale models cause more harm than none
- **Doesn't prevent all confusion**: AI can still misinterpret
- **Initial investment**: Creating a good model takes dialogue

## Integration with Other Patterns

| Pattern | Integration |
|---------|-------------|
| Terminology | Glossary references model primitives |
| ADR | Decisions may update model |
| Acceptance Gates | Specs should use model terminology |
| Plan Workflow | Plans reference model for shared understanding |
| Documentation Graph | Graph routes to ontology/glossary based on file being edited |

**Rationale:** See [META-ADR-0005](../adr/0005-hierarchical-context-compression.md) — the ontology and glossary are compression layers in the hierarchical context system. The ontology compresses entity schema (~300 lines vs ~15,000 lines of code). The glossary compresses vocabulary (~30 terms). Both provide information that is expensive to reconstruct from code alone.

## Origin

Emerged from Plan #229 in agent_ecology when CC instances repeatedly misunderstood fundamental concepts (like "owner" in a system with contract-based rights). A formal model reduced these errors by providing authoritative definitions and explicitly prohibiting problematic terms.

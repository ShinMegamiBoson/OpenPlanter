# Pattern: Gap Analysis

## Problem

Development proceeds without systematic understanding of the delta between current and target architecture:
- Plans are created ad-hoc, missing gaps that aren't obvious
- No methodology for discovering gaps - relies on developer intuition
- No mechanism to detect when the gap landscape changes (target evolves, implementation drifts)
- One-time analyses go stale with no trigger for refresh

Result: incomplete planning, missed dependencies, wasted work on low-priority gaps while critical ones remain hidden.

## Solution

Formalize gap analysis as a repeatable, methodology-driven process:

1. **Compare current vs target** across 6 dimensions systematically
2. **Produce structured output** (YAML) with dependencies, complexity, risk
3. **Prioritize and phase** gaps into parallelizable workstreams
4. **Inform plan creation** - every plan should trace to an identified gap
5. **Refresh periodically** - re-run when architecture docs change

## When to Run Gap Analysis

| Trigger | Scope | Why |
|---------|-------|-----|
| **Bootstrap** | Full (all workstreams) | Applying meta-process to existing codebase |
| **Target architecture changes** | Affected workstreams | New vision creates new gaps |
| **Major milestone** | Focused re-check | Implementation may have drifted from plan |
| **Current architecture update** | Affected workstreams | Better understanding reveals hidden gaps |
| **Periodic review** | Summary-level | Catch drift that wasn't noticed incrementally |

## Methodology: 6-Dimensional Comparison

For each system component, compare current vs target across:

| Dimension | Question |
|-----------|----------|
| **Capabilities** | What functions exist now vs. target? |
| **Data Model** | What fields/structures exist now vs. target? |
| **Interfaces** | What methods/APIs exist now vs. target? |
| **Behaviors** | How does it work now vs. target? |
| **Configuration** | What's configurable now vs. target? |
| **Constraints** | What limits exist now vs. target? |

### Document Pairing

Each workstream pairs a current architecture doc with its target counterpart:

```
docs/architecture/current/<component>.md  (what IS)
docs/architecture/target/<component>.md   (what we WANT)
```

Multiple workstreams can be analyzed in parallel by separate agents.

## Output Format

Each gap is captured as structured YAML:

```yaml
- id: GAP-{WORKSTREAM}-{NUMBER}
  component: <component_name>
  dimension: capabilities|data_model|interfaces|behaviors|configuration|constraints
  title: "<short description>"
  current_state: |
    <what exists today>
  target_state: |
    <what should exist>
  delta: |
    <what needs to change>
  dependencies:
    - GAP-YYY  # gaps that must complete first
  complexity: S|M|L|XL
  risk: low|medium|high
  files_affected:
    - path/to/file1.py
  acceptance_criteria:
    - criterion 1
```

### Complexity Scale

| Size | Scope |
|------|-------|
| S | Single function, < 50 lines |
| M | Multiple functions, single file, 50-200 lines |
| L | Multiple files, one component, 200-500 lines |
| XL | Cross-component, > 500 lines |

## Gap-to-Plan Flow

```
current/ + target/
        |
        v
   Gap Analysis  (this pattern)
        |
        v
   Gap Summary   (stays in-repo: lightweight index)
        |
        v
   Prioritization + Phasing
        |
        v
   Plan Creation  (Pattern #15: Plan Workflow)
        |
        v
   Implementation
        |
        v
   Update current/  (triggers potential re-analysis)
```

Every plan should reference which gap(s) it addresses. The plan's "References Reviewed" section (Pattern #28) should cite the relevant current/ and target/ docs that define the gap.

## Files

| File | Purpose |
|------|---------|
| `docs/architecture/current/` | Source of truth for what IS |
| `docs/architecture/target/` | Source of truth for what we WANT |
| `docs/architecture/gaps/GAPS_SUMMARY.yaml` | Lightweight gap index (stays in-repo) |
| `docs/architecture/gaps/CLAUDE.md` | Directory readme |

### Gap Analysis Outputs (Ephemeral)

Detailed workstream YAML files (`ws1_*.yaml`, `ws2_*.yaml`, etc.) are the **output** of running gap analysis. They inform plan creation, then get archived externally. They are not permanent repo fixtures.

**Archive location:** External directory outside the git repo (e.g., `<archive>/docs/architecture/gaps/`).

**Why archive:** Detailed gap worksheets go stale as implementation progresses. Keeping them in-repo gives AI assistants outdated information and wastes context during exploration. The summary stays in-repo as the lightweight index.

## Setup

### 1. Create architecture doc structure

```
docs/architecture/
  current/    # Document what IS implemented
  target/     # Document what you WANT
  gaps/       # Gap analysis outputs
```

### 2. Run initial gap analysis

Pair each current doc with its target counterpart. For each pair, compare across the 6 dimensions and output structured YAML.

For large codebases, parallelize by assigning each workstream to a separate agent.

### 3. Consolidate outputs

1. Merge all workstream YAML files
2. Deduplicate gaps identified from different angles
3. Analyze cross-gap dependencies
4. Group into parallelizable workstreams
5. Produce summary (`GAPS_SUMMARY.yaml`)

### 4. Create plans from gaps

Use the prioritized gap list to create implementation plans (Pattern #15). Each plan should reference the gap(s) it addresses.

### 5. Archive detailed outputs

After plans are created, move detailed workstream files to external archive. Keep only the summary in-repo.

## Customization

### Workstream definitions

Workstreams depend on your architecture. Common splits:
- By component (execution, agents, resources, etc.)
- By layer (data, business logic, API, infrastructure)
- By domain (auth, billing, content, etc.)

### Refresh frequency

- **Active development:** After every 5-10 plans completed
- **Stable project:** Quarterly or on architecture changes
- **New project:** Once at bootstrap, then as target evolves

### Lightweight vs full analysis

- **Full:** All workstreams, all 6 dimensions (bootstrap, major changes)
- **Focused:** Single workstream, triggered by target doc update
- **Summary review:** Check if summary still reflects reality (periodic)

## Limitations

- **Manual process** - No automation for running gap analysis (requires AI reading comprehension)
- **Summary can drift** - If summary isn't updated after focused re-analysis
- **Dependency tracking is static** - Cross-gap dependencies may change as implementation progresses

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Archive detailed outputs | Yes | Prevents stale detail from misleading AI assistants |
| Keep summary in-repo | Yes | Lightweight index for quick reference during plan creation |
| 6 dimensions | Fixed set | Comprehensive without being overwhelming; covers structural + behavioral |
| YAML format | Structured | Machine-queryable, consistent, works with existing tooling |

## See Also

- [Plan Workflow](15_plan-workflow.md) - Plans implement gaps
- [Question-Driven Planning](28_question-driven-planning.md) - Forces exploration before planning
- [Conceptual Modeling](27_conceptual-modeling.md) - Formal model prevents misconceptions
- [Documentation Graph](09_documentation-graph.md) - Traceability from decisions to code

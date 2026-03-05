# Pattern: Acceptance-Gate-Driven Development

A comprehensive meta-process for AI-assisted software development that ensures verified progress, prevents AI drift, and maintains thin slices.

## Why This Exists: The Anti-Big-Bang Goal

Claude Code (and AI coding assistants generally) tends toward **big-bang development**:
- Work for days on implementation
- Accumulate uncommitted changes
- Hope everything integrates at the end
- Discover fundamental issues too late

**Acceptance gates force thin-slice development** by requiring functional capabilities to pass real E2E tests before being considered complete. This pattern exists to prevent the "fingers crossed" approach to integration.

See [META-ADR-0002: Thin-Slice Enforcement](../adr/0002-thin-slice-enforcement.md) for the full rationale.

## Core Concept: Acceptance Gates Are E2E Checkpoints

**An acceptance gate is COMPLETE when its acceptance criteria pass with real (non-mocked) integration.**

Not when code is written. Not when unit tests pass. When **real E2E tests with no mocks** pass.

```
Acceptance Gate: escrow
├── AC-1: Deposit works       ← Must pass with NO MOCKS
├── AC-2: Purchase works      ← Must pass with NO MOCKS
├── AC-3: Cancellation works  ← Must pass with NO MOCKS
│
└── DONE when: pytest tests/e2e/test_real_e2e.py --run-external passes
```

### Acceptance Gates vs Plans

| Concept | Purpose | Done When |
|---------|---------|-----------|
| **Acceptance Gate** | E2E verification checkpoint | Real LLM E2E tests pass |
| **Plan** | Unit of work toward a gate | Code done, unit tests pass |

- Multiple **plans** contribute to one **acceptance gate**
- Plans can be "complete" while acceptance gate is still not passed
- Gate passed = the REAL checkpoint

See [META-ADR-0003: Plan-Gate Hierarchy](../adr/0003-plan-gate-hierarchy.md) for why E2E is at the gate level, not plan level.

### Why Real E2E Matters

Unit tests can pass with mocks. Integration tests can pass with mocks. Only real E2E **with no mocks at all** proves the system actually works. The entire pattern below exists to ensure we reach that checkpoint with verified, working code.

## Problem

### The AI Drift Problem
AI coding assistants (Claude Code, etc.):
- Forget ADRs and architectural constraints mid-implementation
- Make "reasonable assumptions" that diverge from requirements
- When implementation is hard, write weak tests that pass trivially
- Test what they built, not what was needed

### The Linkage Problem
Typical project structure has sparse, disconnected mappings:
- Plans are administrative, not architectural
- No concept linking code + tests + docs + ADRs
- Can't answer: "What ADRs apply to this file?"
- Can't answer: "What tests cover this feature?"

## Solution

### Core Concept: Acceptance Gate as Central Entity

**Acceptance Gate** = E2E-verifiable functional capability (e.g., "escrow", "rate_limiting")

An Acceptance Gate contains:
- Problem statement (WHY)
- Acceptance criteria (WHAT, testable)
- Out of scope (explicit exclusions)
- ADR constraints
- Code files
- Test files
- Documentation

**Tasks** operate ON Acceptance Gates. Plans become administrative tracking, not organizational structure.

See [META-ADR-0001: Acceptance Gate Terminology](../adr/0001-acceptance-gate-terminology.md) for why we use "acceptance gate" not "feature".

### The Lock-Before-Implement Principle

```
Spec written → Spec LOCKED (committed) → Implementation
                    │
                    └── AI cannot modify, so cannot cheat
```

Even if same AI instance, same context - once specs are committed and CI enforces immutability, the AI must pass the specs it wrote.

### Modifying Locked Specs

Locks prevent *sneaky* changes, not *all* changes. Legitimate reasons to modify specs:
- Requirements actually changed (user decision)
- Original spec was wrong or ambiguous
- Scope legitimately changed

**Process to modify:**

```
PR: Remove `locked: true` → Modify spec → Re-add `locked: true`
                │
                └── Human reviews diff, sees explicit unlock/modify/relock
```

**Why this works:**
| Protection | How |
|------------|-----|
| Friction | AI must explicitly unlock (shows intent) |
| Visibility | Spec changes show clearly in PR diff |
| Audit trail | Git history shows unlock → modify → relock |
| Human review | User reviews specs in plain English |

**The key insight:** The lock's value is making spec changes *visible and deliberate*, not *impossible*. If AI explicitly unlocks, modifies, and relocks, that's a deliberate choice visible in git history for human review.

**Stronger enforcement (if needed later):**
- Require `unlock_reason:` field in YAML
- Require separate unlock PR before modification PR
- Require human approval label (e.g., `spec-change-approved`)

Start simple. Add friction only if abuse is detected.

### Human-AI Division of Labor

| Role | Human | AI |
|------|-------|-----|
| Define problem | Reviews/approves | Writes |
| Write specs | Reviews (plain English) | Writes |
| Lock specs | Approves commit | Commits |
| Implement | Not involved | Writes |
| Review code | Not involved | N/A (CI does it) |
| Verify | Sees green CI | N/A |

**Human only touches what human is good at:** requirements and acceptance criteria in plain English.

**AI handles what AI is good at:** writing code and tests.

**CI handles what automation is good at:** verification and enforcement.

## Acceptance Gate Definition Schema

```yaml
# acceptance_gates/escrow.yaml
gate: escrow
planning_mode: guided  # autonomous | guided | detailed | iterative

# === PRD SECTION (What/Why - Human-readable) ===
problem: |
  Agents need to trade artifacts without trusting each other.
  Currently, if Agent A sends artifact first, Agent B might not pay.

# === DESIGN SECTION (How - Optional, plain English) ===
# Use when: multiple approaches possible, architectural novelty, medium+ features
# Skip when: obvious implementation, bug fix, small feature
design:
  approach: |
    Escrow will be a contract artifact that temporarily holds ownership of
    the traded artifact until payment is received or timeout occurs.
  key_decisions:
    - "Timeout based on tick count, not wall clock (simpler, deterministic)"
    - "One escrow contract per trade (not a shared escrow pool)"
    - "Seller can cancel before buyer commits (flexibility)"
    - "Escrow is an artifact itself (per ADR-0001)"
  risks:
    - "If tick processing is slow, timeout could behave unexpectedly (accepted)"

acceptance_criteria:
  - id: AC-1
    scenario: "Basic escrow lock"
    given:
      - "Agent A owns an artifact"
      - "Agent A has sufficient scrip"
    when: "Agent A locks artifact in escrow with price 50"
    then:
      - "Artifact held by escrow system, not Agent A"
      - "Price recorded as 50 scrip"
      - "Agent A hasn't paid anything yet"
    locked: true  # AI cannot modify after commit

  - id: AC-2
    scenario: "Successful claim"
    given:
      - "Artifact locked in escrow at price 50"
      - "Agent B has 100 scrip"
    when: "Agent B pays 50 scrip to claim"
    then:
      - "Agent B now owns artifact"
      - "Agent A receives 50 scrip"
      - "Escrow cleared"
    locked: true

  - id: AC-3
    scenario: "Cannot claim without payment"
    given:
      - "Artifact locked at price 50"
    when: "Agent B tries to claim with only 30 scrip"
    then:
      - "Claim fails with InsufficientFundsError"
      - "Artifact stays in escrow"
      - "Agent B keeps their 30 scrip"
    locked: true

out_of_scope:
  - "Multi-party escrow (only 2-party supported)"
  - "Partial payments"
  - "Renegotiation after lock"
  - "Escrow fee negotiation"

# === IMPLEMENTATION SECTION ===
adrs: [1, 3]  # ADR-0001, ADR-0003

code:
  - src/world/escrow.py
  - src/world/contracts/escrow_contract.py

tests:
  - tests/unit/test_escrow.py
  - tests/e2e/test_escrow.py

docs:
  - docs/architecture/current/genesis_artifacts.md
```

## Design Section (The "How")

The design section captures architectural decisions BEFORE implementation.

### Why It Exists

Without design section:
```
Spec (WHAT) → Implementation (HOW happens invisibly)
```

CC could satisfy the spec with poor architecture. Tests pass, but code is:
- Hard to maintain
- Wrong patterns
- Doesn't fit existing codebase

Design section surfaces these choices for review.

### When to Use

| Planning Mode | Design Section |
|---------------|----------------|
| `autonomous` | Skip |
| `guided` | Optional (use when multiple approaches possible) |
| `detailed` | Required |
| `iterative` | Per-cycle (can evolve) |

| Gate Size | Design Section |
|-----------|----------------|
| Bug fix | Skip |
| Small utility | Skip |
| Medium gate | Recommended |
| Large gate | Required |
| Architectural change | Required |

### Format Rules

1. **Plain English only** - Human must be able to review without reading code
2. **5-10 lines max** - Not a formal design doc, just a checkpoint
3. **Focus on choices that matter** - Skip obvious decisions
4. **Include rationale** - "X because Y", not just "X"

### What to Include

```yaml
design:
  approach: "1-3 sentence summary of HOW this will be built"
  key_decisions:
    - "Decision 1 and brief rationale"
    - "Decision 2 and brief rationale"
    # 2-5 decisions, focus on non-obvious choices
  risks:  # Optional
    - "Known risk and whether accepted/mitigated"
```

### What NOT to Include

- Pseudocode or code snippets
- Database schemas (unless very simple)
- API signatures
- Implementation details

Keep it reviewable by someone who can't read code.

## Planning Depth Levels

Not all acceptance gates require the same planning depth.

### Autonomous Mode
```
Human: "Add logging to the simulation"
AI: Writes spec, locks it, implements, done
Human: Sees green CI, trusts result
```
- **Use for:** Low-stakes, well-understood, utilities
- **Risk accepted:** AI might build wrong thing
- **Benefit:** Fast, no bottleneck

### Guided Mode (Default)
```
Human: "I need escrow for trading"
AI: Writes spec in plain English Given/When/Then
Human: "Yes" / "Add timeout case" / "Remove partial payments"
AI: Revises, locks, implements
Human: Sees green CI
```
- **Use for:** Most features
- **Balanced:** Human validates requirements, doesn't read code

### Detailed Mode
```
Human: "Let's design the economic model"
[Days of dialogue]
Human: "What if agents can go into debt?"
AI: "Here are tradeoffs..."
Human: "Let's prohibit debt but allow credit lines"
[More rounds]
AI: Locks spec, implements
```
- **Use for:** Critical features, novel problems, core architecture
- **High investment:** Human deeply involved in spec creation

### Iterative Mode
```
Cycle 1:
  Human: "I want agents to cooperate somehow"
  AI: Writes minimal spec for basic cooperation
  Human: Approves
  AI: Locks v1, implements v1

Cycle 2:
  Human: "Interesting, but they're not forming groups"
  AI: Writes spec v2 based on learnings
  AI: Locks v2, implements v2

Cycle 3:
  [Refined spec based on learnings]
```
- **Use for:** R&D, exploratory, unclear requirements
- **Key:** Each cycle still has lock-before-implement
- **Learning:** Requirements emerge from implementation feedback

## Preventing AI Cheating

### The Problem

When AI writes both spec AND implementation:
- Knows what's easy while writing specs
- Can write weak specs broken code passes
- Skip edge cases that reveal bugs
- Test what it built, not what was needed

### Solution: Temporal Separation + Lock

1. **Spec Phase:** AI writes Given/When/Then specs
2. **Lock Phase:** Specs committed to git, CI enforces immutability
3. **Impl Phase:** AI implements to pass locked specs

AI cannot modify locked specs. If implementation is hard, AI must either:
- Make it work (correct behavior)
- Report failure (honest behavior)

NOT: Weaken the test (cheating)

### Role Framing (Optional Enhancement)

Different prompts for different phases:

**Spec Phase:** "You are QA. Write specs to catch bugs in code someone else will write. Be adversarial. Think about edge cases and failure modes."

**Impl Phase:** "You are a developer. Make these tests pass. You cannot modify the tests."

### Minimum Spec Requirements (CI Enforced)

```yaml
spec_requirements:
  minimum_scenarios: 3
  required_categories:
    - happy_path: "At least one success case"
    - error_case: "At least one failure mode"
    - edge_case: "At least one boundary condition"
  format: "Given/When/Then"
  assertions: "Specific, testable statements in 'then'"
```

## ADR Conformance

### Pre-Implementation Checklist

Before implementing, AI must produce:

```markdown
## Pre-Implementation Checklist

### Feature: escrow
### Task: Add timeout functionality

**Acceptance Criteria Addressed:**
- AC-3: "Escrow times out after N ticks if unclaimed"

**ADR Conformance:**
- ADR-0001 (Everything is artifact): Escrow is already an artifact ✓
- ADR-0003 (Contracts can do anything): Timeout logic in contract ✓

**Out of Scope Verified:**
- NOT adding renegotiation (out of scope) ✓
- NOT adding partial refunds (out of scope) ✓

**Test Plan:**
- Will add test_timeout to test_escrow.py
- Maps to AC-3
```

### Governance Headers

ADR references in source file headers keep constraints visible:

```python
# src/world/escrow.py
# --- GOVERNANCE START (do not edit) ---
# ADR-0001: Everything is an artifact
# ADR-0003: Contracts can do anything
# --- GOVERNANCE END ---
```

## Process Flow

1. **Define** — AI writes problem statement + out_of_scope; human reviews (if guided/detailed)
2. **Spec** — AI writes Given/When/Then acceptance criteria; human reviews; CI validates completeness
3. **Design** — AI writes approach + key decisions in plain English (optional, based on planning mode)
4. **Lock** — Gate file committed to git; CI enforces immutability of locked sections
5. **Checklist** — AI documents ADR conformance, out_of_scope acknowledgment, criteria addressed
6. **Implement** — AI writes code to pass locked specs; cannot modify specs
7. **Verify** — CI: all tests pass, locked files unchanged, doc-coupling passes
8. **Merge** — Human sees green CI = done; no code review needed (specs are the contract)

## Task Types

Acceptance gates contain tasks. Each task has a type with specific verification:

| Type | What It Is | Verification |
|------|------------|--------------|
| `impl` | Code implementation | Gate tests pass, ADR conformance documented |
| `doc` | Documentation | Doc-coupling check passes, terminology correct |
| `arch` | Architecture decision | ADR exists, governance sync passes |

## Thin Slices (Always)

### Principle

Every unit of work must prove it works end-to-end before declaring success.

### Why

- Unit tests passing ≠ system works
- Small increments = verified progress
- Catches integration issues early
- Limits blast radius of mistakes

### Orthogonal to Planning Depth

| Combination | Meaning |
|-------------|---------|
| Autonomous + thin slices | AI makes assumptions, delivers small increments |
| Detailed + thin slices | Extensive planning, still small deliverables |
| Detailed + big slice | **ANTI-PATTERN** (avoid) |

## Files

| File | Purpose |
|------|---------|
| `acceptance_gates/*.yaml` | Acceptance gate definitions (single source of truth) |
| `scripts/check_locked_files.py` | Ensures locked files unchanged (manual tool) |

See [META-ADR-0004: Gate YAML Is Documentation](../adr/0004-gate-yaml-is-documentation.md) for why gate definitions live in YAML, not separate markdown files.

## Setup (New Project)

1. Create `acceptance_gates/` directory
2. Add feature definition template

## Usage

### Creating a New Acceptance Gate

```bash
# 1. Create gate definition
claude "Create acceptance gate definition for user authentication"
# AI writes acceptance_gates/authentication.yaml with problem, out_of_scope

# 2. Review and approve (if guided mode)
# Human reviews the definition

# 3. Create specs
claude "Write acceptance criteria for authentication gate"
# AI writes Given/When/Then specs

# 4. Review specs (if guided mode)
# Human reviews acceptance criteria

# 5. Lock specs
git add acceptance_gates/authentication.yaml
git commit -m "Lock authentication gate specs"

# 6. Implement
claude "Implement authentication to pass the locked specs"
# AI implements, cannot modify specs

# 7. Verify
# CI runs, human sees green = done
```

### Iterative Development

```bash
# Cycle 1
claude "Create minimal spec for agent cooperation - we'll iterate"
git commit -m "Lock cooperation v1 specs"
claude "Implement cooperation v1"

# Learn from implementation
# Human: "I see agents aren't forming groups"

# Cycle 2
claude "Update cooperation spec to include group formation based on learnings"
git commit -m "Lock cooperation v2 specs"
claude "Implement cooperation v2"
```

## CI Enforcement

Add these checks to your CI pipeline:
- **Lock enforcement:** `python scripts/check_locked_files.py` (manual)
- **Gate tests:** `pytest tests/acceptance_gates/ -v`

## Customization

### Adjusting Minimum Spec Requirements

> *Note: `config/spec_requirements.yaml` is not yet implemented. Configure requirements
> directly in acceptance gate YAML files.*

```yaml
# config/spec_requirements.yaml (planned, not yet implemented)
minimum_scenarios: 3  # Increase for critical gates
required_categories:
  - happy_path
  - error_case
  - edge_case
  - security_case  # Add for security-sensitive gates
```

### Planning Mode Defaults

> *Note: `config/defaults.yaml` is not yet implemented. Configure planning modes
> in `meta-process.yaml` under the `planning:` section.*

```yaml
# config/defaults.yaml (planned, not yet implemented)
default_planning_mode: guided
allow_autonomous: true
require_approval_for_lock: true
```

## Limitations

### What This Pattern Solves
- AI drift from ADRs/constraints
- AI cheating by weakening tests
- Big bang integration failures
- Sparse file-to-constraint mapping
- "Fingers crossed" development

### What This Pattern Doesn't Solve
- Knowing the right requirements (requires human judgment)
- Ambiguous natural language in specs (minimize with Given/When/Then)
- AI missing non-obvious edge cases in autonomous mode
- Performance optimization (this is about correctness)

### Accepted Risks

| Risk | Mitigation | Residual |
|------|------------|----------|
| Weak specs in autonomous mode | Spec validation | Non-obvious gaps |
| Wrong requirements | Human reviews (guided/detailed) | None if human reviews |
| Ambiguous spec language | Structured format | Some ambiguity possible |

## Related Patterns

- [Acceptance Gate Linkage](14_acceptance-gate-linkage.md) - Companion pattern: optimal linkage structure
- [ADR](07_adr.md) - Architecture Decision Records
- [ADR Governance](08_adr-governance.md) - Linking ADRs to code
- [Doc-Code Coupling](10_doc-code-coupling.md) - Linking docs to code
- [Testing Strategy](03_testing-strategy.md) - Test organization
- [Verification Enforcement](17_verification-enforcement.md) - Proving completion

## Related Meta-Process ADRs

- [META-ADR-0001: Acceptance Gate Terminology](../adr/0001-acceptance-gate-terminology.md) - Why "acceptance gate" not "feature"
- [META-ADR-0002: Thin-Slice Enforcement](../adr/0002-thin-slice-enforcement.md) - Anti-big-bang goal
- [META-ADR-0003: Plan-Gate Hierarchy](../adr/0003-plan-gate-hierarchy.md) - E2E at gate level
- [META-ADR-0004: Gate YAML Is Documentation](../adr/0004-gate-yaml-is-documentation.md) - YAML as single source

## Origin

Emerged from coordination problems with multiple Claude Code instances on [agent_ecology](https://github.com/BrianMills2718/agent_ecology2), specifically:
- Repeated "big bang" integration failures
- AI making reasonable but wrong assumptions
- Difficulty tracing requirements to code to tests
- Human unable to validate code but able to validate requirements


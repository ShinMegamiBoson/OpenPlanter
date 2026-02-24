# Pattern: Phased ADR

A pattern for documenting architectural decisions that involve intentional phasing - building simpler versions first while preserving the thinking about more powerful future options.

## When to Use

Use this pattern when:
- You've done significant design work on a complex feature
- You decide to build a simpler version first
- You want to preserve the "full vision" without losing it
- Future phases depend on learnings from earlier phases
- You want to avoid re-doing the analysis later

## The Problem

Standard ADRs capture "we decided X" but don't capture:
- "We designed X, Y, and Z but are only building X now"
- "Y and Z are intentionally deferred, not forgotten"
- "Here's when we'd revisit Y and Z"

Plans capture "build X" but lose the context of Y and Z that informed the design.

## The Pattern

### 1. Create a Phased ADR

```markdown
# ADR-00XX: [Feature] Architecture

**Status:** Accepted (Phase 1)
**Phases:** Phase 1 ✅ | Phase 2 ⏳ | Phase 3 ⏳

## Context

[Problem statement and why phasing makes sense]

## Decision

We will implement [Feature] in phases:

### Phase 1: [Simple Version] (Current)

**What:** [Concrete scope]
**Why first:** [Rationale for starting here]
**Limitations:** [What this doesn't do]

### Phase 2: [Enhanced Version] (Deferred)

**What:** [Concrete scope]
**Requires:** [What we need to learn/observe first]
**Trigger:** [Criteria for when to implement]

### Phase 3: [Full Version] (Future)

**What:** [Concrete scope]
**Requires:** [Dependencies on earlier phases]
**Trigger:** [Criteria for when to implement]

## Detailed Design Notes

### Phase 2 Design (Preserved)

[Capture the thinking that went into Phase 2 design so it's not lost]

- Option A considered: ...
- Option B considered: ...
- Trade-offs identified: ...
- Open questions: ...

### Phase 3 Design (Preserved)

[Same for Phase 3]

## Consequences

**Phase 1:**
- Pro: [Benefits of simple version]
- Con: [Limitations accepted]

**If we skip to Phase 3:**
- Risk: [Why jumping ahead is risky]

## Review Triggers

Revisit this ADR when:
- [ ] [Specific observation or metric]
- [ ] [Time-based trigger]
- [ ] [User/agent feedback pattern]
```

### 2. Create Plan for Current Phase Only

The implementation plan covers only Phase 1:

```markdown
# Plan XX: [Feature] Phase 1

**Status:** 📋 Planned
**ADR:** ADR-00XX (Phase 1 of 3)

## Context

See ADR-00XX for full architectural context and future phases.

This plan implements Phase 1 only.

## Files Affected
[Only Phase 1 files]

## Acceptance Criteria
[Only Phase 1 criteria]
```

### 3. Future Phase Plans

When ready for Phase 2, create a new plan:

```markdown
# Plan YY: [Feature] Phase 2

**Status:** 📋 Planned
**ADR:** ADR-00XX (Phase 2 of 3)
**Blocked By:** Learnings from Plan XX

## Trigger Met

[Document what observation/learning triggered this phase]

## Changes from ADR Design

[Note any adjustments based on Phase 1 learnings]
```

## Example: Agent Intelligence Phasing

```markdown
# ADR-0015: Agent Cognitive Architecture

**Status:** Accepted (Phase 1)
**Phases:** Phase 1 ✅ | Phase 2 ⏳ | Phase 3 ⏳

## Context

Agents need configurable cognitive patterns (thinking, planning, acting).
Full meta-configuration is powerful but complex. We don't yet know what
agents actually need.

## Decision

### Phase 1: Simple Workflows (Current)

**What:**
- Workflow defined as ordered steps
- Each step references a prompt artifact (plain markdown)
- Agent manually constructs prompts with context
- No template language, no injection DSL

**Why first:**
- Minimal complexity for agents to understand
- Lets us observe what context agents actually need
- No DSL design decisions to get wrong

**Limitations:**
- Agent must manually include context in prompts
- No structured output enforcement
- No reuse of prompt patterns

### Phase 2: Template Injection (Deferred)

**What:**
- Add injection DSL for context
- Template rendering (Jinja2 or similar)
- Structured output schemas

**Requires:**
- Observations from Phase 1 about what context agents need
- Evidence that manual prompt construction is a bottleneck

**Trigger:**
- Agents consistently fail due to missing context
- Same context patterns repeated across 3+ agents

### Phase 3: Full Meta-Config (Future)

**What:**
- Agents can modify their own workflow structure
- Dynamic step addition/removal
- Self-modifying prompt templates

**Requires:**
- Phase 2 working well
- Evidence that fixed workflows limit emergence

**Trigger:**
- Agents explicitly request workflow modification
- Successful agents develop consistent meta-patterns

## Detailed Design Notes

### Phase 2 Design (Preserved)

Template language options considered:
| Option    | Pros                 | Cons                              |
|-----------|----------------------|-----------------------------------|
| Jinja2    | Powerful, well-known | Complex, potential code execution |
| Mustache  | Simple, safe         | Limited (no conditionals)         |
| Custom    | Full control         | More work, agents must learn it   |

Injection DSL sketch:
```yaml
inject:
  memories: context.memories
  thinking: steps.think.output
```

Open questions:
- What namespace for injection sources?
- Security/sandboxing for injection?
- Kernel vs agent-side rendering?

### Phase 3 Design (Preserved)

Self-modification concerns:
- Can agents access things they shouldn't?
- Does schema enforcement limit emergence?
- How to debug template + injection + schema issues?

## Consequences

**Phase 1:**
- Pro: Simple, observable, minimal agent learning curve
- Con: Manual context construction may be tedious

**If we skip to Phase 3:**
- Risk: Complexity without understanding what's actually needed
- Risk: DSL design decisions made without evidence
```

## Benefits

1. **Thinking preserved** - Phase 2/3 design work isn't lost
2. **Clear current scope** - Plans only cover current phase
3. **Explicit triggers** - Know when to revisit
4. **Avoids premature complexity** - Build what you need now
5. **Traceable evolution** - Future phases reference back to ADR

## Anti-Patterns

❌ **Putting all phases in one plan** - Plans become huge, unclear what to build now

❌ **No ADR, just "we'll do it later"** - Thinking gets lost, re-analysis needed

❌ **Phase 2 plan without Phase 1 learnings** - Defeats the purpose of phasing

❌ **Vague triggers** - "When we need it" vs "When 3+ agents fail due to X"

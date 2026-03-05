# Pattern #33: Uncertainty Resolution

**Status:** Active
**Created:** 2026-02-05 (Plan #294)

---

## Problem

Uncertainties arise during planning and implementation. Without a systematic approach:
- They get listed but never resolved
- Decisions are made implicitly without documentation
- The same uncertainties resurface in future work
- No feedback loop to improve specs/process

## Solution

A lightweight lifecycle for uncertainties: Capture → Triage → Resolve → Feed Back.

---

## The Lifecycle

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ CAPTURE     │ --> │ TRIAGE      │ --> │ RESOLVE     │ --> │ FEED BACK   │
│ (identify)  │     │ (blocking?) │     │ (decide)    │     │ (update)    │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
```

### 1. CAPTURE

When you encounter uncertainty during work:

```markdown
## Open Uncertainties

**U1: Short description of uncertainty**
- Option A: ...
- Option B: ...
- **Current assumption:** What we're doing for now
- **Blocking:** Yes/No
```

Use sequential IDs (U1, U2, ...) within each plan/document.

### 2. TRIAGE

Categorize the uncertainty:

| Category | Description | Resolution Path |
|----------|-------------|-----------------|
| Architecture | Affects system design | ADR |
| Implementation | How to build something | Test empirically |
| Process | How we work | Meta-process pattern |
| Specification | What we're building | Update PRD/domain model |
| Trivial | Low-impact choice | Just decide |

Ask: **Is this blocking?**
- **Yes (can't proceed without answer)** → Stop and resolve now
- **No (can proceed with assumption)** → Document assumption, continue, revisit

### 3. RESOLVE

Based on category:

**Architecture:**
```bash
# Create ADR
cp docs/adr/TEMPLATE.md docs/adr/00XX_decision_name.md
# Fill in context, decision, consequences
```

**Implementation:**
- Build a small test/prototype
- Document what you learned
- Choose based on evidence

**Process:**
- If reusable: Create new pattern in `meta-process/patterns/`
- If one-off: Document in `meta-process/ISSUES.md` with resolution

**Specification:**
- Update the source doc (PRD, domain model, ontology)
- The spec was incomplete; now it's not

**Trivial:**
- Just decide
- Optionally add to `docs/DESIGN_CLARIFICATIONS.md` if rationale might be useful later

### 4. FEED BACK

After resolution:
1. Update the source document with the decision
2. Remove from "Open Uncertainties" (or mark resolved with date)
3. If the uncertainty revealed a gap in specs/process, file a plan to fix it

---

## When to Stop vs Continue

**Stop and resolve if:**
- Implementation would differ significantly based on answer
- Wrong choice would require significant rework
- Multiple people are blocked waiting for decision
- The uncertainty is about requirements (what), not implementation (how)

**Continue with assumption if:**
- The code would be similar either way
- Easy to change later if wrong
- Only affects this specific piece of work
- The uncertainty is about optimization/polish

---

## Example: Plan #294 Uncertainties

| ID | Uncertainty | Category | Blocking? | Resolution |
|----|-------------|----------|-----------|------------|
| U1 | Centralized vs in-file links | Architecture | No | Decide: Centralized (matches existing pattern) |
| U6 | Context size limits | Implementation | No | Defer: Test empirically when implemented |
| U10 | Who maintains mappings | Process | Yes | Pattern: Claude Code adds, CI enforces |

---

## Anti-Patterns

**Analysis paralysis:** Trying to resolve all uncertainties before starting work.
- Fix: Triage ruthlessly. Most uncertainties aren't blocking.

**Hidden assumptions:** Making decisions without documenting them.
- Fix: Every uncertainty should have a documented current assumption.

**Uncertainty graveyard:** Listing uncertainties that never get resolved.
- Fix: Review open uncertainties at plan completion. Resolve or explicitly defer.

**Over-engineering resolution:** Creating ADRs for trivial decisions.
- Fix: Match resolution weight to uncertainty importance.

---

## Meta-Meta-Process

This pattern is itself part of how we improve the meta-process:

1. When working on any project, uncertainties about process arise
2. Resolve them using this pattern
3. If resolution is reusable, create a new pattern
4. The meta-process improves incrementally through use

This is how Pattern #33 was created - by encountering uncertainty handling as an uncertainty during Plan #294.

---

## References

- `docs/DESIGN_CLARIFICATIONS.md` - Decision rationale archive
- `meta-process/ISSUES.md` - Meta-process gaps
- `docs/adr/TEMPLATE.md` - ADR template

# Pattern: Question-Driven Planning

## Problem

Traditional planning starts with solutions:
- "We need to implement X using Y approach"
- AI makes assumptions to fill gaps
- Assumptions often wrong, discovered late
- Wasted work when assumptions collapse

The root cause: **planning before understanding**.

AI assistants are particularly prone to this because:
- They have broad knowledge but shallow project context
- They confidently fill gaps with reasonable-sounding guesses
- They don't naturally surface uncertainties
- Each session starts fresh, re-inventing assumptions

## Solution

Flip the process: **questions before plans**.

1. **Surface questions** - What do we need to know?
2. **Investigate** - Read code, not guess
3. **Resolve** - Get answers from code or human
4. **Plan** - Only after questions are answered

### The Core Principle

> "Don't guess, verify. Every 'I believe' or 'might be' must become 'I verified by reading X'."

This isn't about being slow. It's about:
- Finding issues early (cheap to fix)
- Building on facts, not assumptions
- Reducing rework from collapsed assumptions

## Files

| File | Purpose |
|------|---------|
| Plan files | Include "Open Questions" section |
| `docs/CONCEPTUAL_MODEL.yaml` | Track model-level questions |
| Session context files | Track session-specific questions |

## Process

### Phase 1: Question Elicitation

When starting work, explicitly list unknowns:

```markdown
## Open Questions (Before Planning)

1. [ ] Where does permission checking happen currently?
   - Status: OPEN
   - Why it matters: Need to know where to add new checks

2. [ ] Is "owner" a real concept or informal shorthand?
   - Status: OPEN
   - Why it matters: Affects how we model access control

3. [ ] What happens if contract is missing?
   - Status: OPEN
   - Why it matters: Need to handle edge case
```

### Phase 2: Investigation (Not Guessing)

For each question:

```markdown
## Question: Where does permission checking happen?

### Investigation
- Read `src/world/action_executor.py:45-120` - found permission_checker call
- Read `src/world/permission_checker.py` - this is where checks happen
- Read `src/world/contracts.py` - contracts define policy

### Answer
Permission checking happens in `permission_checker.py`, called from
`action_executor.py` before each action. Contracts define policy,
checker enforces it.

### Status: RESOLVED
```

### Phase 3: Resolution

Questions can resolve in three ways:

| Resolution | Example | Action |
|------------|---------|--------|
| Found in code | "Permission checks are in permission_checker.py" | Document finding |
| Human decision needed | "Should we support multi-party escrow?" | Ask human |
| Deferred | "We'll discover this during implementation" | Mark as accepted risk |

### Phase 4: Plan (Only After Resolution)

Only after critical questions are resolved:

```markdown
## Plan

### Prerequisites Verified
- [x] Permission checking location: `permission_checker.py`
- [x] Contract model: contracts define policy, kernel enforces
- [x] Edge case: missing contract uses kernel default

### Steps
1. Add new permission type to `permission_checker.py`
2. ...
```

## Usage

### Starting New Work

```
Human: "Add rate limiting to the API"

AI: Before planning, let me identify what I need to understand:

## Open Questions
1. [ ] Is there existing rate limiting? Where?
2. [ ] What's the rate limit scope? (per-user, global, per-endpoint?)
3. [ ] Where do API requests enter the system?

Let me investigate these before proposing a plan.
```

### Mid-Implementation Discovery

When assumptions break during work:

```markdown
## New Question Discovered

During implementation, found that `caller_id` is not available
in the context I expected.

**Question:** How does the kernel provide caller identity?
**Status:** BLOCKING - cannot proceed until resolved
**Investigation:** Reading kernel_interface.py...
```

### Escalation: When Plan Meets Reality

When investigation reveals the plan's assumptions are wrong, follow these steps:

**1. Record in CONTEXT.md**

Add the conflict to the "Discovered Conflicts" section so it survives context compaction:

```markdown
## Discovered Conflicts
- Plan assumes caller_id in handler context, but handler receives request_id only
- Impact: Step 3 needs redesign; requires ledger lookup
```

**2. Update the plan file**

Add a note to the plan documenting what changed and why. This keeps the plan as a living document, not a stale spec.

**3. Decide: continue, scope-reduce, or stop**

| Situation | Action |
|-----------|--------|
| Plan achievable with adjustment | Update plan steps, commit with `[Plan #N] Adjust: <reason>`, continue |
| Scope needs reduction | Mark deferred steps in plan, commit with explanation, continue reduced |
| Fundamental assumption collapsed | Stop, commit progress with `[Plan #N] BLOCKED: <reason>`, ask human |

The key discipline: **never silently deviate from the plan.** Every divergence gets a commit message explaining why.

### The Investigation Discipline

When tempted to guess:

| Instead of... | Do this... |
|---------------|------------|
| "I believe X uses Y" | Read the code: `grep -r "X" src/` |
| "This might work" | Find similar patterns: `grep -r "similar_pattern"` |
| "The owner should" | Check model: Is "owner" in non_existence? |
| "Presumably..." | Stop. What would resolve this presumption? |

## Example: Real Session

From Plan #229 conceptual modeling work:

```
Human: "where would a code that kept adding 1 in a loop fall?"

AI: Good question - this exposes a gap in my categorization.
    Let me reconsider...

    I had mutually exclusive subtypes, but this code doesn't
    fit any of them. This suggests subtypes should be
    PROPERTIES not CATEGORIES.

    Updated model:
    - Properties: executable, has_standing, has_loop
    - Labels: non-exclusive convenience names
```

The question drove the model improvement.

## Customization

### Question Tracking Location

| Project Size | Tracking Approach |
|--------------|-------------------|
| Small | Inline in plan files |
| Medium | Dedicated "Open Questions" section in each plan |
| Large | Separate `docs/questions/` directory |
| Research | `docs/CONCEPTUAL_MODEL.yaml` open_questions section |

### Question Priority

```markdown
## Open Questions

### Blocking (Must Resolve Before Plan)
1. [ ] How does X work?

### Important (Should Resolve Before Implementation)
2. [ ] What's the performance impact?

### Nice to Know (Can Discover During Implementation)
3. [ ] Are there similar patterns elsewhere?
```

## Limitations

- **Takes longer upfront** - Investigation time before planning
- **Requires discipline** - Easy to skip when confident
- **Can't answer everything** - Some questions need experiments
- **Human bottleneck** - Some questions only human can answer

## Integration with Other Patterns

| Pattern | Integration |
|---------|-------------|
| Conceptual Modeling | Questions drive model updates |
| Plan Workflow | Plans include "Open Questions" section |
| Acceptance Gates | Specs should have questions resolved first |
| References Reviewed | Same spirit - verify before assuming |

## The Payoff

Question-driven planning catches issues early:

| Traditional | Question-Driven |
|-------------|-----------------|
| Plan → Implement → Discover assumption wrong → Rework | Question → Investigate → Find issue → Adjust plan → Implement |
| Cost: High (late discovery) | Cost: Low (early discovery) |

## Origin

Emerged from Plan #229 when the human repeatedly pushed back on guesses:
- "investigate all your 'believes' and 'mights' - we don't want to guess"
- "this is potentially worse because it reinforces the misconception"
- "where would a code that kept adding 1 in a loop fall?"

Each pushback revealed an unasked question that, when investigated, improved understanding.

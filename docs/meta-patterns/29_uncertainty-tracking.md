# Pattern: Uncertainty Tracking

## Problem

Planning involves uncertainty. Without explicit tracking:
- Uncertainties get forgotten mid-session
- Different sessions make different assumptions about the same unknown
- "Resolved" questions get re-opened without context
- No audit trail of how understanding evolved

AI assistants are especially prone to:
- Forgetting uncertainties across context compaction
- Confidently proceeding despite unresolved questions
- Losing the reasoning behind resolutions

## Solution

Explicitly track uncertainties with:
1. **Status** - open, investigating, resolved, deferred
2. **Resolution** - what was decided and why
3. **Context** - what led to this question

### Uncertainty Lifecycle

```
OPEN → INVESTIGATING → RESOLVED
                    → DEFERRED (accepted risk)
                    → BLOCKED (needs external input)
```

## Files

| File | Purpose |
|------|---------|
| `docs/CONCEPTUAL_MODEL.yaml` | Model-level open questions |
| Plan files | Plan-specific uncertainties |
| `.claude/CONTEXT.md` | Session-specific tracking |

## Format

### In YAML (Conceptual Model)

```yaml
open_questions:
  - question: "What metadata does the kernel provide to contracts?"
    status: open  # open | investigating | resolved | deferred
    context: "Contracts need caller identity for permission checks"
    raised: "2026-01-28"
    resolution: null

  - question: "Should contracts be able to reference other contracts?"
    status: resolved
    context: "Needed for composable access control"
    raised: "2026-01-27"
    resolved: "2026-01-28"
    resolution: |
      Yes - contracts can reference other contracts.
      The contract pointed to by artifact.contract_id is the
      immediate authority. That contract can delegate to others.
      Verified in: src/world/contracts.py:45-80
```

### In Markdown (Plans)

```markdown
## Open Questions

### Q1: Where does permission checking happen?
**Status:** ✅ Resolved
**Raised:** 2026-01-28
**Resolution:** Permission checking is in `permission_checker.py:34-89`,
called from `action_executor.py` before each action execution.

---

### Q2: What's the default when no contract exists?
**Status:** 🔍 Investigating
**Raised:** 2026-01-28
**Context:** Need to handle edge case of artifacts without contracts
**Investigation notes:**
- Checked `permission_checker.py` - no default handling found
- Checking `genesis_contracts.py` next...

---

### Q3: Should we support multi-party escrow?
**Status:** ⏸️ Deferred
**Raised:** 2026-01-28
**Resolution:** Out of scope for current plan. Added to future backlog.
**Risk accepted:** Single-party escrow may be limiting; will revisit if needed.
```

## Status Definitions

| Status | Symbol | Meaning | Action |
|--------|--------|---------|--------|
| Open | ❓ | Not yet investigated | Needs investigation |
| Investigating | 🔍 | Actively looking | Continue investigation |
| Resolved | ✅ | Answer found | Document resolution |
| Deferred | ⏸️ | Accepted risk | Document why deferred |
| Blocked | 🚫 | Needs external input | Wait for human/event |

## Usage

### Creating New Uncertainty

When you encounter something you're not sure about:

```markdown
### Q[N]: [Clear question statement]
**Status:** ❓ Open
**Raised:** [date]
**Context:** [Why this matters for current work]
```

### Investigation Trail

As you investigate, update the entry:

```markdown
### Q3: How does the kernel provide caller identity?
**Status:** 🔍 Investigating
**Raised:** 2026-01-28
**Context:** Contracts need verified caller ID for permission checks

**Investigation:**
- [2026-01-28 10:00] Checked `kernel_interface.py` - found KernelState class
- [2026-01-28 10:15] Read `action_executor.py:45-80` - caller_id injected here
- [2026-01-28 10:30] Found it: kernel extracts caller from action context
```

### Resolution

When resolved, document what you found:

```markdown
### Q3: How does the kernel provide caller identity?
**Status:** ✅ Resolved
**Raised:** 2026-01-28
**Resolved:** 2026-01-28
**Resolution:**
Kernel extracts `caller_id` from the action context in
`action_executor.py:52`. This is passed to `permission_checker.py`
which provides it to contracts. The caller_id is verified by the
kernel (agents can't spoof it).

**Verified in:**
- `src/world/action_executor.py:52-55`
- `src/world/permission_checker.py:30-40`
```

### Deferral

When accepting uncertainty as risk:

```markdown
### Q5: What happens with very deep contract chains?
**Status:** ⏸️ Deferred
**Raised:** 2026-01-28
**Resolution:** Deferred - accepting risk that deep chains could cause
performance issues. Will add depth limit if observed in practice.
**Risk:** Potential stack overflow with malicious contract chains.
**Mitigation:** Can add depth limit later without breaking API.
```

## Context Preservation Across Sessions

For long-running work, uncertainties help new sessions understand state:

```markdown
# Session Context (.claude/CONTEXT.md)

## Current Uncertainties

### Resolved This Session
- Q1: Permission checking location → `permission_checker.py`
- Q2: Contract default behavior → kernel default contract

### Still Open
- Q3: Kernel-provided metadata details
- Q4: Bootstrap sequence (what exists at time zero)

### Deferred
- Q5: Deep contract chain handling (accepted risk)
```

A new session reading this knows:
- What was figured out (don't re-investigate)
- What's still unknown (needs attention)
- What risks were accepted (don't re-raise)

## Customization

### Granularity

| Project Phase | Tracking Level |
|---------------|----------------|
| Early exploration | Many uncertainties, light resolution notes |
| Active development | Fewer uncertainties, detailed resolutions |
| Maintenance | Only blocking uncertainties tracked |

### Integration with Todo Systems

```markdown
## Tasks

- [ ] Implement permission checker
  - Blocked by: Q3 (kernel metadata details)

- [ ] Write contract tests
  - Depends on: Q2 resolution (default behavior)
```

## Limitations

- **Overhead** - Tracking takes time
- **Staleness** - Old unresolved questions accumulate
- **Subjectivity** - What counts as "resolved" varies
- **No automation** - Manual tracking required

### Mitigation

- Periodic cleanup: Archive old deferred questions
- Clear criteria: "Resolved when verified in code"
- Session handoff: Transfer uncertainties explicitly

## Integration with Other Patterns

| Pattern | Integration |
|---------|-------------|
| Conceptual Modeling | Model's `open_questions` section |
| Question-Driven Planning | Uncertainties drive the questions |
| Plan Workflow | Plans include uncertainty section |
| Session Context | `.claude/CONTEXT.md` tracks per-session |

## Origin

Emerged from Plan #229 when uncertainties kept getting lost:
- Questions raised in one part of conversation forgotten later
- Same questions re-investigated across sessions
- No record of why certain decisions were made

Explicit tracking preserved context across the session and for future work.

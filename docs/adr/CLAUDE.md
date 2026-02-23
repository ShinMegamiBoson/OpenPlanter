# Architecture Decision Records

ADRs document significant architectural decisions.

## ADR Index

| # | Title | Status | Date |
|---|-------|--------|------|
| 0001 | Use ADRs | Accepted | YYYY-MM-DD |

## ADR Lifecycle

```
Proposed → Accepted/Rejected → Superseded (optional)
```

## Creating an ADR

1. Copy template to `NNNN-title.md`
2. Fill in sections
3. Add to index above
4. Get review if needed

## ADR Template

```markdown
# ADR-NNNN: Title

Status: Proposed | Accepted | Rejected | Superseded by ADR-XXXX
Date: YYYY-MM-DD

## Context
What is the issue that we're seeing that motivates this decision?

## Decision
What is the change that we're proposing and/or doing?

## Consequences
What becomes easier or harder as a result of this decision?
```

## Status Meanings

| Status | Meaning |
|--------|---------|
| Proposed | Under discussion |
| Accepted | Decision made, being implemented |
| Rejected | Decided not to do this |
| Superseded | Replaced by newer ADR |

## Related

- `meta-process/patterns/07_adr.md` - Full ADR pattern

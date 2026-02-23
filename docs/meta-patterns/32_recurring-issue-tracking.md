# Pattern 32: Recurring Issue Tracking

## Problem

Some issues recur repeatedly. Each time they happen:
- Someone "fixes" them
- The fix doesn't address root cause
- The issue returns
- No one remembers what was tried before
- We go in circles

This wastes time and leads to frustration ("didn't we fix this already?").

## Solution

Create an **incident log** for recurring issues that tracks:
1. Every occurrence with details
2. What was tried
3. What worked (or didn't)
4. Root cause analysis over time

## Structure

An incident log has these sections:

### 1. Known Failure Classes

Categorize the types of failures you've seen. Give each a letter (A, B, C).
Include:
- **Symptom**: What does the user see?
- **Root cause**: What actually causes it?
- **Recovery**: How to get back to working state

### 2. Defenses In Place

Table of preventive measures already implemented:
- What it is
- Where it lives
- What it does
- Whether it actually works

### 3. What Would Actually Fix This

Honest assessment of real solutions, not band-aids. This section admits
when current defenses are insufficient.

### 4. Incident Log

Chronological record of every occurrence:
- Date and context
- Which failure class
- What triggered it
- What was observed
- Root cause analysis
- How it was resolved
- Follow-up actions taken

### 5. Investigation Checklist

Steps to diagnose new occurrences. Helps future investigators not miss
obvious checks.

## Template

```markdown
# [Issue Name] Incident Log

This log tracks every occurrence of [issue]. The purpose is to stop running
in circles — we keep "fixing" these without fixing them.

## Known Failure Classes

### Class A: [Name]

**Symptom:** What the user sees
**Root cause:** What actually causes it
**Recovery:** How to get back to working state

### Class B: [Name]
...

## Defenses In Place

| Defense | Location | What it does | Effective? |
|---------|----------|--------------|------------|
| ... | ... | ... | Yes/No/Partial |

## What Would Actually Fix This

### For Class A:
1. ...

### For Class B:
1. ...

## Incident Log

### Incident #1 - YYYY-MM-DD

**Session/Context:** What was happening
**Class:** A, B, or C
**Trigger:** What caused it
**Symptoms:** What was observed
**Analysis:** Root cause investigation
**Resolution:** How it was fixed
**Follow-up:** Systemic improvements made

---

## Investigation Checklist

When this issue occurs, check:
1. ...
2. ...
3. ...
```

## When to Use

Create an incident log when:
- An issue has occurred **3+ times**
- Different people keep "fixing" it differently
- You find yourself saying "didn't we fix this?"
- Root cause is unclear despite multiple attempts

Don't create an incident log for:
- One-time issues (just fix them)
- Issues with obvious, permanent fixes
- Issues tracked elsewhere (use ISSUES.md for meta-process issues)

## Examples

- Incident logs for recurring issues (e.g., CI failures, merge conflicts)

## Integration with ISSUES.md

ISSUES.md tracks issues through their lifecycle (unconfirmed → monitoring →
planned → resolved). Incident logs are for issues that **keep recurring**
despite being "resolved."

If an issue in ISSUES.md keeps coming back:
1. Create an incident log for it
2. Link to the log from ISSUES.md
3. Change ISSUES.md status to "monitoring" with a note about the incident log

## Key Insight

The point isn't to track incidents — it's to **learn from them**. Each incident
should add to your understanding of the root cause. If incident #5 has the
same analysis as incident #1, you're not learning.

# Pattern #34: Engineering Workflow

**Complexity:** Medium
**Prerequisites:** Pattern #02 (CLAUDE.md), Pattern #07 (ADR), Pattern #10 (Doc-Code Coupling)

## Problem

Architectural decisions exist in docs (ADRs, design clarifications, CLAUDE.md files) but are not systematically loaded before implementation. This leads to:
- Implementing code that contradicts existing ADRs
- Repeating mistakes across sessions because corrections aren't persisted
- Compounding errors that only surface late (at merge time or in production)

## Solution

A 7-phase engineering workflow that requires context loading before implementation and correction persistence after.

## The 7 Phases

```
SCOPE → CONTEXT LOAD → AMBIGUITY CHECK → PLAN → IMPLEMENT → VERIFY → CLEANUP
```

### Phase 1: Scope

Identify affected files and systems. Nothing else yet.

**Output:** List of files that will be read or modified.

### Phase 2: Context Load (REQUIRED before editing `src/`)

For each affected file, load context hierarchically:

1. **CLAUDE.md chain** — root → `src/` → `src/module/` (auto-loaded by tooling)
2. **Governing ADRs** — look up file in `relationships.yaml` governance section, READ each ADR
3. **Coupled docs** — look up file in `relationships.yaml` couplings section
4. **Repo-specific docs** — look up in `meta-process.yaml` `custom_docs` section
5. **Known issues** — check CONCERNS.md, TECH_DEBT.md for references to affected files

**Tooling:** `python scripts/file_context.py <file1> <file2> ...` outputs all of the above.

**Output:** Context brief listing constraints, governing ADRs, known issues.

### Phase 3: Ambiguity Check

With context loaded, check for:

- ADR contradictions (prose says X, code examples show Y)
- Code that doesn't match what ADRs say it should do
- Unclear or conflicting requirements

**If contradictions found:** Surface to user BEFORE implementing. Don't assume which side is correct.

**If user resolves ambiguity:** Record resolution immediately (see Phase 7 for where).

### Phase 4: Plan

Design approach with Phase 2 constraints visible. Plan must include:

- **Relevant ADRs** section (which ADRs govern this work)
- **Constraints** section (what the ADRs require)
- **Files affected** with their governing context

Get user approval before implementing.

### Phase 5: Implement (with walkthrough)

Implementation includes incremental user walkthrough, scaled by risk:

| Risk Level | Walkthrough Granularity | When |
|-----------|------------------------|------|
| High | Per-change | Core system modifications (`src/world/`) |
| Medium | Per-file | Supporting code, config, agents |
| Low | Batch at end | Docs, meta-process, test updates |

User can override the level per task.

**Why not defer to post-implementation quiz:** The quiz catches comprehension gaps after code is written. By then, bad patterns may have compounded across multiple files. Incremental walkthrough catches divergence at the moment it happens.

### Phase 6: Verify

1. `make check` (tests, mypy, doc-coupling)
2. Re-read governing ADRs from Phase 2 — does implementation match?
3. Does code follow patterns in CLAUDE.md for affected directories?

### Phase 7: Cleanup & Persist

1. Update docs if code changed doc-coupled files
2. **Persist corrections** — if the user corrected a misunderstanding during this task:
   - ADR needs fixing → update or supersede the ADR
   - Directory-level constraint → update that dir's CLAUDE.md
   - Global constraint → update root CLAUDE.md
   - Term confusion → update GLOSSARY.md
   - Open question → add to UNCERTAINTIES.md
3. Fix contradictory governance metadata in `relationships.yaml` if found
4. Update TECH_DEBT.md if new debt was introduced or old debt resolved

**Key principle:** Corrections go to the file that will be loaded by Phase 2 next time someone works on the same code. Not to MEMORY.md (too generic), not to conversation (ephemeral).

## Relationship to Other Patterns

- **Pattern #28 (Question-Driven Planning):** Phase 3 is where questions get asked
- **Pattern #29 (Uncertainty Tracking):** Uncertainties discovered in Phase 3 go to UNCERTAINTIES.md
- **Pattern #33 (Uncertainty Resolution):** Resolution lifecycle feeds Phase 7 persistence
- **Pattern #10 (Doc-Code Coupling):** Phase 6 verification includes coupling checks
- **Pattern #15 (Plan Workflow):** Phase 4 uses the existing plan creation process

## Enforcement

- Phase 2 tooling: `scripts/file_context.py` makes context loading mechanical
- Phase 6: `make check` runs existing CI enforcement
- Phase 7: manual discipline (no automation yet — consider adding a post-merge hook)

## Anti-Patterns

- **Skipping Phase 2** — "I know this code, I don't need to read the ADRs" → leads to contradicting decisions you didn't know about
- **Persisting to MEMORY.md** — generic memory doesn't get surfaced contextually. Write to the file that Phase 2 will load next time.
- **Deferring ambiguity resolution** — "I'll figure it out during implementation" → the ambiguity compounds into the code

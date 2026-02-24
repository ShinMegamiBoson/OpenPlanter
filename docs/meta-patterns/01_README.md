# Meta Patterns

Reusable development process patterns. Each pattern solves a specific coordination or quality problem when working with AI coding assistants (Claude Code, etc.).

> **New to meta-process?** Start with the [Getting Started Guide](../GETTING_STARTED.md) for a step-by-step onboarding path.

## Core Patterns

These patterns work with a simple branch-based workflow. No special infrastructure required.

| Pattern | Problem Solved | Complexity | Requires |
|---------|----------------|------------|----------|
| [CLAUDE.md Authoring](02_claude-md-authoring.md) | AI assistants lack project context | Low | — |
| [Testing Strategy](03_testing-strategy.md) | Inconsistent test approaches | Low | — |
| [Mocking Policy](04_mocking-policy.md) | When to mock, when not to | Low | — |
| [Mock Enforcement](05_mock-enforcement.md) | Green CI, broken production | Low | 04 |
| [Git Hooks](06_git-hooks.md) | CI failures caught late | Low | — |
| [ADR](07_adr.md) | Architectural decisions get lost | Medium | — |
| [ADR Governance](08_adr-governance.md) | ADRs not linked to code | Medium | 07 |
| [Documentation Graph](09_documentation-graph.md) | Can't trace decisions → code | Medium | 07, 10 |
| [Doc-Code Coupling](10_doc-code-coupling.md) | Docs drift from code | Medium | — |
| [Terminology](11_terminology.md) | Inconsistent terms | Low | — |
| [Structured Logging](12_structured-logging.md) *(proposed)* | Unreadable logs | Low | — |
| [Acceptance-Gate-Driven Development](13_acceptance-gate-driven-development.md) | AI drift, cheating, big bang integration | High | 07 |
| [Acceptance Gate Linkage](14_acceptance-gate-linkage.md) | Sparse file-to-constraint mappings | Medium | 13 |
| [Plan Workflow](15_plan-workflow.md) | Untracked work, scope creep | Medium | — |
| [Plan Blocker Enforcement](16_plan-blocker-enforcement.md) | Blocked plans started anyway | Medium | 15 |
| [Verification Enforcement](17_verification-enforcement.md) | Untested "complete" work | Medium | 15 |
| [Human Review Pattern](22_human-review-pattern.md) | Risky changes merged without review | Medium | 17 |
| [Plan Status Validation](23_plan-status-validation.md) | Status/content mismatch in plans | Low | 15 |
| [Phased ADR Pattern](24_phased-adr-pattern.md) | Complex features need phased rollout | Medium | 07 |
| [PR Review Process](25_pr-review-process.md) | Inconsistent review quality | Low | — |
| [Conceptual Modeling](27_conceptual-modeling.md) | AI accumulates misconceptions about architecture | Medium | — |
| [Question-Driven Planning](28_question-driven-planning.md) | AI guesses instead of investigating | Low | — |
| [Uncertainty Tracking](29_uncertainty-tracking.md) | Uncertainties forgotten across sessions | Low | — |
| [Gap Analysis](30_gap-analysis.md) | Ad-hoc planning misses gaps between current and target | Medium | 28 |
| [External LLM Review](31_external-llm-review.md) | AI misses issues humans would catch | Low | — |
| [Recurring Issue Tracking](32_recurring-issue-tracking.md) | Issues recur despite "fixes", going in circles | Low | — |
| [Uncertainty Resolution](33_uncertainty-resolution.md) | Uncertainties listed but never resolved | Low | 29 |

## Worktree Coordination Module (opt-in)

For teams running **multiple AI instances concurrently** on the same codebase. Provides file isolation via git worktrees and claim-based coordination to prevent conflicts.

> **Most projects don't need this.** A simple branch-based workflow (one instance at a time) works well. Enable this module only when parallel AI instances cause real coordination problems.

See [worktree-coordination/README.md](worktree-coordination/README.md) for setup and usage.

| Pattern | Problem Solved | Complexity | Requires |
|---------|----------------|------------|----------|
| [Claim System](worktree-coordination/18_claim-system.md) | Parallel work conflicts | Medium | — |
| [Worktree Enforcement](worktree-coordination/19_worktree-enforcement.md) | Main directory corruption from parallel edits | Low | 18 |
| [Rebase Workflow](worktree-coordination/20_rebase-workflow.md) | Stale worktrees causing "reverted" changes | Low | 19 |
| [PR Coordination](worktree-coordination/21_pr-coordination.md) | Lost review requests | Low | 15, 18 |
| [Ownership Respect](worktree-coordination/26_ownership-respect.md) | CC instances interfering with each other's work | Low | 18 |

## When to Use

**Start with these (low overhead):**
- CLAUDE.md Authoring - any project using AI coding assistants
- Git Hooks - any project with CI
- Question-Driven Planning - AI tendency to guess instead of investigate
- Uncertainty Tracking - preserve context across sessions
- Plan Workflow - for larger tasks with multiple steps

**Add these when needed (more setup):**
- Doc-Code Coupling - when docs drift from code
- ADR + ADR Governance - when architectural decisions need to be preserved
- Acceptance-Gate-Driven Development - verified progress, preventing AI drift/cheating
- Verification Enforcement - when plans need proof of completion
- Conceptual Modeling - when AI instances repeatedly misunderstand core concepts
- Gap Analysis - systematic comparison of current vs target architecture

**Multi-CC coordination (opt-in module):**
- Claim System + Worktree Enforcement - when multiple AI instances run concurrently
- PR Coordination + Ownership Respect - cross-instance work tracking

> **Conventions vs. patterns:** Patterns 06 (Git Hooks) and 11 (Terminology) are infrastructure or conventions rather than coordination patterns. They have no dependencies and can be adopted independently.

## Pattern Template

When adding new patterns, follow this structure:

```markdown
# Pattern: [Name]

## Problem
What goes wrong without this?

## Solution
How does this pattern solve it?

## Files
| File | Purpose |
|------|---------|
| ... | ... |

## Setup
Steps to add to a new project.

## Usage
Day-to-day commands.

## Customization
What to change for different projects.

## Limitations
What this pattern doesn't solve.
```

## Origin

These patterns emerged from the [agent_ecology](https://github.com/BrianMills2718/agent_ecology2) project while coordinating multiple Claude Code instances on a shared codebase.

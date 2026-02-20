# OpenPlanter — Claude Code Skill

A [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skill that extracts OpenPlanter's investigation methodology into standalone, zero-dependency Python scripts. Resolve entities, cross-reference datasets, build evidence chains, and score confidence tiers — all from Claude Code's terminal.

## Why a Skill?

OpenPlanter is a full agent with TUI, LLM providers, recursive sub-tasks, and session management. The skill distills its **methodology** — entity resolution, evidence chain construction, confidence scoring — into lightweight scripts that run inside Claude Code without spinning up the full agent.

Use the skill when you want OpenPlanter's analytical tradecraft in any Claude Code session, on any dataset, without configuring providers or launching the TUI.

## Installation

Copy the `skills/openplanter/` directory into your Claude Code skills folder:

```bash
# From this repo
cp -r skills/openplanter ~/.claude/skills/openplanter
```

Or clone and symlink:

```bash
git clone https://github.com/ShinMegamiBoson/OpenPlanter.git
ln -s "$(pwd)/OpenPlanter/skills/openplanter" ~/.claude/skills/openplanter
```

Claude Code discovers skills automatically from `~/.claude/skills/`.

## Quick Start

```bash
# 1. Initialize a workspace
python3 ~/.claude/skills/openplanter/scripts/init_workspace.py /tmp/investigation

# 2. Add datasets
cp campaign_finance.csv lobbying.json /tmp/investigation/datasets/

# 3. Resolve entities across datasets
python3 ~/.claude/skills/openplanter/scripts/entity_resolver.py /tmp/investigation

# 4. Cross-reference linked records
python3 ~/.claude/skills/openplanter/scripts/cross_reference.py /tmp/investigation

# 5. Validate evidence chains
python3 ~/.claude/skills/openplanter/scripts/evidence_chain.py /tmp/investigation

# 6. Score confidence
python3 ~/.claude/skills/openplanter/scripts/confidence_scorer.py /tmp/investigation
```

## Scripts

All scripts use Python stdlib only. Zero external dependencies. Python 3.10+.

| Script | Purpose |
|--------|---------|
| `init_workspace.py` | Create workspace directory structure (`datasets/`, `entities/`, `findings/`, `evidence/`, `plans/`) |
| `entity_resolver.py` | Fuzzy entity matching with Union-Find clustering. Produces `entities/canonical.json` |
| `cross_reference.py` | Link records across datasets using the canonical entity map. Produces `findings/cross-references.json` |
| `evidence_chain.py` | Validate evidence chain structure (hops, corroboration, source records) |
| `confidence_scorer.py` | Re-score findings by confidence tier. Updates JSON files in-place |

### Entity Resolver

Normalize → Block → Compare → Score → Cluster:

```bash
# Default threshold (0.85)
python3 scripts/entity_resolver.py /path/to/workspace

# Lower threshold for wider matching
python3 scripts/entity_resolver.py /path/to/workspace --threshold 0.70

# Specify which columns contain entity names
python3 scripts/entity_resolver.py /path/to/workspace --name-columns "name,contributor_name,registrant"
```

Name normalization includes: Unicode NFKD decomposition, diacritic stripping, legal suffix removal (LLC, Inc, Corp, Ltd, etc.), ampersand canonicalization (`&` → `and`), noise word removal (`the`, `a`, `an`, `of`), punctuation stripping, whitespace collapse.

Blocking uses first-3-character keys with sorted-neighborhood cross-block comparison to reduce O(N^2) pairwise cost.

### Cross-Reference

Requires `entities/canonical.json` (run entity resolver first):

```bash
# All datasets
python3 scripts/cross_reference.py /path/to/workspace

# Specific datasets only
python3 scripts/cross_reference.py /path/to/workspace --datasets campaign.csv lobby.json

# Require 3+ datasets for a match
python3 scripts/cross_reference.py /path/to/workspace --min-datasets 3
```

### Confidence Scorer

```bash
# Dry run (show changes without modifying)
python3 scripts/confidence_scorer.py /path/to/workspace --dry-run

# Score and update in-place
python3 scripts/confidence_scorer.py /path/to/workspace
```

## Confidence Tiers

Based on the Admiralty System (NATO AJP-2.1):

| Tier | Criteria |
|------|----------|
| **Confirmed** | 2+ independent sources with different collection paths AND high similarity (≥0.85); or hard signal match (EIN, phone) across sources |
| **Probable** | Strong single source (official record); 2+ sources with moderate similarity; or hard signal with ≥0.70 similarity |
| **Possible** | Circumstantial evidence only; moderate fuzzy match (0.55–0.84); single-source chain with ≤3 hops |
| **Unresolved** | Contradictory evidence; conflicting hard identifiers; insufficient data; weak chain |

Hard signals (EIN, TIN, phone, email) are verified for **agreement**, not just presence. Conflicting identifiers across variants force "unresolved" status.

## Workspace Structure

```
investigation/
├── datasets/          # Source CSV/JSON files
├── entities/
│   └── canonical.json # Entity resolution output
├── findings/
│   └── cross-references.json
├── evidence/
│   ├── chains.json
│   └── scoring-log.json
└── plans/
    └── plan.md        # Investigation plan
```

## Methodology

The skill encodes OpenPlanter's epistemic discipline:

1. **Ground truth comes from files, not memory.** Read actual data before modifying.
2. **Success does not mean correctness.** Verify outcomes, not exit codes.
3. **Three failures = wrong approach.** Change strategy entirely.
4. **Produce artifacts early.** Write a working first draft, then iterate.
5. **Implementation and verification must be uncorrelated.** The agent that performs analysis must not be its sole verifier.

See `SKILL.md` for the full methodology reference, including:
- Entity Resolution Protocol (6-stage pipeline)
- Evidence Chain Construction (Admiralty grading)
- Analysis of Competing Hypotheses (ACH)
- Key Assumptions Check
- Multi-agent investigation patterns

## Reference Documents

| File | Contents |
|------|----------|
| `SKILL.md` | Full methodology — entity resolution, evidence chains, confidence scoring, ACH, multi-agent patterns |
| `references/entity-resolution-patterns.md` | Normalization tables, suffix maps, address canonicalization |
| `references/investigation-methodology.md` | Epistemic framework extracted from OpenPlanter's `prompts.py` |
| `references/output-templates.md` | JSON/Markdown templates for investigation deliverables |

## Relation to the OpenPlanter Agent

| | Agent (`openplanter-agent`) | Skill (`skills/openplanter/`) |
|---|---|---|
| Runtime | Full TUI + recursive sub-agents | Claude Code terminal |
| Dependencies | `rich`, `prompt_toolkit`, LLM providers | Python stdlib only |
| Entity resolution | LLM-assisted (via tool calls) | `difflib.SequenceMatcher` |
| Web search | Exa API | Bring your own (e.g. `exa-search` skill) |
| Session management | Built-in persistence | Claude Code sessions |
| Confidence scoring | Inline in prompts | Standalone scorer script |

The skill complements the agent. Use the agent for full autonomous investigations. Use the skill for targeted analysis within existing Claude Code workflows.

## Multi-Agent Investigation

For complex investigations requiring parallel workstreams, the skill composes with [**minoan-swarm**](https://github.com/tdimino/claude-code-minoan/tree/main/skills/planning-productivity/minoan-swarm) — a Claude Code skill for multi-agent teams with shared task lists and parallel workstreams. Separate the verifier agent from analysis agents to maintain uncorrelated verification.

See `SKILL.md` § Multi-Agent Investigation and `references/investigation-methodology.md` for the swarm role template.

## Contributing

Scripts should remain zero-dependency (Python stdlib only). Add new scripts to `scripts/`, update `SKILL.md`, and ensure `--help` works.

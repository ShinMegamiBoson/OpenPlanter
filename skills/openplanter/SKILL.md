---
name: openplanter
description: "Dataset investigation and entity resolution using OpenPlanter methodology. This skill should be used when cross-referencing heterogeneous datasets, performing entity resolution, building evidence chains with confidence tiers, or conducting structured investigations requiring epistemic discipline."
argument-hint: "[workspace-path or investigation-query]"
---

# OpenPlanter — Investigation Methodology Skill

Epistemic framework for cross-dataset investigation, entity resolution, and evidence-backed analysis. Extracted from the [OpenPlanter](https://github.com/ShinMegamiBoson/OpenPlanter) recursive investigation agent and enriched with professional OSINT tradecraft (Admiralty System, ACH, FollowTheMoney schema, intelligence cycle methodology).

Claude Code already has the tools. This skill provides the **methodology**.

## When to Use

- Cross-referencing heterogeneous datasets (corporate registries, campaign finance, lobbying, property records, contracts)
- Entity resolution across datasets with inconsistent naming
- Building evidence chains with provenance and confidence tiers
- Structured OSINT investigations requiring epistemic discipline
- Any analysis where claims need to trace to cited source records

## Quick Start

```bash
# 1. Initialize workspace
python3 ~/.claude/skills/openplanter/scripts/init_workspace.py /path/to/investigation

# 2. Drop datasets into datasets/
cp campaign_finance.csv lobbying.json corporate_registry.csv /path/to/investigation/datasets/

# 3. Write an investigation plan
# → plans/plan.md (see references/output-templates.md for plan template)

# 4. Resolve entities across datasets
python3 ~/.claude/skills/openplanter/scripts/entity_resolver.py /path/to/investigation

# 5. Cross-reference linked entities
python3 ~/.claude/skills/openplanter/scripts/cross_reference.py /path/to/investigation

# 6. Validate evidence chains
python3 ~/.claude/skills/openplanter/scripts/evidence_chain.py /path/to/investigation

# 7. Score confidence
python3 ~/.claude/skills/openplanter/scripts/confidence_scorer.py /path/to/investigation
```

## Investigation Methodology

### Epistemic Discipline

Assume nothing about the environment until confirmed firsthand. These principles prevent the most common investigation failures:

1. **Ground truth comes from files, not memory.** Read actual data before modifying it, and read actual error messages before diagnosing. Model memory of data structure is unreliable—reading the file takes seconds, recovering from a wrong assumption takes minutes.
2. **Empty output is ambiguous.** If a command returns empty, cross-check with `ls -la` and `wc -c` before concluding a file is actually empty, because output capture mechanisms can silently lose data.
3. **Success does not mean correctness.** A command that "succeeds" may have done nothing. Check actual outcomes, not just exit codes. After downloading, verify with `ls` and `wc -c`. After extraction, verify expected files exist.
4. **Verify round-trip correctness.** After any data transformation (parsing, linking, aggregation), check the result from the consumer's perspective—load the output, spot-check records, verify row counts. Transformations that silently drop records are the most common source of wrong conclusions.
5. **Three failures = wrong approach.** If a command fails 3 times, change strategy entirely. Repeating an identical command expecting different results wastes context window.
6. **Produce artifacts early.** Write a working first draft of findings as soon as the requirements are clear, then iterate. An imperfect deliverable beats a perfect analysis with no output. If 3+ steps have passed without writing any output, stop and write—even if incomplete.

For the full epistemic framework (including data ingestion rules and hard rules from OpenPlanter's prompts.py), see `references/investigation-methodology.md`.

### Entity Resolution Protocol

**Pipeline: Normalize → Block → Compare → Score → Cluster → Review**

Adapted from OpenPlanter's prompts.py, enriched with Middesk, OpenSanctions, and ICIJ patterns.

1. **Normalize** — Apply canonical key transformation: Unicode NFKD + diacritic stripping, case folding, legal suffix canonicalization (LLC/Inc/Corp/Ltd → canonical forms), punctuation removal, ampersand normalization (`&` → `and`). See `references/entity-resolution-patterns.md` for complete normalization tables and suffix maps.

2. **Block** — Reduce O(N^2) comparisons using blocking keys: first 3 characters of normalized name + state/jurisdiction, phonetic key (Soundex/Double Metaphone), token overlap via inverted index.

3. **Compare** — Pairwise similarity with cascading checks: `real_quick_ratio()` → `quick_ratio()` → `ratio()`. Use `autojunk=False` for entity names because strings under 200 characters produce false negatives with junk heuristics. Include token set comparison for word-order variants ("Apple Inc" vs "Inc Apple").

4. **Score** — Multi-signal weighted model:
   - Hard signals: TIN/EIN exact match (1.0), identical phone E.164 (0.8), identical email (0.8)
   - Soft signals: name similarity (0.5), address fuzzy (0.2), state match (0.1)
   - Hard disqualifiers: TIN mismatch when both present (-0.5), country mismatch (-0.5)

5. **Cluster** — Group via transitive closure using Union-Find. Gate closure so all pairwise scores exceed threshold—this prevents chain errors where A≈B and B≈C but A≉C. Exclude registered agent addresses from triggering transitive closure alone, because thousands of entities share the same registered agent.

6. **Review** — Flag by confidence band:
   - Score >= 0.85: auto-match (confirmed)
   - Score 0.70-0.84: queue for review (probable)
   - Score 0.55-0.69: include in wide net (possible)
   - Score < 0.55: discard

### Evidence Chain Construction

Every claim traces to a specific record in a specific dataset. This is what separates investigation from speculation.

```
Claim
  └── Evidence Item
        ├── type: document | record | image | testimony
        ├── source_ref → Source
        │     ├── url / file path
        │     ├── collection_timestamp
        │     ├── source_type: primary | secondary | tertiary | official | unofficial
        │     └── reliability_grade: A–F (Admiralty)
        ├── credibility_grade: 1–6 (Admiralty)
        ├── corroboration_status: single | corroborated | contradicted | unresolvable
        └── match_details (if cross-reference)
              ├── fields_matched: [name, address, ein]
              ├── match_type: exact | fuzzy | address-based
              └── link_strength: weakest criterion in the chain
```

**Key principles:**
- Distinguish direct evidence (A appears in record X), circumstantial evidence (A's address matches B's address), and absence of evidence (no disclosure found)
- Document every hop in a multi-step chain with source record, linking field, and match quality
- Link strength = weakest criterion in the chain (a chain is only as strong as its weakest link)
- Track source lineage to detect circular reporting—Source B citing Source A is not independent corroboration

### Confidence Tiers

Based on the Admiralty System (NATO AJP-2.1), adapted for dataset investigation:

| Tier | Criteria | Required Evidence | Admiralty Equivalent |
|------|----------|-------------------|---------------------|
| **Confirmed** | 2+ independent sources with different collection paths; hard signal match (EIN, phone); or official record with verifiable provenance | Independent corroboration required | A1–B1 |
| **Probable** | Strong single source (official record); high fuzzy match (>0.85) on name + address + state; consistent with known patterns | Single strong source acceptable | B2–C2 |
| **Possible** | Circumstantial evidence only; moderate fuzzy match (0.55-0.84); consistent but not yet corroborated; requires additional investigation | Hypothesis supported but not confirmed | C3–D3 |
| **Unresolved** | Contradictory evidence; insufficient data; single weak source; or unable to verify | Cannot determine with available evidence | D4–F6 |

**Sherman Kent probability mapping:**
- Confirmed ≈ "almost certain" (93-99%)
- Probable ≈ "likely" (75-85%)
- Possible ≈ "chances about even" (45-55%)
- Unresolved ≈ insufficient basis for estimate

### Verification Principle

**Implementation and verification must be uncorrelated.** An agent that performs an analysis introduces systematic bias when self-verifying—it "knows" what the answer should be and unconsciously confirms it. Use the implement-then-verify pattern:

```
Step 1: Perform entity resolution and cross-referencing (analysis agent)
Step 2: Read the result files
Step 3: Independent verification (separate agent or separate pass with no shared context from step 1):
        - Load output files fresh
        - Spot-check N random records against raw source data
        - Verify row counts match expectations
        - Run validation script
        - Report raw output only
```

The verification executor has no context from the analysis executor. It runs commands and reports output, making its evidence independent.

**Anti-bias checks:**
- **Confirmation bias**: Score hypotheses by inconsistency count (ACH), not confirmation count, because disconfirming evidence is more diagnostic
- **Anchoring**: Do not rank hypotheses until evidence collection is complete
- **Circular reporting**: Track source lineage; verify independence of collection paths before counting corroborations
- **Satisficing**: Require minimum 3 competing hypotheses before scoring—this prevents premature commitment to the first plausible explanation

### Analysis Output Standards

Include in all investigation deliverables:

1. **Methodology section**: Sources used, entity resolution approach, linking logic, known limitations
2. **Confidence breakdown**: Count of findings per tier (confirmed/probable/possible/unresolved)
3. **Evidence appendix**: Every hop, every source record cited, every match score
4. **Structured output**: JSON for machine-readable (`findings/`), Markdown for human-readable (`findings/`)
5. **Provenance**: For each dataset—source URL/path, access timestamp, transformations applied

See `references/output-templates.md` for ready-to-use templates (investigation plans, summaries, evidence chains).

## Integration Modes

The skill operates in three modes based on investigation complexity:

| Mode | When | Scripts |
|------|------|---------|
| **Methodology Only** | Simple tasks, 1-2 datasets, local analysis | `entity_resolver.py`, `cross_reference.py`, `evidence_chain.py`, `confidence_scorer.py` |
| **Web-Enriched** | Need external data, public records, entity enrichment | Above + `dataset_fetcher.py`, `web_enrich.py`, `scrape_records.py` |
| **Full RLM Delegation** | Complex multi-step investigations, 3+ datasets, 20+ reasoning steps | `delegate_to_rlm.py` → full OpenPlanter agent (provider-agnostic) |

**One-command pipeline** for any mode: `investigate.py /path/to/workspace --phases all`

### RLM Delegation — Provider-Agnostic

The RLM agent auto-detects the LLM provider from the model name. Works with any provider the agent supports:

```bash
# Anthropic (default)
python3 scripts/delegate_to_rlm.py --objective "..." --workspace DIR --model claude-sonnet-4-5-20250929

# OpenAI
python3 scripts/delegate_to_rlm.py --objective "..." --workspace DIR --model gpt-4o

# OpenRouter (any model via slash routing)
python3 scripts/delegate_to_rlm.py --objective "..." --workspace DIR --model anthropic/claude-sonnet-4-5

# Cerebras (model name doesn't contain "cerebras", so specify --provider)
python3 scripts/delegate_to_rlm.py --objective "..." --workspace DIR --model qwen-3-235b-a22b-instruct-2507 --provider cerebras
```

Provider auto-detection works for model names containing the provider name (e.g., `claude-*` → anthropic, `gpt-*` → openai, `org/model` → openrouter, `*cerebras*` → cerebras). For models without a recognizable prefix, pass `--provider` explicitly.

API keys pass through environment variables: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `CEREBRAS_API_KEY` (or `OPENPLANTER_`-prefixed variants).

## Scripts Reference

All scripts use Python stdlib only. Zero external dependencies. External tools (Exa, Firecrawl, OpenPlanter agent) are invoked as subprocesses.

### Core Analysis

| Script | Purpose | Example |
|--------|---------|---------|
| `init_workspace.py` | Create investigation workspace structure | `python3 scripts/init_workspace.py /tmp/investigation` |
| `entity_resolver.py` | Fuzzy entity matching + canonical map | `python3 scripts/entity_resolver.py /tmp/investigation --threshold 0.85` |
| `cross_reference.py` | Cross-dataset record linking | `python3 scripts/cross_reference.py /tmp/investigation` |
| `evidence_chain.py` | Validate evidence chain structure | `python3 scripts/evidence_chain.py /tmp/investigation` |
| `confidence_scorer.py` | Score findings by confidence tier | `python3 scripts/confidence_scorer.py /tmp/investigation` |

### Data Collection & Enrichment

| Script | Purpose | Example |
|--------|---------|---------|
| `dataset_fetcher.py` | Download bulk public datasets (SEC, FEC, OFAC, LDA) | `python3 scripts/dataset_fetcher.py /tmp/investigation --sources sec,fec` |
| `web_enrich.py` | Enrich entities via Exa neural search | `python3 scripts/web_enrich.py /tmp/investigation --categories company,news` |
| `scrape_records.py` | Fetch entity records from government APIs | `python3 scripts/scrape_records.py /tmp/investigation --entities "Acme Corp" --sources sec,fec` |

### Orchestration & Delegation

| Script | Purpose | Example |
|--------|---------|---------|
| `investigate.py` | Run full pipeline end-to-end | `python3 scripts/investigate.py /tmp/investigation --phases all` |
| `delegate_to_rlm.py` | Spawn full OpenPlanter agent (provider-agnostic) | `python3 scripts/delegate_to_rlm.py --objective "..." --workspace DIR` |

## Skill Integration

OpenPlanter methodology composes with existing Claude Code skills:

| Investigation Task | Skill | Integration Pattern |
|---|---|---|
| Web research for entity enrichment | `exa-search` | `web_enrich.py` calls `exa_search.py` as subprocess |
| Scrape JS-heavy public records portals | `Firecrawl` | `firecrawl scrape URL --only-main-content` |
| Structured government APIs | Built-in | `scrape_records.py` queries SEC, FEC, LDA, USAspending via `urllib` |
| Bulk dataset downloads | Built-in | `dataset_fetcher.py` fetches SEC, FEC, OFAC, OpenSanctions, LDA |
| Local RAG over large document corpora | `rlama` | Create collection from `datasets/`, query semantically |
| Parallel investigation threads | `minoan-swarm` | Elat Research Swarm with domain-split investigators |
| Academic/legal research | `academic-research` | Case law, regulatory filings, citations |
| Twitter/social media OSINT | `twitter` | `x-search` for entity mentions, `bird` for profile data |

### US Public Records Datasets

Key datasets and their linking keys for cross-reference investigations:

| Dataset | Access | Linking Key | Format |
|---|---|---|---|
| FEC Campaign Finance | `api.open.fec.gov` + bulk CSV | `committee_id`, contributor name | CSV, JSON API |
| Senate LDA Lobbying | `lda.senate.gov/api` | Registrant name, Client name | JSON API, XML |
| SEC EDGAR | `data.sec.gov` + EFTS search | `CIK` (Central Index Key) | JSON, XBRL |
| State Corporate Registries | Per-state (or OpenCorporates API) | State registration number, registered agent | Varies |
| Property Records | County-level (or ATTOM/CoreLogic) | Parcel ID (APN), owner name | CSV, shapefile |
| OFAC Sanctions | `treasury.gov/ofac` (or OpenSanctions) | Name + aliases, identifiers | CSV, XML |

**Cross-dataset linking challenge**: No universal corporate ID exists in US public records. The standard approach: normalize names, fuzzy match, filter by jurisdiction/address, then anchor on known IDs (CIK, committee_id, EIN) when available.

## Multi-Agent Investigation

For complex investigations requiring parallel workstreams, use `minoan-swarm`. Separate the verifier agent from analysis agents to maintain uncorrelated verification—the verifier receives only output files and verification criteria, with no shared context from the analysis phase.

See `references/investigation-methodology.md` for the full swarm role template (keret, kothar, resheph, anat, shapash).

## Structured Analytical Techniques

For complex scenarios with multiple possible explanations, apply Analysis of Competing Hypotheses (ACH) and Key Assumptions Check. These techniques are detailed in `references/investigation-methodology.md`.

**ACH summary**: Build a matrix of hypotheses vs. evidence. Score by **inconsistency count** (fewest I markers wins), not confirmation count. This counteracts confirmation bias because disconfirming evidence is more diagnostic than supporting evidence. Identify linchpin evidence whose reclassification would change the conclusion.

## Deep References

- `references/investigation-methodology.md` — Full epistemic framework, ACH procedure, Key Assumptions Check, multi-agent swarm template
- `references/entity-resolution-patterns.md` — Complete normalization tables, suffix maps, address canonicalization
- `references/output-templates.md` — JSON/Markdown templates for investigation plans, summaries, and evidence chains
- `references/public-records-apis.md` — API endpoints, auth, rate limits, linking keys for SEC, FEC, LDA, OFAC, USAspending

## OpenPlanter Tool to Claude Code Mapping

| OpenPlanter Tool | Claude Code Equivalent |
|---|---|
| `list_files` | `Glob`, `Bash(ls)` |
| `read_file` | `Read` |
| `write_file` | `Write` |
| `search_files` | `Grep` |
| `edit_file` | `Edit` |
| `apply_patch` | `Edit` |
| `run_shell` | `Bash` |
| `web_search` | `exa-search` skill |
| `fetch_url` | `Firecrawl` skill / `WebFetch` |
| `subtask` | `Task` tool (minoan-swarm) |
| `execute` | `Task` tool (haiku model) |
| `think` | Native reasoning |

No capability gap. The methodology is what matters, not the tooling.

# Output Templates

Ready-to-use templates for investigation deliverables.

## Investigation Summary (Markdown)

```markdown
# Investigation Summary: [Title]

**Date**: [YYYY-MM-DD]
**Investigator**: [name / agent]
**Workspace**: [path]

## Executive Summary

[2-3 sentence overview of key findings and confidence level]

## Methodology

### Data Sources
| Dataset | Records | Format | Collection Date | Source Reliability |
|---------|---------|--------|-----------------|-------------------|
| [name] | [N] | CSV/JSON | [date] | [A-F] |

### Entity Resolution Approach
- Normalization: [Unicode NFKD + suffix canonicalization + ...]
- Blocking: [first_3_chars + state]
- Similarity: [difflib.SequenceMatcher, threshold 0.85/0.70]
- Clustering: [Union-Find with threshold-gated transitive closure]

### Linking Logic
- Primary linking fields: [name, EIN, address]
- Match types used: [exact, fuzzy, address-based]
- Cross-reference strategy: [description]

### Known Limitations
- [Dataset gaps]
- [Entity resolution edge cases]
- [Temporal coverage limitations]

## Key Findings

### Finding 1: [Title]
**Confidence**: [Confirmed/Probable/Possible/Unresolved]

[Description of finding grounded in cited evidence]

**Evidence chain**:
1. [Source record A] → [field match] → [Source record B] (score: 0.92)
2. [Source record B] → [address match] → [Source record C] (score: 0.78)

### Finding 2: [Title]
...

## Confidence Breakdown

| Tier | Count | Percentage |
|------|-------|------------|
| Confirmed | [N] | [%] |
| Probable | [N] | [%] |
| Possible | [N] | [%] |
| Unresolved | [N] | [%] |

## Anti-Bias Checks Applied
- [x] Confirmation bias: scored by inconsistency (ACH)
- [x] Circular reporting: source lineage verified
- [x] Satisficing: 3+ hypotheses considered
- [ ] Independent verification: [pending/completed]

## Recommendations
1. [Next steps]
2. [Additional data to collect]
3. [Hypotheses to investigate further]

## Evidence Appendix

[Detailed evidence chains for each finding — see evidence/chains.json]
```

## Entity Map (JSON)

```json
{
  "metadata": {
    "created": "2026-02-20T12:00:00Z",
    "workspace": "/path/to/investigation",
    "datasets_processed": ["campaign.csv", "lobby.json", "registry.csv"],
    "total_entities": 142,
    "resolution_threshold": 0.85
  },
  "entities": [
    {
      "canonical_id": "entity-001",
      "canonical_name": "Acme Corporation",
      "entity_type": "organization",
      "variants": [
        {
          "name": "ACME CORP LLC",
          "source": "campaign.csv",
          "row": 42,
          "similarity": 0.91
        },
        {
          "name": "Acme Corporation",
          "source": "registry.csv",
          "row": 17,
          "similarity": 1.0
        },
        {
          "name": "Acme Corp.",
          "source": "lobby.json",
          "path": "$.registrants[3].name",
          "similarity": 0.95
        }
      ],
      "identifiers": {
        "ein": "12-3456789",
        "state_reg": "DE-1234567",
        "fec_committee_id": null
      },
      "properties": {
        "jurisdiction": "DE",
        "address": "1234 Main St, Wilmington, DE 19801",
        "industry": "Technology"
      },
      "confidence": "confirmed",
      "confidence_basis": "EIN exact match across 2 datasets + name similarity > 0.90"
    }
  ]
}
```

## Evidence Chain (JSON)

```json
{
  "metadata": {
    "investigation": "Campaign Finance Cross-Reference",
    "created": "2026-02-20T12:00:00Z",
    "total_chains": 23
  },
  "chains": [
    {
      "chain_id": "chain-001",
      "claim": "Acme Corporation made campaign contributions while simultaneously lobbying on related legislation",
      "confidence": "probable",
      "admiralty_grade": "B2",
      "hops": [
        {
          "hop": 1,
          "from_entity": "Acme Corp LLC",
          "from_dataset": "campaign.csv",
          "from_record": {"row": 42, "fields": {"contributor_name": "ACME CORP LLC", "amount": "$50,000", "recipient": "Committee XYZ", "date": "2025-03-15"}},
          "to_entity": "Acme Corporation",
          "to_dataset": "registry.csv",
          "to_record": {"row": 17, "fields": {"name": "Acme Corporation", "ein": "12-3456789", "status": "Active"}},
          "link_field": "name",
          "match_type": "fuzzy",
          "match_score": 0.91,
          "link_strength": "strong"
        },
        {
          "hop": 2,
          "from_entity": "Acme Corporation",
          "from_dataset": "registry.csv",
          "from_record": {"row": 17},
          "to_entity": "Acme Corp.",
          "to_dataset": "lobby.json",
          "to_record": {"path": "$.registrants[3]", "fields": {"name": "Acme Corp.", "client": "Self", "issue": "Technology regulation"}},
          "link_field": "name + ein",
          "match_type": "exact_ein + fuzzy_name",
          "match_score": 0.95,
          "link_strength": "strong"
        }
      ],
      "corroboration": {
        "status": "corroborated",
        "independent_sources": 3,
        "circular_check": "passed",
        "source_lineage": ["campaign.csv (FEC bulk 2025-Q1)", "registry.csv (DE SOS 2025-01)", "lobby.json (Senate LDA 2025-Q1)"]
      },
      "key_assumptions": [
        "ACME CORP LLC and Acme Corporation are the same legal entity (supported by EIN match)",
        "Lobbying activity is related to campaign contributions (temporal correlation within same quarter)"
      ],
      "falsification_conditions": [
        "EIN 12-3456789 belongs to a different entity than Acme Corporation in DE registry",
        "Lobbying issue area has no connection to recipient committee's jurisdiction"
      ]
    }
  ]
}
```

## Cross-Reference Report (Markdown)

```markdown
# Cross-Reference Report

**Datasets**: campaign.csv, lobby.json, registry.csv
**Date**: 2026-02-20
**Total cross-references found**: 47

## Match Summary

| Dataset Pair | Matches | Avg Score | Confirmed | Probable | Possible |
|---|---|---|---|---|---|
| campaign ↔ registry | 23 | 0.89 | 15 | 6 | 2 |
| campaign ↔ lobby | 18 | 0.82 | 8 | 7 | 3 |
| lobby ↔ registry | 31 | 0.91 | 22 | 7 | 2 |

## Highest-Confidence Cross-References

| Entity | Campaign | Lobby | Registry | Score | Confidence |
|---|---|---|---|---|---|
| Acme Corp | Row 42 ($50K to Cmte XYZ) | Reg #3 (Tech regulation) | Row 17 (DE, Active) | 0.95 | Confirmed |
| Beta Holdings | Row 108 ($25K to Cmte ABC) | Reg #7 (Energy policy) | Row 89 (NV, Active) | 0.88 | Probable |

## Entities Appearing in All Datasets

[List of entities with records in all loaded datasets — highest investigation priority]

## Entities with Conflicting Information

[List of entities where datasets contradict each other — requires investigation]

## Unresolved Matches (Manual Review Required)

| Entity A | Dataset | Entity B | Dataset | Score | Issue |
|---|---|---|---|---|---|
| Smith & Co | campaign.csv:205 | Smith Company LLC | registry.csv:312 | 0.72 | Possible DBA; confirm EIN |
```

## Workspace README (for init_workspace.py)

```markdown
# Investigation Workspace

## Structure

```
datasets/     — Raw source data (CSV, JSON). Never modify originals.
entities/     — Resolved entity maps (canonical.json)
findings/     — Analysis outputs (cross-references, summaries)
evidence/     — Evidence chains with full provenance
plans/        — Investigation plans and methodology docs
```

## Workflow

1. Drop datasets into `datasets/`
2. Write investigation plan in `plans/plan.md`
3. Run entity resolution: `entity_resolver.py`
4. Run cross-referencing: `cross_reference.py`
5. Validate evidence: `evidence_chain.py`
6. Score confidence: `confidence_scorer.py`
7. Review findings in `findings/`

## Provenance

Record for every dataset:
- Source URL or file path
- Access/download timestamp
- Any transformations applied
- Admiralty source reliability grade (A-F)
```

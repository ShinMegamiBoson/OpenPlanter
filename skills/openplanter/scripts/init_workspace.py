#!/usr/bin/env python3
"""Initialize an OpenPlanter investigation workspace.

Creates the standard directory structure for dataset investigation:
  datasets/   — Raw source data (CSV, JSON). Never modify originals.
  entities/   — Resolved entity maps (canonical.json)
  findings/   — Analysis outputs (cross-references, summaries)
  evidence/   — Evidence chains with full provenance
  plans/      — Investigation plans and methodology docs

Usage:
    python3 init_workspace.py /path/to/investigation
    python3 init_workspace.py /path/to/investigation --plan "Cross-reference campaign finance with lobbying"
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

DIRS = ["datasets", "entities", "findings", "evidence", "plans"]

README = """\
# Investigation Workspace

Created: {timestamp}

## Structure

```
datasets/     Raw source data (CSV, JSON). Never modify originals.
entities/     Resolved entity maps (canonical.json)
findings/     Analysis outputs (cross-references, summaries)
evidence/     Evidence chains with full provenance
plans/        Investigation plans and methodology docs
```

## Workflow

1. Drop datasets into `datasets/`
2. Write investigation plan in `plans/plan.md`
3. Run entity resolution: `entity_resolver.py <workspace>`
4. Run cross-referencing: `cross_reference.py <workspace>`
5. Validate evidence chains: `evidence_chain.py <workspace>`
6. Score confidence: `confidence_scorer.py <workspace>`
7. Review findings in `findings/`

## Provenance

Record for every dataset:
- Source URL or file path
- Access/download timestamp
- Any transformations applied
- Admiralty source reliability grade (A-F)

## Confidence Tiers

| Tier | Criteria |
|------|----------|
| Confirmed | 2+ independent sources; hard signal match (EIN, phone) |
| Probable | Strong single source; high fuzzy match (>0.85) on name + address |
| Possible | Circumstantial only; moderate match (0.55-0.84) |
| Unresolved | Contradictory evidence; insufficient data |
"""

PLAN_TEMPLATE = """\
# Investigation Plan: {title}

**Date**: {date}
**Objective**: {objective}

## Data Sources

| Dataset | Format | Expected Records | Linking Fields |
|---------|--------|-----------------|----------------|
| | CSV/JSON | ~N | name, address, ... |

## Entity Resolution Strategy

- Primary matching fields: [name, EIN, address]
- Blocking key: [first_3_chars + state]
- Similarity threshold: 0.85 (confirmed), 0.70 (probable)

## Cross-Dataset Linking Approach

- Link datasets via: [field matching, fuzzy name, shared address]
- Expected match rate: ~N%

## Evidence Chain Construction

- Confidence model: 4-tier (confirmed/probable/possible/unresolved)
- Minimum corroboration: 2 independent sources for confirmed

## Expected Deliverables

- [ ] Entity canonical map (entities/canonical.json)
- [ ] Cross-reference report (findings/cross-references.json)
- [ ] Investigation summary (findings/summary.md)
- [ ] Evidence appendix (evidence/chains.json)

## Risks and Limitations

- [Known data quality issues]
- [Missing datasets]
- [Entity resolution edge cases]
"""


def init_workspace(workspace: Path, plan_title: str | None = None) -> None:
    workspace = workspace.resolve()

    if workspace.exists() and any(workspace.iterdir()):
        # Check if already initialized
        if (workspace / "entities").exists():
            print(f"Workspace already initialized: {workspace}")
            return
        # Non-empty but not an investigation workspace — proceed carefully
        print(f"Warning: {workspace} is not empty. Creating investigation subdirectories.")

    workspace.mkdir(parents=True, exist_ok=True)

    for d in DIRS:
        (workspace / d).mkdir(exist_ok=True)
        # Add .gitkeep to empty dirs
        gitkeep = workspace / d / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.touch()

    # Write README
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    readme_path = workspace / "README.md"
    if not readme_path.exists():
        readme_path.write_text(README.format(timestamp=now), encoding="utf-8")

    # Initialize empty canonical entity map
    canonical_path = workspace / "entities" / "canonical.json"
    if not canonical_path.exists():
        canonical_path.write_text(
            json.dumps(
                {
                    "metadata": {
                        "created": now,
                        "workspace": str(workspace),
                        "datasets_processed": [],
                        "total_entities": 0,
                        "resolution_threshold": 0.85,
                    },
                    "entities": [],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    # Write plan template if requested
    if plan_title:
        plan_path = workspace / "plans" / "plan.md"
        if not plan_path.exists():
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            plan_path.write_text(
                PLAN_TEMPLATE.format(
                    title=plan_title, date=today, objective=plan_title
                ),
                encoding="utf-8",
            )
            print(f"  Plan template: {plan_path}")

    print(f"Workspace initialized: {workspace}")
    for d in DIRS:
        print(f"  {d}/")
    print(f"  README.md")
    print(f"  entities/canonical.json")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Initialize an OpenPlanter investigation workspace"
    )
    parser.add_argument("workspace", type=Path, help="Path to workspace directory")
    parser.add_argument(
        "--plan",
        type=str,
        default=None,
        help="Investigation title — creates a plan template in plans/plan.md",
    )
    args = parser.parse_args()
    init_workspace(args.workspace, args.plan)


if __name__ == "__main__":
    main()

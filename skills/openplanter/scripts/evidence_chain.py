#!/usr/bin/env python3
"""Validate evidence chain structure in investigation findings.

Checks each claim in findings/ for:
  - Evidence items with source records
  - Dataset references
  - Confidence tier assignment
  - Required fields (claim, evidence, source, confidence)
  - Evidence chain completeness (every hop documented)

Reports pass/fail per claim, missing fields, and broken chains.

Uses Python stdlib only — zero external dependencies.

Usage:
    python3 evidence_chain.py /path/to/investigation
    python3 evidence_chain.py /path/to/investigation --strict
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

VALID_CONFIDENCE = {"confirmed", "probable", "possible", "unresolved"}
VALID_MATCH_TYPES = {"exact", "fuzzy", "address-based", "ein", "phone", "email", "fuzzy_name", "exact_ein"}
VALID_CORROBORATION = {"single", "corroborated", "contradicted", "unresolvable"}

REQUIRED_CHAIN_FIELDS = {"claim", "confidence", "hops"}
REQUIRED_HOP_FIELDS = {"from_entity", "from_dataset", "to_entity", "to_dataset", "match_type"}


@dataclass
class ValidationResult:
    chain_id: str
    claim: str
    status: str = "pass"  # pass, warn, fail
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_issue(self, msg: str) -> None:
        self.issues.append(msg)
        self.status = "fail"

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)
        if self.status == "pass":
            self.status = "warn"


def validate_hop(hop: dict[str, Any], hop_num: int, strict: bool) -> list[str]:
    """Validate a single hop in an evidence chain."""
    issues: list[str] = []

    # Check required fields
    for f in REQUIRED_HOP_FIELDS:
        if f not in hop or not hop[f]:
            issues.append(f"Hop {hop_num}: missing required field '{f}'")

    # Check match type
    mt = hop.get("match_type", "")
    if mt and mt not in VALID_MATCH_TYPES:
        # Allow compound types like "exact_ein + fuzzy_name"
        parts = [p.strip() for p in mt.replace("+", ",").split(",")]
        for part in parts:
            if part and part not in VALID_MATCH_TYPES:
                issues.append(f"Hop {hop_num}: unknown match_type '{part}'")

    # Check match score if present
    score = hop.get("match_score")
    if score is not None:
        try:
            s = float(score)
            if not 0.0 <= s <= 1.0:
                issues.append(f"Hop {hop_num}: match_score {s} out of range [0, 1]")
        except (ValueError, TypeError):
            issues.append(f"Hop {hop_num}: match_score '{score}' is not numeric")

    # Check link strength
    if strict and "link_strength" not in hop:
        issues.append(f"Hop {hop_num}: missing link_strength (required in strict mode)")

    # Check source records
    if strict:
        if "from_record" not in hop:
            issues.append(f"Hop {hop_num}: missing from_record (required in strict mode)")
        if "to_record" not in hop:
            issues.append(f"Hop {hop_num}: missing to_record (required in strict mode)")

    return issues


def validate_chain(chain: dict[str, Any], strict: bool) -> ValidationResult:
    """Validate an evidence chain."""
    chain_id = chain.get("chain_id", "unknown")
    claim = chain.get("claim", "(no claim)")
    result = ValidationResult(chain_id=chain_id, claim=claim)

    # Check required top-level fields
    for f in REQUIRED_CHAIN_FIELDS:
        if f not in chain or not chain[f]:
            result.add_issue(f"Missing required field: '{f}'")

    # Validate confidence tier
    confidence = chain.get("confidence", "")
    if confidence and confidence not in VALID_CONFIDENCE:
        result.add_issue(f"Invalid confidence tier: '{confidence}'")

    # Validate hops
    hops = chain.get("hops", [])
    if not hops:
        result.add_issue("No evidence hops — claim has no supporting evidence chain")
    else:
        for i, hop in enumerate(hops, start=1):
            hop_issues = validate_hop(hop, i, strict)
            for issue in hop_issues:
                result.add_issue(issue)

        # Check chain continuity — each hop's to_entity should be the next hop's from_entity
        for i in range(len(hops) - 1):
            to_entity = hops[i].get("to_entity", "")
            from_entity = hops[i + 1].get("from_entity", "")
            if to_entity and from_entity and to_entity != from_entity:
                result.add_warning(
                    f"Chain break: hop {i+1} ends at '{to_entity}' "
                    f"but hop {i+2} starts at '{from_entity}'"
                )

    # Validate corroboration (if present)
    corr = chain.get("corroboration", {})
    if corr:
        status = corr.get("status", "")
        if status and status not in VALID_CORROBORATION:
            result.add_warning(f"Unknown corroboration status: '{status}'")
        if status == "corroborated":
            sources = corr.get("independent_sources", 0)
            if isinstance(sources, int) and sources < 2:
                result.add_warning(
                    f"Corroborated but independent_sources={sources} (need >=2)"
                )

    # Check key assumptions (warn if missing in strict mode)
    if strict:
        if "key_assumptions" not in chain or not chain["key_assumptions"]:
            result.add_warning("No key_assumptions documented")
        if "falsification_conditions" not in chain or not chain["falsification_conditions"]:
            result.add_warning("No falsification_conditions documented")

    return result


def validate_findings_file(filepath: Path, strict: bool) -> list[ValidationResult]:
    """Validate all evidence chains in a findings file."""
    results: list[ValidationResult] = []

    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        r = ValidationResult(chain_id="file", claim=filepath.name)
        r.add_issue(f"Cannot parse file: {e}")
        return [r]

    # Handle different file structures
    chains: list[dict[str, Any]] = []

    if isinstance(data, list):
        chains = [c for c in data if isinstance(c, dict)]
    elif isinstance(data, dict):
        # Check common wrapper patterns
        for key in ("chains", "evidence_chains", "findings", "cross_references"):
            if key in data and isinstance(data[key], list):
                chains = [c for c in data[key] if isinstance(c, dict)]
                break
        else:
            # Single chain
            chains = [data]

    if not chains:
        r = ValidationResult(chain_id="file", claim=filepath.name)
        r.add_warning("No evidence chains found in file")
        results.append(r)
        return results

    for chain in chains:
        results.append(validate_chain(chain, strict))

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate evidence chain structure in investigation findings"
    )
    parser.add_argument("workspace", type=Path, help="Path to investigation workspace")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Strict mode: require link_strength, source records, assumptions",
    )
    args = parser.parse_args()

    workspace = args.workspace.resolve()

    # Check both findings/ and evidence/ directories
    search_dirs = [workspace / "findings", workspace / "evidence"]
    json_files: list[Path] = []
    for d in search_dirs:
        if d.exists():
            json_files.extend(d.glob("*.json"))

    if not json_files:
        print("No JSON files found in findings/ or evidence/")
        sys.exit(0)

    total_pass = 0
    total_warn = 0
    total_fail = 0
    all_results: list[ValidationResult] = []

    print(f"Validating evidence chains (strict={'yes' if args.strict else 'no'}):\n")

    for fp in sorted(json_files):
        results = validate_findings_file(fp, args.strict)
        all_results.extend(results)
        print(f"  {fp.relative_to(workspace)}:")

        for r in results:
            icon = {"pass": "+", "warn": "~", "fail": "!"}[r.status]
            print(f"    [{icon}] {r.chain_id}: {r.claim[:60]}")
            for issue in r.issues:
                print(f"        FAIL: {issue}")
            for warning in r.warnings:
                print(f"        WARN: {warning}")

            if r.status == "pass":
                total_pass += 1
            elif r.status == "warn":
                total_warn += 1
            else:
                total_fail += 1

    # Write validation report
    report = {
        "metadata": {
            "workspace": str(workspace),
            "strict_mode": args.strict,
            "files_checked": len(json_files),
            "chains_validated": len(all_results),
        },
        "summary": {
            "pass": total_pass,
            "warn": total_warn,
            "fail": total_fail,
        },
        "results": [
            {
                "chain_id": r.chain_id,
                "claim": r.claim,
                "status": r.status,
                "issues": r.issues,
                "warnings": r.warnings,
            }
            for r in all_results
        ],
    }

    evidence_dir = workspace / "evidence"
    evidence_dir.mkdir(exist_ok=True)
    report_path = evidence_dir / "validation-report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"\n{'='*50}")
    print(f"  Pass: {total_pass}  Warn: {total_warn}  Fail: {total_fail}")
    print(f"  Report: {report_path}")

    if total_fail > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

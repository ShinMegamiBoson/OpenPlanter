#!/usr/bin/env python3
"""Master orchestrator: run a full investigation pipeline end-to-end.

Chains the OpenPlanter skill scripts in the correct order:
    collect → resolve → enrich → analyze → report

Each phase can be run independently or as part of the full pipeline.
Produces a structured findings summary in findings/summary.md.

Uses Python stdlib only — zero external dependencies.
Invokes sibling scripts as subprocesses.

Usage:
    python3 investigate.py /path/to/workspace --objective "Investigate X"
    python3 investigate.py /path/to/workspace --phases collect,resolve,analyze
    python3 investigate.py /path/to/workspace --phases all
    python3 investigate.py /path/to/workspace --phases report --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Script locations (sibling scripts in the same directory)
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).resolve().parent

PHASE_SCRIPTS = {
    "init": _SCRIPT_DIR / "init_workspace.py",
    "fetch": _SCRIPT_DIR / "dataset_fetcher.py",
    "scrape": _SCRIPT_DIR / "scrape_records.py",
    "resolve": _SCRIPT_DIR / "entity_resolver.py",
    "crossref": _SCRIPT_DIR / "cross_reference.py",
    "enrich": _SCRIPT_DIR / "web_enrich.py",
    "evidence": _SCRIPT_DIR / "evidence_chain.py",
    "score": _SCRIPT_DIR / "confidence_scorer.py",
}

# Phase groups map to pipeline stages
PHASE_GROUPS = {
    "collect": ["fetch", "scrape"],
    "resolve": ["resolve", "crossref"],
    "enrich": ["enrich"],
    "analyze": ["evidence", "score"],
    "report": [],  # handled separately
}

ALL_PHASES = ["collect", "resolve", "enrich", "analyze", "report"]


def run_script(script: Path, args: list[str], timeout: int = 300) -> dict:
    """Run a sibling script and capture its result."""
    cmd = [sys.executable, str(script), *args]
    name = script.stem

    print(f"  Running: {name}")
    t0 = time.monotonic()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ},
        )
        elapsed = round(time.monotonic() - t0, 2)

        if result.stdout:
            # Indent output
            for line in result.stdout.strip().split("\n"):
                print(f"    {line}")

        if result.returncode != 0 and result.stderr:
            for line in result.stderr.strip().split("\n")[:5]:
                print(f"    ERROR: {line}")

        return {
            "script": name,
            "status": "ok" if result.returncode == 0 else "error",
            "exit_code": result.returncode,
            "elapsed_sec": elapsed,
        }
    except subprocess.TimeoutExpired:
        return {
            "script": name,
            "status": "timeout",
            "elapsed_sec": round(time.monotonic() - t0, 2),
        }
    except FileNotFoundError:
        return {
            "script": name,
            "status": "error",
            "error": f"Script not found: {script}",
            "elapsed_sec": 0,
        }


def run_phase(
    phase: str,
    workspace: Path,
    timeout: int,
    extra_args: dict[str, list[str]] | None = None,
) -> list[dict]:
    """Run all scripts in a phase group."""
    print(f"\n{'='*60}")
    print(f"  Phase: {phase.upper()}")
    print(f"{'='*60}\n")

    results = []
    scripts = PHASE_GROUPS.get(phase, [])

    for script_key in scripts:
        script = PHASE_SCRIPTS.get(script_key)
        if not script or not script.exists():
            print(f"  Skipping {script_key}: script not found")
            results.append({
                "script": script_key,
                "status": "skipped",
                "reason": "not found",
            })
            continue

        args = [str(workspace)]
        # Add any extra args for this script
        if extra_args and script_key in extra_args:
            args.extend(extra_args[script_key])

        result = run_script(script, args, timeout=timeout)
        results.append(result)
        print()

    return results


def generate_report(workspace: Path) -> str:
    """Generate a findings summary from all investigation outputs."""
    lines = [
        f"# Investigation Summary",
        f"",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"**Workspace:** `{workspace}`",
        f"",
    ]

    # Entity resolution summary
    canon_path = workspace / "entities" / "canonical.json"
    if canon_path.exists():
        try:
            data = json.loads(canon_path.read_text(encoding="utf-8"))
            entities = data.get("entities", data) if isinstance(data, dict) else data
            lines.append(f"## Entity Resolution")
            lines.append(f"")
            lines.append(f"- **Canonical entities:** {len(entities)}")
            # Count by confidence
            conf_counts: dict[str, int] = {}
            for e in entities:
                c = e.get("confidence", "unresolved")
                conf_counts[c] = conf_counts.get(c, 0) + 1
            for tier, count in sorted(conf_counts.items()):
                lines.append(f"  - {tier}: {count}")
            lines.append(f"")
        except (json.JSONDecodeError, OSError):
            pass

    # Cross-reference summary
    xref_path = workspace / "findings" / "cross-references.json"
    if xref_path.exists():
        try:
            data = json.loads(xref_path.read_text(encoding="utf-8"))
            xrefs = data.get("cross_references", data) if isinstance(data, dict) else data
            if isinstance(xrefs, list):
                lines.append(f"## Cross-References")
                lines.append(f"")
                lines.append(f"- **Cross-referenced entities:** {len(xrefs)}")
                multi_source = sum(
                    1 for x in xrefs
                    if len(x.get("sources", x.get("datasets", []))) >= 2
                )
                lines.append(f"- **Multi-source matches:** {multi_source}")
                lines.append(f"")
        except (json.JSONDecodeError, OSError):
            pass

    # Evidence chains summary
    chains_path = workspace / "evidence" / "chains.json"
    if chains_path.exists():
        try:
            data = json.loads(chains_path.read_text(encoding="utf-8"))
            chains = data.get("chains", data) if isinstance(data, dict) else data
            if isinstance(chains, list):
                lines.append(f"## Evidence Chains")
                lines.append(f"")
                lines.append(f"- **Chains validated:** {len(chains)}")
                lines.append(f"")
        except (json.JSONDecodeError, OSError):
            pass

    # Confidence scoring summary
    scoring_path = workspace / "evidence" / "scoring-log.json"
    if scoring_path.exists():
        try:
            data = json.loads(scoring_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                lines.append(f"## Confidence Scoring")
                lines.append(f"")
                for key, val in data.items():
                    if key != "timestamp":
                        lines.append(f"- **{key}:** {val}")
                lines.append(f"")
        except (json.JSONDecodeError, OSError):
            pass

    # Enrichment summary
    enriched_path = workspace / "entities" / "enriched.json"
    if enriched_path.exists():
        try:
            data = json.loads(enriched_path.read_text(encoding="utf-8"))
            meta = data.get("enrichment_metadata", {})
            enriched = data.get("entities", [])
            lines.append(f"## Web Enrichment")
            lines.append(f"")
            lines.append(f"- **Entities enriched:** {meta.get('entities_enriched', len(enriched))}")
            lines.append(f"- **Categories:** {', '.join(meta.get('categories', []))}")
            total_results = sum(len(e.get("search_results", [])) for e in enriched)
            lines.append(f"- **Total search results:** {total_results}")
            lines.append(f"")
        except (json.JSONDecodeError, OSError):
            pass

    # Scraped records summary
    scraped_prov = workspace / "datasets" / "scraped" / "provenance.json"
    if scraped_prov.exists():
        try:
            data = json.loads(scraped_prov.read_text(encoding="utf-8"))
            results = data.get("results", [])
            lines.append(f"## Public Records")
            lines.append(f"")
            lines.append(f"- **API queries:** {len(results)}")
            ok = sum(1 for r in results if r.get("status") == "ok")
            lines.append(f"- **Matches found:** {ok}")
            lines.append(f"")
        except (json.JSONDecodeError, OSError):
            pass

    # Dataset inventory
    ds_dir = workspace / "datasets"
    if ds_dir.exists():
        files = [f for f in ds_dir.rglob("*") if f.is_file() and f.name != ".gitkeep"]
        if files:
            lines.append(f"## Dataset Inventory")
            lines.append(f"")
            lines.append(f"- **Total files:** {len(files)}")
            total_size = sum(f.stat().st_size for f in files)
            if total_size > 1_000_000:
                lines.append(f"- **Total size:** {total_size / 1_000_000:.1f} MB")
            else:
                lines.append(f"- **Total size:** {total_size / 1_000:.1f} KB")
            lines.append(f"")

    # Methodology
    lines.extend([
        f"## Methodology",
        f"",
        f"This investigation used the OpenPlanter skill pipeline:",
        f"1. Entity resolution via fuzzy matching (difflib.SequenceMatcher)",
        f"2. Cross-referencing across datasets using canonical entity map",
        f"3. Evidence chain validation with hop tracking",
        f"4. Confidence scoring using Admiralty System tiers (NATO AJP-2.1)",
        f"",
        f"See `entities/canonical.json` for the full entity map and "
        f"`findings/cross-references.json` for detailed cross-references.",
    ])

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run OpenPlanter investigation pipeline"
    )
    parser.add_argument(
        "workspace", type=Path,
        help="Path to investigation workspace",
    )
    parser.add_argument(
        "--objective", type=str,
        help="Investigation objective (included in report)",
    )
    parser.add_argument(
        "--phases", type=str, default="all",
        help=f"Comma-separated phases or 'all' (default: all). "
             f"Available: {', '.join(ALL_PHASES)}",
    )
    parser.add_argument(
        "--threshold", type=float, default=0.85,
        help="Entity resolution similarity threshold (default: 0.85)",
    )
    parser.add_argument(
        "--fetch-sources", type=str, default="sec",
        help="Dataset sources for collect phase (default: sec). "
             "Options: sec, fec, ofac, sanctions, lda, or 'all'",
    )
    parser.add_argument(
        "--timeout", type=int, default=300,
        help="Timeout per script in seconds (default: 300)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would run without executing",
    )
    args = parser.parse_args()

    workspace = args.workspace.resolve()

    # Auto-init workspace if it doesn't exist
    if not workspace.exists():
        print(f"Initializing workspace: {workspace}")
        init_script = PHASE_SCRIPTS["init"]
        if init_script.exists():
            run_script(init_script, [str(workspace)], timeout=30)
        else:
            workspace.mkdir(parents=True)
            for d in ["datasets", "entities", "findings", "evidence", "plans"]:
                (workspace / d).mkdir(exist_ok=True)

    # Resolve phases
    if args.phases == "all":
        phases = ALL_PHASES
    else:
        phases = [p.strip() for p in args.phases.split(",")]
        unknown = [p for p in phases if p not in ALL_PHASES]
        if unknown:
            print(f"Error: unknown phase(s): {', '.join(unknown)}\n"
                  f"Available: {', '.join(ALL_PHASES)}", file=sys.stderr)
            sys.exit(1)

    # Extra args per script
    extra_args: dict[str, list[str]] = {
        "fetch": ["--sources", args.fetch_sources],
        "resolve": ["--threshold", str(args.threshold)],
    }

    print(f"OpenPlanter Investigation Pipeline")
    print(f"Workspace: {workspace}")
    if args.objective:
        print(f"Objective: {args.objective}")
    print(f"Phases: {', '.join(phases)}")
    print()

    if args.dry_run:
        for phase in phases:
            scripts = PHASE_GROUPS.get(phase, [])
            for sk in scripts:
                script = PHASE_SCRIPTS.get(sk)
                print(f"  [dry-run] Phase {phase}: would run {sk} ({script})")
            if phase == "report":
                print(f"  [dry-run] Phase report: would generate findings/summary.md")
        return

    t_start = time.monotonic()
    all_results: list[dict] = []

    for phase in phases:
        if phase == "report":
            # Generate report
            print(f"\n{'='*60}")
            print(f"  Phase: REPORT")
            print(f"{'='*60}\n")

            report = generate_report(workspace)
            if args.objective:
                report = report.replace(
                    "# Investigation Summary",
                    f"# Investigation Summary\n\n**Objective:** {args.objective}",
                )

            report_path = workspace / "findings" / "summary.md"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(report, encoding="utf-8")
            print(f"  Wrote: {report_path}")
            all_results.append({"script": "report", "status": "ok"})
        else:
            results = run_phase(phase, workspace, args.timeout, extra_args)
            all_results.extend(results)

    elapsed = round(time.monotonic() - t_start, 2)

    print(f"\n{'='*60}")
    print(f"  Pipeline Complete ({elapsed}s)")
    print(f"{'='*60}\n")

    ok = sum(1 for r in all_results if r.get("status") == "ok")
    errs = sum(1 for r in all_results if r.get("status") == "error")
    skipped = sum(1 for r in all_results if r.get("status") == "skipped")
    print(f"  {ok} succeeded, {errs} errors, {skipped} skipped")

    if errs:
        print("\nErrors:")
        for r in all_results:
            if r.get("status") == "error":
                print(f"  - {r['script']}: {r.get('error', 'non-zero exit')}")
        sys.exit(1)


if __name__ == "__main__":
    main()

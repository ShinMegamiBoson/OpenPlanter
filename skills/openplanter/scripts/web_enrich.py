#!/usr/bin/env python3
"""Enrich resolved entities with web search results via Exa.

Reads entities/canonical.json, searches for each entity using the Exa neural
search API (via the exa-search skill subprocess), and writes enriched records
to entities/enriched.json. Provider-agnostic — works with any Exa-compatible
search backend.

Uses Python stdlib only — zero external dependencies.
Exa search is invoked as a subprocess (exa_search.py from exa-search skill).

Usage:
    python3 web_enrich.py /path/to/investigation
    python3 web_enrich.py /path/to/investigation --entities "Acme Corp" "Beta LLC"
    python3 web_enrich.py /path/to/investigation --categories company,news --limit 5
    python3 web_enrich.py /path/to/investigation --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Exa search skill locations
# ---------------------------------------------------------------------------

_EXA_SEARCH_CANDIDATES = [
    Path.home() / ".claude" / "skills" / "exa-search" / "scripts" / "exa_search.py",
    Path.home() / "Desktop" / "Programming" / "claude-code-minoan" / "skills"
    / "web-search" / "exa-search" / "scripts" / "exa_search.py",
]

_EXA_CONTENTS_CANDIDATES = [
    Path.home() / ".claude" / "skills" / "exa-search" / "scripts" / "exa_contents.py",
]


def _find_script(candidates: list[Path], name: str) -> Path | None:
    """Find the first existing script from candidate paths."""
    for p in candidates:
        if p.exists():
            return p
    # Check PATH
    if shutil.which(name):
        return Path(shutil.which(name))  # type: ignore[arg-type]
    return None


def _run_exa_search(
    query: str,
    category: str = "company",
    num_results: int = 5,
    extra_args: list[str] | None = None,
) -> list[dict]:
    """Run exa_search.py as a subprocess and return parsed results."""
    script = _find_script(_EXA_SEARCH_CANDIDATES, "exa_search.py")
    if not script:
        return []

    cmd = [
        sys.executable, str(script),
        query,
        "--category", category,
        "-n", str(num_results),
        "--json",
    ]
    if extra_args:
        cmd.extend(extra_args)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ},
        )
        if result.returncode != 0:
            return []
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return []


def _run_exa_contents(
    urls: list[str],
    max_chars: int = 3000,
    summary: bool = True,
) -> list[dict]:
    """Run exa_contents.py to get page content for given URLs."""
    script = _find_script(_EXA_CONTENTS_CANDIDATES, "exa_contents.py")
    if not script:
        return []

    cmd = [
        sys.executable, str(script),
        *urls,
        "--max-chars", str(max_chars),
    ]
    if summary:
        cmd.append("--summary")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ},
        )
        if result.returncode != 0:
            return []
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return []


def load_canonical(workspace: Path) -> list[dict]:
    """Load canonical entities from entities/canonical.json."""
    canon_path = workspace / "entities" / "canonical.json"
    if not canon_path.exists():
        print(f"Error: {canon_path} not found. Run entity_resolver.py first.",
              file=sys.stderr)
        return []
    try:
        data = json.loads(canon_path.read_text(encoding="utf-8"))
        return data.get("entities", data) if isinstance(data, dict) else data
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error reading {canon_path}: {e}", file=sys.stderr)
        sys.exit(1)


def enrich_entity(
    entity: dict,
    categories: list[str],
    limit: int,
    delay: float,
) -> dict:
    """Search for an entity across categories and return enrichment data."""
    name = entity.get("canonical_name", "")
    if not name:
        return {}

    enrichment: dict = {
        "canonical_id": entity.get("canonical_id", ""),
        "canonical_name": name,
        "search_results": [],
        "summaries": [],
        "enrichment_timestamp": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
    }

    all_urls: list[str] = []

    for category in categories:
        print(f"    Searching [{category}]: {name}")
        results = _run_exa_search(name, category=category, num_results=limit)

        for r in results:
            entry = {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "category": category,
                "score": r.get("score", 0),
                "published_date": r.get("publishedDate", ""),
            }
            enrichment["search_results"].append(entry)
            if r.get("url"):
                all_urls.append(r["url"])

        if delay > 0:
            time.sleep(delay)

    # Get summaries for top URLs (limit to 3 to conserve API calls)
    top_urls = all_urls[:3]
    if top_urls:
        print(f"    Fetching summaries for {len(top_urls)} URL(s)")
        contents = _run_exa_contents(top_urls, max_chars=3000, summary=True)
        for c in contents:
            enrichment["summaries"].append({
                "url": c.get("url", ""),
                "title": c.get("title", ""),
                "summary": c.get("summary", c.get("text", ""))[:2000],
            })

    return enrichment


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich resolved entities with Exa web search results"
    )
    parser.add_argument(
        "workspace", type=Path,
        help="Path to investigation workspace",
    )
    parser.add_argument(
        "--entities", nargs="+",
        help="Specific entity names to enrich (default: all canonical entities)",
    )
    parser.add_argument(
        "--categories", type=str, default="company,news",
        help="Comma-separated Exa search categories (default: company,news). "
             "Options: company, research paper, news, pdf, github, tweet, "
             "personal site, people, financial report",
    )
    parser.add_argument(
        "--limit", type=int, default=5,
        help="Max results per category per entity (default: 5)",
    )
    parser.add_argument(
        "--delay", type=float, default=0.5,
        help="Delay between API calls in seconds (default: 0.5)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be searched without making API calls",
    )
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    if not workspace.exists():
        print(f"Error: workspace does not exist: {workspace}", file=sys.stderr)
        sys.exit(1)

    # Check Exa availability
    exa_script = _find_script(_EXA_SEARCH_CANDIDATES, "exa_search.py")
    if not exa_script and not args.dry_run:
        print(
            "Error: exa_search.py not found. Install the exa-search skill:\n"
            "  cp -r exa-search ~/.claude/skills/exa-search\n"
            "  export EXA_API_KEY=your-key",
            file=sys.stderr,
        )
        sys.exit(1)

    if not os.environ.get("EXA_API_KEY") and not args.dry_run:
        print(
            "Warning: EXA_API_KEY not set. Search may fail.",
            file=sys.stderr,
        )

    categories = [c.strip() for c in args.categories.split(",")]
    entities = load_canonical(workspace)
    if not entities:
        print("No canonical entities found. Run entity_resolver.py first.")
        sys.exit(1)

    # Filter to specific entities if requested
    if args.entities:
        target_names = {n.lower() for n in args.entities}
        entities = [
            e for e in entities
            if e.get("canonical_name", "").lower() in target_names
        ]
        if not entities:
            print(f"No matching entities found for: {args.entities}")
            sys.exit(1)

    print(f"Enriching {len(entities)} entity/entities across "
          f"{len(categories)} category/categories\n")

    if args.dry_run:
        for e in entities:
            name = e.get("canonical_name", "unknown")
            for cat in categories:
                print(f"  [dry-run] Would search [{cat}]: {name}")
        print(f"\n  [dry-run] Would write: entities/enriched.json")
        return

    enriched = []
    for i, entity in enumerate(entities, 1):
        name = entity.get("canonical_name", "unknown")
        print(f"  [{i}/{len(entities)}] {name}")
        result = enrich_entity(entity, categories, args.limit, args.delay)
        if result:
            enriched.append(result)
        print()

    # Write output
    output_path = workspace / "entities" / "enriched.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output = {
        "enrichment_metadata": {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "categories": categories,
            "limit_per_category": args.limit,
            "entities_searched": len(entities),
            "entities_enriched": len(enriched),
            "exa_script": str(exa_script) if exa_script else None,
        },
        "entities": enriched,
    }
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"Wrote {len(enriched)} enriched entities to {output_path}")

    total_results = sum(len(e.get("search_results", [])) for e in enriched)
    total_summaries = sum(len(e.get("summaries", [])) for e in enriched)
    print(f"Total: {total_results} search results, {total_summaries} summaries")


if __name__ == "__main__":
    main()

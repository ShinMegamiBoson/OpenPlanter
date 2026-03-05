#!/usr/bin/env python3
"""Generate post-edit understanding quiz for changed files.

Surfaces implicit design decisions, ADR constraints, and tradeoffs
so the user can confirm alignment with the implementation.

This is NOT a test — it's an alignment check. "Wrong" answers mean
either the user misunderstands or the implementation is wrong.

Usage:
    # Quiz for a single file
    python scripts/generate_quiz.py src/world/contracts.py

    # Quiz for all files changed on current branch vs main
    python scripts/generate_quiz.py --diff

    # Quiz for staged changes
    python scripts/generate_quiz.py --staged

    # Output as JSON (for hook integration)
    python scripts/generate_quiz.py src/world/contracts.py --json
"""

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path

import yaml


def load_relationships(repo_root: Path) -> dict:  # type: ignore[type-arg]
    """Load relationships.yaml."""
    rel_path = repo_root / "scripts" / "relationships.yaml"
    if not rel_path.exists():
        return {}
    with open(rel_path) as f:
        return yaml.safe_load(f) or {}


def get_governance(
    file_path: str, relationships: dict  # type: ignore[type-arg]
) -> dict | None:  # type: ignore[type-arg]
    """Get governance info for a file."""
    adrs_info = relationships.get("adrs", {})
    for gov in relationships.get("governance", []):
        if gov.get("source") == file_path:
            adr_details = []
            for adr_num in gov.get("adrs", []):
                info = adrs_info.get(adr_num, {})
                adr_details.append({
                    "number": adr_num,
                    "title": info.get("title", "Unknown"),
                })
            return {
                "adrs": adr_details,
                "context": gov.get("context", "").strip(),
            }
    return None


def get_coupled_docs(
    file_path: str, relationships: dict  # type: ignore[type-arg]
) -> list[dict]:  # type: ignore[type-arg]
    """Get coupled docs for a file."""
    docs = []
    for coupling in relationships.get("couplings", []):
        for source in coupling.get("sources", []):
            if _matches(file_path, source):
                for doc in coupling.get("docs", []):
                    docs.append({
                        "path": doc,
                        "description": coupling.get("description", ""),
                    })
    return docs


def _matches(file_path: str, pattern: str) -> bool:
    """Check if file matches a source pattern."""
    if "**" in pattern:
        return file_path.startswith(pattern.split("**")[0])
    if "*" in pattern:
        return file_path.startswith(pattern.split("*")[0])
    return file_path == pattern


def get_forbidden_terms(relationships: dict) -> dict[str, str]:  # type: ignore[type-arg]
    """Get forbidden terms and their replacements."""
    result = {}
    glossary = relationships.get("glossary", {})
    if isinstance(glossary, dict):
        for term, info in glossary.items():
            if isinstance(info, dict) and info.get("deprecated"):
                result[term] = info.get("replacement", "unknown")
    return result


def analyze_python_file(file_path: Path) -> dict:  # type: ignore[type-arg]
    """Extract structural info from a Python file using AST."""
    result: dict = {  # type: ignore[type-arg]
        "classes": [],
        "functions": [],
        "imports_from_world": [],
        "has_protocol": False,
        "has_dataclass": False,
        "has_pydantic": False,
        "error_handling": [],
        "line_count": 0,
    }

    if not file_path.exists():
        return result

    content = file_path.read_text()
    result["line_count"] = len(content.splitlines())

    try:
        tree = ast.parse(content)
    except SyntaxError:
        return result

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bases = []
            for base in node.bases:
                if isinstance(base, ast.Name):
                    bases.append(base.id)
                elif isinstance(base, ast.Attribute):
                    bases.append(base.attr)
            result["classes"].append({
                "name": node.name,
                "bases": bases,
                "methods": [
                    n.name for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                ],
            })
            if "Protocol" in bases:
                result["has_protocol"] = True
            if any(b in ("BaseModel", "StrictModel") for b in bases):
                result["has_pydantic"] = True

        elif isinstance(node, ast.FunctionDef) and node.col_offset == 0:
            result["functions"].append(node.name)

        elif isinstance(node, ast.ImportFrom):
            if node.module and "src.world" in node.module:
                result["imports_from_world"].append(node.module)

        # Check for decorators
        if isinstance(node, ast.ClassDef):
            for dec in node.decorator_list:
                if isinstance(dec, ast.Name) and dec.id == "dataclass":
                    result["has_dataclass"] = True

    return result


def generate_quiz(
    file_path: str,
    repo_root: Path,
    relationships: dict,  # type: ignore[type-arg]
) -> dict:  # type: ignore[type-arg]
    """Generate quiz questions for a file.

    Returns:
        {
            "file": "src/world/contracts.py",
            "questions": [
                {
                    "category": "constraint",
                    "question": "...",
                    "options": ["A) ...", "B) ...", "C) ...", "D) ..."],
                    "context": "ADR-0003"
                },
                ...
            ]
        }
    """
    questions: list[dict] = []  # type: ignore[type-arg]
    governance = get_governance(file_path, relationships)
    coupled_docs = get_coupled_docs(file_path, relationships)
    forbidden = get_forbidden_terms(relationships)
    file_info = analyze_python_file(repo_root / file_path)

    # === Constraint questions from governance ===
    if governance:
        for ctx_line in governance["context"].splitlines():
            ctx_line = ctx_line.strip()
            if not ctx_line:
                continue
            # Extract ADR reference if present
            adr_ref = ""
            if "ADR-" in ctx_line:
                import re
                match = re.search(r"ADR-(\d+)", ctx_line)
                if match:
                    adr_ref = f"ADR-{match.group(1)}"

            questions.append({
                "category": "constraint",
                "question": f"This file has the constraint: \"{ctx_line}\"\n"
                            f"Does your change respect this? If not, what's the justification?",
                "type": "confirm_or_justify",
                "context": adr_ref,
            })

    # === Structural questions ===
    if file_info["has_protocol"]:
        protocol_classes = [
            c["name"] for c in file_info["classes"]
            if "Protocol" in c.get("bases", [])
        ]
        if protocol_classes:
            questions.append({
                "category": "structure",
                "question": f"This file defines Protocol(s): {', '.join(protocol_classes)}. "
                            f"Did your change modify the protocol interface? "
                            f"If so, what downstream implementations need updating?",
                "type": "confirm_or_justify",
                "context": "Protocol changes break implementors",
            })

    if file_info["has_pydantic"]:
        questions.append({
            "category": "structure",
            "question": "This file uses Pydantic models. Did your change add/remove/rename fields? "
                        "If so, what serialization/deserialization paths are affected?",
            "type": "confirm_or_justify",
            "context": "Pydantic field changes can break checkpoints and APIs",
        })

    # === Coupling questions ===
    if coupled_docs:
        strict_docs = [d for d in coupled_docs if not d.get("soft")]
        if strict_docs:
            doc_list = ", ".join(d["path"].split("/")[-1] for d in strict_docs)
            questions.append({
                "category": "coupling",
                "question": f"This file is strictly coupled to: {doc_list}. "
                            f"Does your change require updating these docs? "
                            f"(CI will catch this, but think about it now.)",
                "type": "confirm_or_justify",
                "context": "Doc-coupling is CI-enforced",
            })

    # === Forbidden term check ===
    if forbidden:
        questions.append({
            "category": "terminology",
            "question": "Does your change introduce any of these forbidden terms?\n"
                        + "\n".join(
                            f"  - '{term}' → use '{repl}' instead"
                            for term, repl in sorted(forbidden.items())
                        ),
            "type": "confirm",
            "context": "Terminology violations cause confusion",
        })

    # === Risk question (always) ===
    questions.append({
        "category": "risk",
        "question": "What could go wrong with this change? Consider:\n"
                    "  - Performance impact (is this on a hot path?)\n"
                    "  - Backwards compatibility (does this break existing data?)\n"
                    "  - Error handling (what happens when this fails?)\n"
                    "  - Observability (will problems be visible in logs/dashboard?)",
        "type": "free_response",
        "context": "Explicit risk assessment",
    })

    return {
        "file": file_path,
        "governance": governance,
        "coupled_docs": [d["path"] for d in coupled_docs],
        "file_info": {
            "classes": len(file_info["classes"]),
            "functions": len(file_info["functions"]),
            "lines": file_info["line_count"],
        },
        "questions": questions,
    }


def format_quiz_markdown(quiz: dict) -> str:  # type: ignore[type-arg]
    """Format quiz as readable markdown."""
    lines = []
    lines.append(f"## Understanding Quiz: {quiz['file']}")
    lines.append("")

    info = quiz["file_info"]
    lines.append(f"*{info['lines']} lines, {info['classes']} classes, "
                 f"{info['functions']} top-level functions*")
    lines.append("")

    if quiz["governance"]:
        adr_list = ", ".join(
            f"ADR-{a['number']:04d} ({a['title']})"
            for a in quiz["governance"]["adrs"]
        )
        lines.append(f"**Governing ADRs:** {adr_list}")
        lines.append("")

    for i, q in enumerate(quiz["questions"], 1):
        cat = q["category"].upper()
        lines.append(f"### Q{i} [{cat}]")
        lines.append("")
        lines.append(q["question"])
        lines.append("")

        if q["type"] == "confirm_or_justify":
            lines.append("- [ ] Yes, my change respects this")
            lines.append("- [ ] No — justification: ___________")
            lines.append("")
        elif q["type"] == "confirm":
            lines.append("- [ ] Confirmed — no violations")
            lines.append("- [ ] Found issue: ___________")
            lines.append("")
        elif q["type"] == "free_response":
            lines.append("*Response:* ___________")
            lines.append("")

    lines.append("---")
    lines.append("*This quiz surfaces implicit decisions. "
                 "\"Wrong\" answers = misalignment to discuss, not failures.*")

    return "\n".join(lines)


def get_changed_files(repo_root: Path, staged: bool = False) -> list[str]:
    """Get list of changed Python files."""
    if staged:
        cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"]
    else:
        cmd = ["git", "diff", "--name-only", "--diff-filter=ACMR", "origin/main...HEAD"]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True, cwd=repo_root
        )
        return [
            f for f in result.stdout.strip().splitlines()
            if f.endswith(".py") and f.startswith("src/")
        ]
    except subprocess.CalledProcessError:
        return []


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate post-edit understanding quiz"
    )
    parser.add_argument(
        "files", nargs="*", help="Files to quiz (relative to repo root)"
    )
    parser.add_argument(
        "--diff", action="store_true",
        help="Quiz all src/ files changed vs origin/main"
    )
    parser.add_argument(
        "--staged", action="store_true",
        help="Quiz all staged src/ files"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output as JSON"
    )
    args = parser.parse_args()

    repo_root = Path.cwd()
    relationships = load_relationships(repo_root)
    if not relationships:
        print("No relationships.yaml found", file=sys.stderr)
        sys.exit(2)

    # Determine files to quiz
    files: list[str] = []
    if args.diff:
        files = get_changed_files(repo_root, staged=False)
    elif args.staged:
        files = get_changed_files(repo_root, staged=True)
    elif args.files:
        files = args.files
    else:
        parser.print_help()
        sys.exit(1)

    if not files:
        print("No files to quiz.", file=sys.stderr)
        sys.exit(0)

    quizzes = []
    for f in files:
        quiz = generate_quiz(f, repo_root, relationships)
        if quiz["questions"]:
            quizzes.append(quiz)

    if args.json:
        print(json.dumps(quizzes, indent=2))
    else:
        for quiz in quizzes:
            print(format_quiz_markdown(quiz))
            print()

    # Exit with number of files quizzed (for scripting)
    sys.exit(0)


if __name__ == "__main__":
    main()

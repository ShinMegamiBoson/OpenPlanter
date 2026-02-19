"""Demo mode: censor entity names and workspace path segments in TUI output.

Censoring is UI-only -- the agent's internal state is unaffected.  Block
characters (``\u2588``) replace sensitive text at the same length so Rich
``Text`` style spans are preserved.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Sequence

# ---------------------------------------------------------------------------
# Entity detection regexes
# ---------------------------------------------------------------------------

# 2+ consecutive capitalised words: "John Smith", "Boston Medical Center"
# Use [ \t]+ (not \s+) to avoid matching across newlines.
_RE_MULTI_CAP = re.compile(r"\b([A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+)+)\b")

# Title + capitalised name: "Dr. Smith", "Mayor Walsh", "Sen. Warren"
_RE_TITLED = re.compile(
    r"\b((?:Dr|Mr|Mrs|Ms|Prof|Rev|Sen|Rep|Gov|Mayor|Judge|Chief|Officer|Det|Sgt|Lt|Cpt|Cmdr|Supt)"
    r"\.?[ \t]+[A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+)*)\b"
)

# Terms that look like entities but are actually tech/UI labels.
_ENTITY_WHITELIST: frozenset[str] = frozenset({
    # Months / days
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    # Common tech terms
    "Python", "Java", "JavaScript", "TypeScript", "Visual Studio",
    "Open Source", "Machine Learning", "Deep Learning",
    "Natural Language", "Large Language", "Artificial Intelligence",
    "Stack Overflow", "Pull Request", "Code Review",
    "Unit Test", "Test Case", "Test Suite",
    # TUI / OpenPlanter labels
    "Step", "Provider", "Model", "Reasoning", "Workspace", "Session",
    "Token", "Tokens", "Type", "Commands",
    "Open Planter", "Rich Text",
})

# Generic path components that should NOT be censored.
_GENERIC_PATH_PARTS: frozenset[str] = frozenset({
    "/", "Users", "home", "Documents", "Desktop", "Downloads",
    "Projects", "repos", "src", "var", "tmp", "opt", "etc",
    "Library", "Applications", "volumes", "mnt", "media",
    "nix", "store", "run", "snap",
})


# ---------------------------------------------------------------------------
# DemoCensor
# ---------------------------------------------------------------------------

class DemoCensor:
    """Builds replacement tables from a workspace path and censors text."""

    def __init__(self, workspace: Path) -> None:
        self._replacements: list[tuple[str, str]] = []
        self._build_path_replacements(workspace)

    # -- construction helpers ------------------------------------------------

    def _build_path_replacements(self, workspace: Path) -> None:
        """Decompose *workspace* into parts; add non-generic, non-project
        segments to the literal replacement table."""
        project_name = workspace.name
        for part in workspace.parts:
            if part in _GENERIC_PATH_PARTS:
                continue
            if part == project_name:
                continue
            if not part:  # empty string guard
                continue
            replacement = "\u2588" * len(part)
            self._replacements.append((part, replacement))

        # Sort longest-first so longer matches take precedence.
        self._replacements.sort(key=lambda t: len(t[0]), reverse=True)

    # -- public API ----------------------------------------------------------

    def censor_text(self, text: str) -> str:
        """Apply workspace-path replacements and entity-name censoring."""
        # 1. Literal path-segment replacements
        for original, replacement in self._replacements:
            text = text.replace(original, replacement)

        # 2. Titled names (Dr. Smith) — run before multi-cap so titles win
        text = _RE_TITLED.sub(self._replace_entity, text)

        # 3. Multi-word capitalised names
        text = _RE_MULTI_CAP.sub(self._replace_entity, text)

        return text

    def censor_rich_text(self, rich_text: Any) -> Any:
        """Censor a ``rich.text.Text`` object in-place (same length preserves
        style spans) and return it."""
        original = rich_text.plain
        censored = self.censor_text(original)
        if censored != original:
            # Assign through the documented .plain setter which preserves spans
            # when the new string is the same length.
            rich_text.plain = censored
        return rich_text

    # -- internal ------------------------------------------------------------

    @staticmethod
    def _replace_entity(m: re.Match[str]) -> str:
        matched = m.group(0)
        # Exact whitelist hit
        if matched in _ENTITY_WHITELIST:
            return matched
        # If a whitelisted term appears as a sub-phrase, pass through
        for term in _ENTITY_WHITELIST:
            if term in matched:
                return matched
        return "\u2588" * len(matched)


# ---------------------------------------------------------------------------
# DemoRenderHook — intercept all Rich renderables before display
# ---------------------------------------------------------------------------

class DemoRenderHook:
    """A ``rich.console.RenderHook`` that censors renderables before display."""

    def __init__(self, censor: DemoCensor) -> None:
        self._censor = censor

    # -- RenderHook protocol -------------------------------------------------

    def process_renderables(
        self, renderables: Sequence[Any],
    ) -> list[Any]:
        return [self._process_one(r) for r in renderables]

    # -- per-renderable dispatch ---------------------------------------------

    def _process_one(self, renderable: Any) -> Any:
        # Lazy imports so the module loads even without Rich installed.
        from rich.text import Text
        from rich.markdown import Markdown
        from rich.rule import Rule

        if isinstance(renderable, Text):
            return self._censor.censor_rich_text(renderable)

        if isinstance(renderable, Markdown):
            new_markup = self._censor.censor_text(renderable.markup)
            return Markdown(new_markup)

        if isinstance(renderable, Rule):
            if renderable.title:
                renderable.title = self._censor.censor_text(renderable.title)
            return renderable

        return renderable

"""Demo mode: censor workspace path segments in TUI output.

Censoring is UI-only -- the agent's internal state is unaffected.  Block
characters (``\u2588``) replace sensitive text at the same length so Rich
``Text`` style spans are preserved.

Entity-name censoring is handled by a prompt instruction (see prompts.py)
rather than regex post-processing.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

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
        """Apply workspace-path segment replacements."""
        for original, replacement in self._replacements:
            text = text.replace(original, replacement)
        return text

    def censor_rich_text(self, rich_text: Any) -> Any:
        """Censor a ``rich.text.Text`` object in-place (same length preserves
        style spans) and return it."""
        original = rich_text.plain
        censored = self.censor_text(original)
        if censored != original:
            rich_text.plain = censored
        return rich_text


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
        from rich.markdown import Markdown
        from rich.rule import Rule
        from rich.text import Text

        if isinstance(renderable, Text):
            return self._censor.censor_rich_text(renderable)

        if isinstance(renderable, Markdown):
            new_markup = self._censor.censor_text(renderable.markup)
            return Markdown(new_markup)

        if isinstance(renderable, Rule):
            if renderable.title:
                renderable.title = self._censor.censor_text(str(renderable.title))
            return renderable

        return renderable

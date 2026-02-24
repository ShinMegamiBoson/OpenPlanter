"""External tool plugin loading utilities."""

from __future__ import annotations

import importlib
import os
from collections.abc import Iterable

from .tool_registry import ToolPlugin


def parse_tool_module_list(value: str | None) -> tuple[str, ...]:
    """Parse a comma-separated module list from env/config."""
    if not value:
        return ()
    seen: set[str] = set()
    modules: list[str] = []
    for raw in value.split(","):
        name = raw.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        modules.append(name)
    return tuple(modules)


def configured_tool_modules_from_env() -> tuple[str, ...]:
    """Read configured external tool modules from environment."""
    return parse_tool_module_list(os.getenv("OPENPLANTER_TOOL_MODULES"))


def load_external_tool_plugins(module_names: Iterable[str]) -> list[ToolPlugin]:
    """Import external tool plugin modules and collect plugins.

    Each module must expose ``get_openplanter_tools()`` returning a list of
    ``ToolPlugin`` objects.
    """
    plugins: list[ToolPlugin] = []
    for module_name in module_names:
        mod = importlib.import_module(module_name)
        getter = getattr(mod, "get_openplanter_tools", None)
        if getter is None or not callable(getter):
            raise ValueError(
                f"Tool plugin module '{module_name}' is missing callable get_openplanter_tools()"
            )
        loaded = getter()
        if not isinstance(loaded, list):
            raise TypeError(
                f"Tool plugin module '{module_name}' returned non-list from get_openplanter_tools()"
            )
        for plugin in loaded:
            if not isinstance(plugin, ToolPlugin):
                raise TypeError(
                    f"Tool plugin module '{module_name}' returned non-ToolPlugin item: {type(plugin).__name__}"
                )
            plugins.append(plugin)
    return plugins

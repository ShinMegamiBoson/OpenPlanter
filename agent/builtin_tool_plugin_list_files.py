"""Standalone built-in plugin example: list_files.

This module intentionally contains one useful, simple plugin to serve as a
pedagogical example for plugin authors.
"""

from __future__ import annotations

from typing import Any

from .tool_defs import TOOL_DEFINITIONS
from .tool_registry import ToolPlugin, tool

PLUGIN_TOOLS: list[ToolPlugin] = []
_DEF_BY_NAME = {d["name"]: d for d in TOOL_DEFINITIONS}


@tool(
    name="list_files",
    description=str(_DEF_BY_NAME["list_files"]["description"]),
    parameters_schema=dict(_DEF_BY_NAME["list_files"]["parameters"]),
    collector=PLUGIN_TOOLS,
)
def list_files_tool(args: dict[str, Any], ctx: Any) -> str:
    """List files in the workspace, optionally filtered by glob."""
    glob = args.get("glob")
    return ctx.tools.list_files(glob=str(glob) if glob else None)


def get_builtin_list_files_tool_plugins() -> list[ToolPlugin]:
    """Return the standalone list_files built-in plugin."""
    return list(PLUGIN_TOOLS)

"""Decorator-collected built-in tool plugins (incremental migration).

This module uses a module-local collector and reuses metadata from the existing
static TOOL_DEFINITIONS list to avoid duplicating schemas during transition.
"""

from __future__ import annotations

from typing import Any

from .builtin_tool_plugin_list_files import get_builtin_list_files_tool_plugins
from .tool_defs import TOOL_DEFINITIONS
from .tool_registry import ToolPlugin, tool

BUILTIN_TOOL_PLUGINS: list[ToolPlugin] = []
BUILTIN_TOOL_PLUGINS.extend(get_builtin_list_files_tool_plugins())

_DEF_BY_NAME = {d["name"]: d for d in TOOL_DEFINITIONS}


def _desc(name: str) -> str:
    return str(_DEF_BY_NAME[name]["description"])


def _schema(name: str) -> dict[str, Any]:
    return dict(_DEF_BY_NAME[name]["parameters"])


@tool(
    name="think",
    description=_desc("think"),
    parameters_schema=_schema("think"),
    collector=BUILTIN_TOOL_PLUGINS,
)
def think_tool(args: dict[str, Any], _ctx: Any) -> str:
    note = str(args.get("note", ""))
    return f"Thought noted: {note}"


@tool(
    name="search_files",
    description=_desc("search_files"),
    parameters_schema=_schema("search_files"),
    collector=BUILTIN_TOOL_PLUGINS,
)
def search_files_tool(args: dict[str, Any], ctx: Any) -> str:
    query = str(args.get("query", "")).strip()
    glob = args.get("glob")
    if not query:
        return "search_files requires non-empty query"
    return ctx.tools.search_files(query=query, glob=str(glob) if glob else None)


@tool(
    name="repo_map",
    description=_desc("repo_map"),
    parameters_schema=_schema("repo_map"),
    collector=BUILTIN_TOOL_PLUGINS,
)
def repo_map_tool(args: dict[str, Any], ctx: Any) -> str:
    glob = args.get("glob")
    raw_max_files = args.get("max_files", 200)
    max_files = raw_max_files if isinstance(raw_max_files, int) else 200
    return ctx.tools.repo_map(glob=str(glob) if glob else None, max_files=max_files)


@tool(
    name="web_search",
    description=_desc("web_search"),
    parameters_schema=_schema("web_search"),
    collector=BUILTIN_TOOL_PLUGINS,
)
def web_search_tool(args: dict[str, Any], ctx: Any) -> str:
    query = str(args.get("query", "")).strip()
    if not query:
        return "web_search requires non-empty query"
    raw_num_results = args.get("num_results", 10)
    num_results = raw_num_results if isinstance(raw_num_results, int) else 10
    raw_include_text = args.get("include_text", False)
    include_text = bool(raw_include_text) if isinstance(raw_include_text, bool) else False
    return ctx.tools.web_search(query=query, num_results=num_results, include_text=include_text)


@tool(
    name="fetch_url",
    description=_desc("fetch_url"),
    parameters_schema=_schema("fetch_url"),
    collector=BUILTIN_TOOL_PLUGINS,
)
def fetch_url_tool(args: dict[str, Any], ctx: Any) -> str:
    urls = args.get("urls")
    if not isinstance(urls, list):
        return "fetch_url requires a list of URL strings"
    return ctx.tools.fetch_url([str(u) for u in urls if isinstance(u, str)])


@tool(
    name="read_file",
    description=_desc("read_file"),
    parameters_schema=_schema("read_file"),
    collector=BUILTIN_TOOL_PLUGINS,
)
def read_file_tool(args: dict[str, Any], ctx: Any) -> str:
    path = str(args.get("path", "")).strip()
    if not path:
        return "read_file requires path"
    hashline = args.get("hashline")
    hashline = hashline if hashline is not None else True
    return ctx.tools.read_file(path, hashline=hashline)


@tool(
    name="read_image",
    description=_desc("read_image"),
    parameters_schema=_schema("read_image"),
    collector=BUILTIN_TOOL_PLUGINS,
)
def read_image_tool(args: dict[str, Any], ctx: Any) -> str:
    path = str(args.get("path", "")).strip()
    if not path:
        return "read_image requires path"
    text, b64, media_type = ctx.tools.read_image(path)
    if b64 is not None and media_type is not None:
        ctx._pending_image.data = (b64, media_type)
    return text


@tool(
    name="write_file",
    description=_desc("write_file"),
    parameters_schema=_schema("write_file"),
    collector=BUILTIN_TOOL_PLUGINS,
)
def write_file_tool(args: dict[str, Any], ctx: Any) -> str:
    path = str(args.get("path", "")).strip()
    if not path:
        return "write_file requires path"
    content = str(args.get("content", ""))
    return ctx.tools.write_file(path, content)


@tool(
    name="apply_patch",
    description=_desc("apply_patch"),
    parameters_schema=_schema("apply_patch"),
    collector=BUILTIN_TOOL_PLUGINS,
)
def apply_patch_tool(args: dict[str, Any], ctx: Any) -> str:
    patch = str(args.get("patch", ""))
    if not patch.strip():
        return "apply_patch requires non-empty patch"
    return ctx.tools.apply_patch(patch)


@tool(
    name="edit_file",
    description=_desc("edit_file"),
    parameters_schema=_schema("edit_file"),
    collector=BUILTIN_TOOL_PLUGINS,
)
def edit_file_tool(args: dict[str, Any], ctx: Any) -> str:
    path = str(args.get("path", "")).strip()
    if not path:
        return "edit_file requires path"
    old_text = str(args.get("old_text", ""))
    new_text = str(args.get("new_text", ""))
    if not old_text:
        return "edit_file requires old_text"
    return ctx.tools.edit_file(path, old_text, new_text)


@tool(
    name="hashline_edit",
    description=_desc("hashline_edit"),
    parameters_schema=_schema("hashline_edit"),
    collector=BUILTIN_TOOL_PLUGINS,
)
def hashline_edit_tool(args: dict[str, Any], ctx: Any) -> str:
    path = str(args.get("path", "")).strip()
    if not path:
        return "hashline_edit requires path"
    edits = args.get("edits")
    if not isinstance(edits, list):
        return "hashline_edit requires edits array"
    return ctx.tools.hashline_edit(path, edits)


@tool(
    name="run_shell",
    description=_desc("run_shell"),
    parameters_schema=_schema("run_shell"),
    collector=BUILTIN_TOOL_PLUGINS,
)
def run_shell_tool(args: dict[str, Any], ctx: Any) -> str:
    command = str(args.get("command", "")).strip()
    if not command:
        return "run_shell requires command"
    raw_timeout = args.get("timeout")
    timeout = int(raw_timeout) if raw_timeout is not None else None
    return ctx.tools.run_shell(command, timeout=timeout)


@tool(
    name="run_shell_bg",
    description=_desc("run_shell_bg"),
    parameters_schema=_schema("run_shell_bg"),
    collector=BUILTIN_TOOL_PLUGINS,
)
def run_shell_bg_tool(args: dict[str, Any], ctx: Any) -> str:
    command = str(args.get("command", "")).strip()
    if not command:
        return "run_shell_bg requires command"
    return ctx.tools.run_shell_bg(command)


@tool(
    name="check_shell_bg",
    description=_desc("check_shell_bg"),
    parameters_schema=_schema("check_shell_bg"),
    collector=BUILTIN_TOOL_PLUGINS,
)
def check_shell_bg_tool(args: dict[str, Any], ctx: Any) -> str:
    raw_id = args.get("job_id")
    if raw_id is None:
        return "check_shell_bg requires job_id"
    return ctx.tools.check_shell_bg(int(raw_id))


@tool(
    name="kill_shell_bg",
    description=_desc("kill_shell_bg"),
    parameters_schema=_schema("kill_shell_bg"),
    collector=BUILTIN_TOOL_PLUGINS,
)
def kill_shell_bg_tool(args: dict[str, Any], ctx: Any) -> str:
    raw_id = args.get("job_id")
    if raw_id is None:
        return "kill_shell_bg requires job_id"
    return ctx.tools.kill_shell_bg(int(raw_id))


@tool(
    name="subtask",
    description=_desc("subtask"),
    parameters_schema=_schema("subtask"),
    collector=BUILTIN_TOOL_PLUGINS,
)
def subtask_tool(args: dict[str, Any], ctx: Any) -> str:
    return ctx._registry_subtask(args, ctx)


@tool(
    name="execute",
    description=_desc("execute"),
    parameters_schema=_schema("execute"),
    collector=BUILTIN_TOOL_PLUGINS,
)
def execute_tool(args: dict[str, Any], ctx: Any) -> str:
    return ctx._registry_execute(args, ctx)


@tool(
    name="list_artifacts",
    description=_desc("list_artifacts"),
    parameters_schema=_schema("list_artifacts"),
    collector=BUILTIN_TOOL_PLUGINS,
)
def list_artifacts_tool(args: dict[str, Any], ctx: Any) -> str:
    return ctx._registry_list_artifacts(args, ctx)


@tool(
    name="read_artifact",
    description=_desc("read_artifact"),
    parameters_schema=_schema("read_artifact"),
    collector=BUILTIN_TOOL_PLUGINS,
)
def read_artifact_tool(args: dict[str, Any], ctx: Any) -> str:
    return ctx._registry_read_artifact(args, ctx)


def get_builtin_tool_plugins() -> list[ToolPlugin]:
    """Return decorator-collected built-in tool plugins."""
    order = [d["name"] for d in TOOL_DEFINITIONS]
    by_name = {plugin.definition.name: plugin for plugin in BUILTIN_TOOL_PLUGINS}
    return [by_name[name] for name in order if name in by_name]

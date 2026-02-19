"""Provider-neutral tool definitions for the OpenPlanter agent.

Single source of truth for tool schemas. Converter helpers produce the
provider-specific shapes expected by OpenAI and Anthropic APIs.
"""
from __future__ import annotations

from typing import Any

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "list_files",
        "description": "List files in the workspace directory. Optionally filter with a glob pattern.",
        "parameters": {
            "type": "object",
            "properties": {
                "glob": {
                    "type": "string",
                    "description": "Optional glob pattern to filter files.",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_files",
        "description": "Search file contents in the workspace for a text or regex query.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Text or regex to search for.",
                },
                "glob": {
                    "type": "string",
                    "description": "Optional glob pattern to restrict which files are searched.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "repo_map",
        "description": "Build a lightweight map of source files and symbols to speed up code navigation.",
        "parameters": {
            "type": "object",
            "properties": {
                "glob": {
                    "type": "string",
                    "description": "Optional glob pattern to limit which files are scanned.",
                },
                "max_files": {
                    "type": "integer",
                    "description": "Maximum number of files to scan (1-500, default 200).",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "web_search",
        "description": "Search the web using the Exa API. Returns URLs, titles, and optional page text.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Web search query string.",
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of results to return (1-20, default 10).",
                },
                "include_text": {
                    "type": "boolean",
                    "description": "Whether to include page text in results.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "fetch_url",
        "description": "Fetch and return the text content of one or more URLs.",
        "parameters": {
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of URLs to fetch.",
                },
            },
            "required": ["urls"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_file",
        "description": "Read the contents of a file in the workspace. Lines are numbered LINE:HASH|content by default for use with hashline_edit. Set hashline=false for plain N|content.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative or absolute path within the workspace.",
                },
                "hashline": {
                    "type": "boolean",
                    "description": "Prefix each line with LINE:HASH| format for content verification. Default true.",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "write_file",
        "description": "Create or overwrite a file in the workspace with the given content.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path for the file.",
                },
                "content": {
                    "type": "string",
                    "description": "Full file content to write.",
                },
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    },
    {
        "name": "apply_patch",
        "description": (
            "Apply a Codex-style patch to one or more files. "
            "Use the *** Begin Patch / *** End Patch format with "
            "Update File, Add File, and Delete File operations."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "patch": {
                    "type": "string",
                    "description": "The full patch block in Codex patch format.",
                },
            },
            "required": ["patch"],
            "additionalProperties": False,
        },
    },
    {
        "name": "edit_file",
        "description": (
            "Replace a specific text span in a file. Provide the exact old text "
            "to find and the new text to replace it with. The old text must appear "
            "exactly once in the file."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the file to edit.",
                },
                "old_text": {
                    "type": "string",
                    "description": "The exact text to find and replace.",
                },
                "new_text": {
                    "type": "string",
                    "description": "The replacement text.",
                },
            },
            "required": ["path", "old_text", "new_text"],
            "additionalProperties": False,
        },
    },
    {
        "name": "hashline_edit",
        "description": (
            "Edit a file using hash-anchored line references from read_file(hashline=true). "
            "Operations: set_line (replace one line), replace_lines (replace a range), "
            "insert_after (insert new lines after an anchor)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to the file."},
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "set_line": {
                                "type": "string",
                                "description": "Anchor 'N:HH' for single-line replace.",
                            },
                            "replace_lines": {
                                "type": "object",
                                "description": "Range with 'start' and 'end' anchors.",
                                "properties": {
                                    "start": {"type": "string"},
                                    "end": {"type": "string"},
                                },
                                "required": ["start", "end"],
                                "additionalProperties": False,
                            },
                            "insert_after": {
                                "type": "string",
                                "description": "Anchor 'N:HH' to insert after.",
                            },
                            "content": {
                                "type": "string",
                                "description": "New content for the operation.",
                            },
                        },
                        "required": [],
                        "additionalProperties": False,
                    },
                    "description": "Edit operations: set_line, replace_lines, or insert_after.",
                },
            },
            "required": ["path", "edits"],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_shell",
        "description": "Execute a shell command from the workspace root and return its output.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds for this command (default: agent default, max: 600).",
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_shell_bg",
        "description": "Start a shell command in the background. Returns a job ID to check or kill later.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to run in the background.",
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
    {
        "name": "check_shell_bg",
        "description": "Check the status and output of a background job started with run_shell_bg.",
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "integer",
                    "description": "The job ID returned by run_shell_bg.",
                },
            },
            "required": ["job_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kill_shell_bg",
        "description": "Kill a background job started with run_shell_bg.",
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "integer",
                    "description": "The job ID returned by run_shell_bg.",
                },
            },
            "required": ["job_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "think",
        "description": "Record an internal planning thought. Use this to reason about the task before acting.",
        "parameters": {
            "type": "object",
            "properties": {
                "note": {
                    "type": "string",
                    "description": "Your planning thought or reasoning note.",
                },
            },
            "required": ["note"],
            "additionalProperties": False,
        },
    },
    {
        "name": "subtask",
        "description": "Spawn a recursive sub-agent to solve a smaller sub-problem. The result is returned as an observation.",
        "parameters": {
            "type": "object",
            "properties": {
                "objective": {
                    "type": "string",
                    "description": "Clear objective for the sub-agent to accomplish.",
                },
                "model": {
                    "type": "string",
                    "description": "Optional model for subtask (e.g. 'claude-sonnet-4-5-20250929', 'claude-haiku-4-5-20251001').",
                },
                "reasoning_effort": {
                    "type": "string",
                    "enum": ["xhigh", "high", "medium", "low"],
                    "description": "Optional reasoning effort for the subtask model. For OpenAI codex models, this controls the delegation level.",
                },
                "acceptance_criteria": {
                    "type": "string",
                    "description": "Acceptance criteria for judging the subtask result. A lightweight judge evaluates the result against these criteria and appends PASS/FAIL to your observation. Be specific and verifiable.",
                },
            },
            "required": ["objective", "acceptance_criteria"],
            "additionalProperties": False,
        },
    },
    {
        "name": "execute",
        "description": (
            "Hand an atomic sub-problem to a leaf executor agent with full tool access. "
            "Use this when the sub-problem requires no further decomposition and can be "
            "solved directly (e.g. write a file, run tests, apply a patch). The executor "
            "has no subtask or execute tools — it must solve the objective in one pass."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "objective": {
                    "type": "string",
                    "description": "Clear, specific objective for the executor to accomplish.",
                },
                "acceptance_criteria": {
                    "type": "string",
                    "description": "Acceptance criteria for judging the executor result. A lightweight judge evaluates the result against these criteria and appends PASS/FAIL to your observation. Be specific and verifiable.",
                },
            },
            "required": ["objective", "acceptance_criteria"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_artifacts",
        "description": "List artifacts from previous subagent runs. Returns ID, objective, and result summary for each.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_artifact",
        "description": (
            "Read a previous subagent's conversation log artifact. "
            "Returns JSONL records of the subagent's full conversation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "artifact_id": {
                    "type": "string",
                    "description": "Artifact ID from list_artifacts.",
                },
                "offset": {
                    "type": "integer",
                    "description": "Start line (0-indexed). Default 0.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max lines to return. Default 100.",
                },
            },
            "required": ["artifact_id"],
            "additionalProperties": False,
        },
    },
]


_ARTIFACT_TOOLS = {"list_artifacts", "read_artifact"}
_DELEGATION_TOOLS = {"subtask", "execute", "list_artifacts", "read_artifact"}


def _strip_acceptance_criteria(defs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove acceptance_criteria property from subtask/execute schemas."""
    import copy
    result = []
    for d in defs:
        if d["name"] in ("subtask", "execute"):
            d = copy.deepcopy(d)
            d["parameters"]["properties"].pop("acceptance_criteria", None)
            req = d["parameters"].get("required", [])
            if "acceptance_criteria" in req:
                d["parameters"]["required"] = [r for r in req if r != "acceptance_criteria"]
        result.append(d)
    return result


def get_tool_definitions(
    include_subtask: bool = True,
    include_artifacts: bool = False,
    include_acceptance_criteria: bool = False,
) -> list[dict[str, Any]]:
    """Return tool definitions based on mode.

    - ``include_subtask=True`` (normal recursive) → everything except execute, artifact tools.
    - ``include_subtask=False`` (flat / executor) → no subtask, no execute, no artifact tools.
    - ``include_artifacts=True`` → add list_artifacts + read_artifact.
    - ``include_acceptance_criteria=False`` → strip acceptance_criteria from schemas.
    """
    if include_subtask:
        defs = [d for d in TOOL_DEFINITIONS if d["name"] not in ("execute",) and d["name"] not in _ARTIFACT_TOOLS]
    else:
        defs = [d for d in TOOL_DEFINITIONS if d["name"] not in _DELEGATION_TOOLS]

    if include_artifacts:
        defs += [d for d in TOOL_DEFINITIONS if d["name"] in _ARTIFACT_TOOLS]

    if not include_acceptance_criteria:
        defs = _strip_acceptance_criteria(defs)
    return defs


def _make_strict_parameters(params: dict[str, Any]) -> dict[str, Any]:
    """For OpenAI strict mode: all properties must be required.

    Optional properties (not in 'required') are made nullable by wrapping
    their type with anyOf [original, null].  Recurses into nested objects
    and array items so that every ``type: object`` node has
    ``additionalProperties: false`` and a complete ``required`` list.
    """
    import copy
    out = copy.deepcopy(params)
    _strict_fixup(out)
    return out


def _strict_fixup(schema: dict[str, Any]) -> None:
    """Recursively enforce OpenAI strict-mode constraints on *schema* in-place."""
    schema_type = schema.get("type")

    if schema_type == "object":
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        all_keys = list(properties.keys())

        for key in all_keys:
            prop = properties[key]
            if isinstance(prop, dict):
                _strict_fixup(prop)
            if key not in required:
                if "type" in prop:
                    original_type = prop.pop("type")
                    desc = prop.pop("description", None)
                    new_prop: dict[str, Any] = {"anyOf": [{"type": original_type}, {"type": "null"}]}
                    if desc:
                        new_prop["description"] = desc
                    for k, v in prop.items():
                        if k not in new_prop:
                            new_prop["anyOf"][0][k] = v
                    properties[key] = new_prop

        schema["required"] = all_keys
        schema["additionalProperties"] = False

    elif schema_type == "array":
        items = schema.get("items")
        if isinstance(items, dict):
            _strict_fixup(items)


def to_openai_tools(
    defs: list[dict[str, Any]] | None = None,
    strict: bool = True,
) -> list[dict[str, Any]]:
    """Convert provider-neutral definitions to OpenAI tools array format."""
    defs = defs if defs is not None else TOOL_DEFINITIONS
    tools: list[dict[str, Any]] = []
    for d in defs:
        parameters = d["parameters"]
        if strict:
            parameters = _make_strict_parameters(parameters)
        tool: dict[str, Any] = {
            "type": "function",
            "function": {
                "name": d["name"],
                "description": d["description"],
                "parameters": parameters,
            },
        }
        if strict:
            tool["function"]["strict"] = True
        tools.append(tool)
    return tools


def to_anthropic_tools(
    defs: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Convert provider-neutral definitions to Anthropic tools array format."""
    defs = defs if defs is not None else TOOL_DEFINITIONS
    tools: list[dict[str, Any]] = []
    for d in defs:
        tools.append(
            {
                "name": d["name"],
                "description": d["description"],
                "input_schema": d["parameters"],
            }
        )
    return tools

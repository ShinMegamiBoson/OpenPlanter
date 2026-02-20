# Tool-Handler Registry Refactoring

**Date:** 2026-02-20
**PR:** #7

---

## Problem

`_apply_tool_call` in `agent/engine.py` was a 260-line `if/elif` chain dispatching 18 tool names:

```python
def _apply_tool_call(self, name, args, depth, context, on_event, ...):
    if name == "think":
        ...
    elif name == "list_files":
        ...
    elif name == "execute":
        # 40 lines of complex logic
    ...
    # 15 more elif branches
```

Two concrete problems:

1. **Adding a tool requires editing `_apply_tool_call`** — a 260-line method — to insert another `elif`. Every addition risks touching unrelated branches.
2. **The method has no coherent responsibility.** It mixes dispatch, argument extraction, error handling, and domain logic for 18 unrelated tools in one place.

---

## Solution: Split Registry

Replace the `if/elif` chain with a handler registry for the 17 stateless tools, while keeping the 2 complex engine-owned tools (`subtask`, `execute`) as explicit named methods.

### Handler signature

All registry handlers share a uniform signature:

```python
Callable[[dict[str, Any]], tuple[bool, str]]
```

- Input: raw `args` dict from the tool call.
- Output: `(ok: bool, result: str)` — the same convention used throughout the engine.

### Registry construction

The registry is built once during `__post_init__` via `_build_tool_registry()`:

```python
def __post_init__(self) -> None:
    ...
    self._tool_handlers: dict[str, Callable[[dict[str, Any]], tuple[bool, str]]] = (
        self._build_tool_registry()
    )

def _build_tool_registry(self) -> dict[str, Callable[[dict[str, Any]], tuple[bool, str]]]:
    return {
        "think":          self._handle_think,
        "list_files":     self._handle_list_files,
        "search_files":   self._handle_search_files,
        "repo_map":       self._handle_repo_map,
        "web_search":     self._handle_web_search,
        "fetch_url":      self._handle_fetch_url,
        "read_file":      self._handle_read_file,
        "write_file":     self._handle_write_file,
        "apply_patch":    self._handle_apply_patch,
        "edit_file":      self._handle_edit_file,
        "hashline_edit":  self._handle_hashline_edit,
        "run_shell":      self._handle_run_shell,
        "run_shell_bg":   self._handle_run_shell_bg,
        "check_shell_bg": self._handle_check_shell_bg,
        "kill_shell_bg":  self._handle_kill_shell_bg,
        "list_artifacts": self._handle_list_artifacts,
        "read_artifact":  self._handle_read_artifact,
    }
```

Each `_handle_*` method extracts arguments from the dict and delegates to `self.tools.*`. Example:

```python
def _handle_read_file(self, args: dict[str, Any]) -> tuple[bool, str]:
    path = args.get("path", "")
    offset = args.get("offset")
    limit = args.get("limit")
    return self.tools.read_file(path, offset=offset, limit=limit)
```

### `_apply_tool_call` after refactoring

```python
def _apply_tool_call(
    self,
    name: str,
    args: dict[str, Any],
    depth: int,
    context: list[Message],
    on_event: EventCallback,
    on_step: StepCallback,
    deadline: float,
    current_model: str,
    replay_logger: ReplayLogger | None,
    step: int,
) -> tuple[bool, str]:
    # Policy check (unchanged)
    if not self._tool_allowed(name):
        return False, f"Tool '{name}' is not enabled."

    # Registry dispatch (17 stateless tools)
    if name in self._tool_handlers:
        return self._tool_handlers[name](args)

    # Explicit dispatch for call-time-dependent tools
    if name == "subtask":
        return self._apply_subtask(args, depth, context, on_event, on_step,
                                   deadline, current_model, replay_logger)
    if name == "execute":
        return self._apply_execute(args, depth, context, on_event, on_step,
                                   deadline, current_model, replay_logger, step)

    return False, f"Unknown tool: {name}"
```

### Why `subtask` and `execute` are outside the registry

Both tools require call-time parameters that vary per invocation:

| Parameter | Why it can't be pre-bound |
|-----------|--------------------------|
| `depth` | Tracks recursion level; changes each call |
| `context` | Current message history; mutated during a run |
| `on_event`, `on_step` | Caller-supplied callbacks; differ per invocation |
| `deadline` | Absolute timestamp; set at run start |
| `current_model`, `replay_logger` | Resolved at call time |
| `step` | Current step counter |

Forcing these into `handler(args)` would require either a fat mutable context object passed to every handler (adding complexity everywhere for two edge cases) or lambda rebinding per call (closures on every tool invocation, creating noise for the common case).

The split keeps the registry interface clean (`args` in, `(ok, str)` out) and isolates the complexity where it actually lives.

---

## Tool Inventory

**17 tools in registry:**

| Tool | Handler method |
|------|---------------|
| `think` | `_handle_think` |
| `list_files` | `_handle_list_files` |
| `search_files` | `_handle_search_files` |
| `repo_map` | `_handle_repo_map` |
| `web_search` | `_handle_web_search` |
| `fetch_url` | `_handle_fetch_url` |
| `read_file` | `_handle_read_file` |
| `write_file` | `_handle_write_file` |
| `apply_patch` | `_handle_apply_patch` |
| `edit_file` | `_handle_edit_file` |
| `hashline_edit` | `_handle_hashline_edit` |
| `run_shell` | `_handle_run_shell` |
| `run_shell_bg` | `_handle_run_shell_bg` |
| `check_shell_bg` | `_handle_check_shell_bg` |
| `kill_shell_bg` | `_handle_kill_shell_bg` |
| `list_artifacts` | `_handle_list_artifacts` |
| `read_artifact` | `_handle_read_artifact` |

**2 tools dispatched explicitly:** `subtask`, `execute`

---

## Alternatives Considered

### Uniform registry with `_CallCtx` dataclass

Package all call-time parameters into a context object and give every handler the same extended signature:

```python
Callable[[dict[str, Any], _CallCtx], tuple[bool, str]]
```

**Why rejected:** This passes a context object to all 17 stateless handlers that never use it. It introduces a new dataclass solely to handle two edge cases, and forces every future handler author to accept and thread a context parameter they don't need.

### Closures at call time

Rebind `subtask` and `execute` into the registry on each `_apply_tool_call` invocation:

```python
handlers = {**self._tool_handlers,
            "subtask": lambda args: self._apply_subtask(args, depth, ...),
            "execute": lambda args: self._apply_execute(args, depth, ...)}
```

**Why rejected:** Creates two lambdas on every tool invocation, not just when those tools are called. The code is also harder to follow — the registry appears uniform but is quietly rebuilt every call.

---

## How to Add a New Tool

Three steps, no changes to `_apply_tool_call`:

1. **Add a handler method** on `RLMEngine`:

   ```python
   def _handle_my_tool(self, args: dict[str, Any]) -> tuple[bool, str]:
       param = args.get("param", "")
       return self.tools.my_tool(param)
   ```

2. **Register it** in `_build_tool_registry()`:

   ```python
   "my_tool": self._handle_my_tool,
   ```

3. **Add its schema** to `tool_defs.py`.

If the new tool needs call-time parameters (depth, context, callbacks), follow the `subtask`/`execute` pattern: add an `_apply_*` method and an explicit `if name == "..."` branch in `_apply_tool_call`.

"""Minimal tool registry skeleton for incremental migration.

This module intentionally starts small: it wraps provider-neutral tool
definitions and exposes filtering/lookup helpers so `tool_defs.py` can move to
registry-backed export without changing engine dispatch yet.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any
from typing import Callable

ToolHandler = Callable[[dict[str, Any], Any], str]


@dataclass(slots=True)
class ToolDefinition:
    """Provider-neutral tool definition wrapper."""

    name: str
    description: str
    parameters: dict[str, Any]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ToolDefinition":
        """Build a typed wrapper from a provider-neutral tool definition dict."""
        return cls(
            name=str(payload["name"]),
            description=str(payload["description"]),
            parameters=copy.deepcopy(dict(payload["parameters"])),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a deep-copied provider-neutral tool definition."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": copy.deepcopy(self.parameters),
        }


@dataclass(slots=True)
class ToolPlugin:
    """Decorator-friendly tool plugin bundle."""

    definition: ToolDefinition
    handler: ToolHandler
    policy: dict[str, Any] = field(default_factory=dict)


def tool(
    *,
    name: str,
    description: str,
    parameters_schema: dict[str, Any],
    collector: list[ToolPlugin] | None = None,
    policy: dict[str, Any] | None = None,
):
    """Decorator to build and optionally collect a tool plugin."""

    def decorator(fn: ToolHandler) -> ToolHandler:
        plugin = ToolPlugin(
            definition=ToolDefinition(
                name=name,
                description=description,
                parameters=copy.deepcopy(parameters_schema),
            ),
            handler=fn,
            policy=copy.deepcopy(policy or {}),
        )
        setattr(fn, "__openplanter_tool_plugin__", plugin)
        if collector is not None:
            collector.append(plugin)
        return fn

    return decorator


@dataclass(slots=True)
class ToolRegistry:
    """Registry for provider-neutral tool definitions.

    This is a migration scaffold for the future plugin-based registry. It keeps
    name collision checks and filtering logic in one place while preserving the
    existing tool definition dict format.
    """

    _tools: dict[str, ToolDefinition] = field(default_factory=dict)
    _order: list[str] = field(default_factory=list)
    _handlers: dict[str, ToolHandler] = field(default_factory=dict)
    _policies: dict[str, dict[str, Any]] = field(default_factory=dict)

    def register_definition(self, payload: dict[str, Any]) -> None:
        """Register one provider-neutral tool definition dict."""
        tool = ToolDefinition.from_dict(payload)
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool definition name: {tool.name}")
        self._tools[tool.name] = tool
        self._order.append(tool.name)

    def register_definition_obj(self, tool: ToolDefinition) -> None:
        """Register one typed tool definition."""
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool definition name: {tool.name}")
        self._tools[tool.name] = ToolDefinition(
            name=tool.name,
            description=tool.description,
            parameters=copy.deepcopy(tool.parameters),
        )
        self._order.append(tool.name)

    def register_definitions(self, payloads: list[dict[str, Any]]) -> None:
        """Register multiple provider-neutral tool definitions."""
        for payload in payloads:
            self.register_definition(payload)

    def list_definitions(self) -> list[dict[str, Any]]:
        """Return all registered tool definitions in insertion order."""
        return [self._tools[name].to_dict() for name in self._order]

    def filtered_definitions(
        self,
        *,
        exclude_names: set[str] | None = None,
        include_names: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return filtered tool definitions preserving insertion order."""
        exclude = exclude_names or set()
        include = include_names
        out: list[dict[str, Any]] = []
        for name in self._order:
            if name in exclude:
                continue
            if include is not None and name not in include:
                continue
            out.append(self._tools[name].to_dict())
        return out

    def register_handler(self, name: str, handler: ToolHandler) -> None:
        """Register an execution handler for an existing tool definition."""
        if name not in self._tools:
            raise KeyError(f"Cannot register handler for unknown tool: {name}")
        self._handlers[name] = handler
        self._policies.setdefault(name, {})

    def register_plugin(self, plugin: ToolPlugin, *, allow_handler_override: bool = False) -> None:
        """Register a plugin's definition and handler.

        Duplicate plugin names are rejected by default to avoid accidental
        handler replacement. Pass ``allow_handler_override=True`` only when an
        intentional override is desired and the definition metadata matches the
        existing definition exactly.
        """
        name = plugin.definition.name
        if name not in self._tools:
            self.register_definition_obj(plugin.definition)
            self._handlers[name] = plugin.handler
            self._policies[name] = copy.deepcopy(plugin.policy)
            return

        existing = self._tools[name]
        new_def = plugin.definition
        if (
            existing.description != new_def.description
            or existing.parameters != new_def.parameters
            or self._policies.get(name, {}) != plugin.policy
        ):
            raise ValueError(f"Conflicting duplicate tool plugin definition: {name}")
        if not allow_handler_override:
            raise ValueError(f"Duplicate tool plugin registration: {name}")
        self._handlers[name] = plugin.handler
        self._policies[name] = copy.deepcopy(plugin.policy)

    def register_plugins(
        self,
        plugins: list[ToolPlugin],
        *,
        allow_handler_override: bool = False,
    ) -> None:
        """Register multiple plugins."""
        for plugin in plugins:
            self.register_plugin(plugin, allow_handler_override=allow_handler_override)

    def try_invoke(
        self,
        name: str,
        args: dict[str, Any],
        ctx: Any = None,
    ) -> tuple[bool, str]:
        """Try to invoke a registered handler by tool name.

        Returns ``(handled, result_text)``. If no handler is registered for the
        tool, returns ``(False, "")`` so callers can fall back to legacy paths.
        """
        handler = self._handlers.get(name)
        if handler is None:
            return False, ""
        return True, handler(args, ctx)

    def get_policy(self, name: str) -> dict[str, Any]:
        """Return a deep-copied policy metadata dict for a tool."""
        return copy.deepcopy(self._policies.get(name, {}))


    @classmethod
    def from_definitions(cls, payloads: list[dict[str, Any]]) -> "ToolRegistry":
        """Convenience constructor from provider-neutral tool definition dicts."""
        registry = cls()
        registry.register_definitions(payloads)
        return registry

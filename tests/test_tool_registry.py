from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

from agent.tool_registry import ToolDefinition, ToolPlugin, ToolRegistry, tool


class ToolRegistryDefinitionTests(unittest.TestCase):
    def test_register_definition_duplicate_name_raises(self) -> None:
        reg = ToolRegistry()
        payload = {
            "name": "x",
            "description": "desc",
            "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        }
        reg.register_definition(payload)
        with self.assertRaises(ValueError):
            reg.register_definition(payload)

    def test_register_handler_unknown_tool_raises(self) -> None:
        reg = ToolRegistry()
        with self.assertRaises(KeyError):
            reg.register_handler("missing", lambda _args, _ctx: "nope")

    def test_try_invoke_unhandled_returns_false_empty(self) -> None:
        reg = ToolRegistry.from_definitions([
            {
                "name": "x",
                "description": "desc",
                "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
            }
        ])
        handled, out = reg.try_invoke("x", {}, None)
        self.assertFalse(handled)
        self.assertEqual(out, "")

    def test_try_invoke_calls_handler_and_returns_true(self) -> None:
        reg = ToolRegistry.from_definitions([
            {
                "name": "x",
                "description": "desc",
                "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
            }
        ])

        calls: list[tuple[dict, object]] = []

        def handler(args, ctx):
            calls.append((args, ctx))
            return "handled"

        reg.register_handler("x", handler)
        handled, out = reg.try_invoke("x", {"a": 1}, "ctx")
        self.assertTrue(handled)
        self.assertEqual(out, "handled")
        self.assertEqual(calls, [({"a": 1}, "ctx")])

    def test_register_plugin_registers_definition_and_handler(self) -> None:
        reg = ToolRegistry()
        plugin = ToolPlugin(
            definition=ToolDefinition(
                name="plug",
                description="plugin tool",
                parameters={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
            ),
            handler=lambda _args, _ctx: "ok",
        )
        reg.register_plugin(plugin)

        self.assertEqual([d["name"] for d in reg.list_definitions()], ["plug"])
        handled, out = reg.try_invoke("plug", {}, None)
        self.assertTrue(handled)
        self.assertEqual(out, "ok")

    def test_register_plugin_stores_policy_metadata_deepcopy(self) -> None:
        reg = ToolRegistry()
        plugin = ToolPlugin(
            definition=ToolDefinition(
                name="mutating.tool",
                description="plugin tool",
                parameters={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
            ),
            handler=lambda _args, _ctx: "ok",
            policy={"requires_confirmation": True, "tags": ["mutating"]},
        )
        reg.register_plugin(plugin)

        policy = reg.get_policy("mutating.tool")
        self.assertEqual(policy["requires_confirmation"], True)
        self.assertEqual(policy["tags"], ["mutating"])
        policy["tags"].append("changed")
        self.assertEqual(reg.get_policy("mutating.tool")["tags"], ["mutating"])

    def test_register_plugin_duplicate_name_raises_by_default(self) -> None:
        reg = ToolRegistry()
        base_def = ToolDefinition(
            name="plug",
            description="plugin tool",
            parameters={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        )
        reg.register_plugin(ToolPlugin(definition=base_def, handler=lambda _a, _c: "v1"))
        with self.assertRaises(ValueError):
            reg.register_plugin(ToolPlugin(definition=base_def, handler=lambda _a, _c: "v2"))

        self.assertEqual(len(reg.list_definitions()), 1)
        handled, out = reg.try_invoke("plug", {}, None)
        self.assertTrue(handled)
        self.assertEqual(out, "v1")

    def test_register_plugin_duplicate_name_can_override_when_explicit(self) -> None:
        reg = ToolRegistry()
        base_def = ToolDefinition(
            name="plug",
            description="plugin tool",
            parameters={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        )
        reg.register_plugin(ToolPlugin(definition=base_def, handler=lambda _a, _c: "v1"))
        reg.register_plugin(
            ToolPlugin(definition=base_def, handler=lambda _a, _c: "v2"),
            allow_handler_override=True,
        )

        self.assertEqual(len(reg.list_definitions()), 1)
        handled, out = reg.try_invoke("plug", {}, None)
        self.assertTrue(handled)
        self.assertEqual(out, "v2")

    def test_register_plugin_duplicate_name_conflicting_metadata_raises(self) -> None:
        reg = ToolRegistry()
        reg.register_plugin(
            ToolPlugin(
                definition=ToolDefinition(
                    name="plug",
                    description="plugin tool",
                    parameters={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
                ),
                handler=lambda _a, _c: "v1",
            )
        )
        conflicting = ToolPlugin(
            definition=ToolDefinition(
                name="plug",
                description="different",
                parameters={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
            ),
            handler=lambda _a, _c: "v2",
        )
        with self.assertRaises(ValueError):
            reg.register_plugin(conflicting, allow_handler_override=True)

    def test_register_plugin_duplicate_name_conflicting_policy_raises(self) -> None:
        reg = ToolRegistry()
        base_def = ToolDefinition(
            name="plug",
            description="plugin tool",
            parameters={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        )
        reg.register_plugin(
            ToolPlugin(definition=base_def, handler=lambda _a, _c: "v1", policy={"requires_confirmation": True})
        )
        with self.assertRaises(ValueError):
            reg.register_plugin(
                ToolPlugin(definition=base_def, handler=lambda _a, _c: "v2", policy={}),
                allow_handler_override=True,
            )

    def test_list_definitions_returns_deep_copies(self) -> None:
        reg = ToolRegistry.from_definitions([
            {
                "name": "x",
                "description": "desc",
                "parameters": {
                    "type": "object",
                    "properties": {"a": {"type": "string"}},
                    "required": [],
                    "additionalProperties": False,
                },
            }
        ])
        listed = reg.list_definitions()
        listed[0]["parameters"]["properties"]["a"]["type"] = "integer"
        relisted = reg.list_definitions()
        self.assertEqual(relisted[0]["parameters"]["properties"]["a"]["type"], "string")


class ToolDecoratorTests(unittest.TestCase):
    def test_tool_decorator_attaches_plugin_metadata(self) -> None:
        collector = []

        @tool(
            name="demo.tool",
            description="demo",
            parameters_schema={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
            collector=collector,
        )
        def fn(args, ctx):
            return "ok"

        self.assertEqual(len(collector), 1)
        plugin = collector[0]
        self.assertEqual(plugin.definition.name, "demo.tool")
        self.assertIs(getattr(fn, "__openplanter_tool_plugin__"), plugin)

    def test_tool_decorator_deepcopies_schema(self) -> None:
        collector = []
        schema = {
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": [],
            "additionalProperties": False,
        }

        @tool(
            name="demo.schema",
            description="demo",
            parameters_schema=schema,
            collector=collector,
        )
        def fn(args, ctx):
            return "ok"

        schema["properties"]["x"]["type"] = "integer"
        self.assertEqual(collector[0].definition.parameters["properties"]["x"]["type"], "string")
        # mutate plugin copy too; original should remain modified independently
        collector[0].definition.parameters["properties"]["x"]["type"] = "number"
        self.assertEqual(schema["properties"]["x"]["type"], "integer")

    def test_tool_decorator_deepcopies_policy(self) -> None:
        collector = []
        policy = {"requires_confirmation": True, "tags": ["mutating"]}

        @tool(
            name="demo.policy",
            description="demo",
            parameters_schema={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
            collector=collector,
            policy=policy,
        )
        def fn(args, ctx):
            return "ok"

        policy["tags"].append("changed")
        self.assertEqual(collector[0].policy["tags"], ["mutating"])

    def test_external_module_plugin_can_use_real_rng_library(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            module_path = Path(tmpdir) / "thirdparty_rng_plugin.py"
            module_path.write_text(
                """
from __future__ import annotations

import secrets
from typing import Any

from agent.tool_registry import ToolPlugin, tool

PLUGIN_TOOLS: list[ToolPlugin] = []


@tool(
    name="rng.random_number",
    description="Return a cryptographically strong random integer.",
    parameters_schema={
        "type": "object",
        "properties": {
            "num_bits": {"type": "integer", "description": "Number of bits (1-64)."},
        },
        "required": ["num_bits"],
        "additionalProperties": False,
    },
    collector=PLUGIN_TOOLS,
)
def random_number_tool(args: dict[str, Any], _ctx: Any) -> str:
    raw_num_bits = args.get("num_bits")
    if not isinstance(raw_num_bits, int):
        return "rng.random_number requires integer num_bits"
    if raw_num_bits < 1 or raw_num_bits > 64:
        return "rng.random_number num_bits must be between 1 and 64"
    return str(secrets.randbits(raw_num_bits))


def get_openplanter_tools() -> list[ToolPlugin]:
    return list(PLUGIN_TOOLS)
""",
                encoding="utf-8",
            )

            spec = importlib.util.spec_from_file_location("thirdparty_rng_plugin", module_path)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            sys.modules["thirdparty_rng_plugin"] = module
            try:
                spec.loader.exec_module(module)
                plugins = module.get_openplanter_tools()
                self.assertEqual(len(plugins), 1)
                self.assertEqual(plugins[0].definition.name, "rng.random_number")

                reg = ToolRegistry()
                reg.register_plugins(plugins)
                handled, out = reg.try_invoke("rng.random_number", {"num_bits": 16}, None)

                self.assertTrue(handled)
                value = int(out)
                self.assertGreaterEqual(value, 0)
                self.assertLess(value, 2**16)
            finally:
                sys.modules.pop("thirdparty_rng_plugin", None)

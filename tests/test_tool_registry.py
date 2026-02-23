from __future__ import annotations

import unittest

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

    def test_register_plugin_same_name_overrides_handler_without_duplicate_definition(self) -> None:
        reg = ToolRegistry()
        base_def = ToolDefinition(
            name="plug",
            description="plugin tool",
            parameters={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        )
        reg.register_plugin(ToolPlugin(definition=base_def, handler=lambda _a, _c: "v1"))
        reg.register_plugin(ToolPlugin(definition=base_def, handler=lambda _a, _c: "v2"))

        self.assertEqual(len(reg.list_definitions()), 1)
        handled, out = reg.try_invoke("plug", {}, None)
        self.assertTrue(handled)
        self.assertEqual(out, "v2")

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


from __future__ import annotations

import types
import unittest
from unittest.mock import patch

from agent.plugin_loader import load_external_tool_plugins, parse_tool_module_list
from agent.tool_registry import ToolDefinition, ToolPlugin


class ParseToolModuleListTests(unittest.TestCase):
    def test_empty_values(self) -> None:
        self.assertEqual(parse_tool_module_list(None), ())
        self.assertEqual(parse_tool_module_list(""), ())

    def test_parses_trims_and_dedupes(self) -> None:
        value = " foo.bar , baz.qux,foo.bar ,, baz.qux  "
        self.assertEqual(parse_tool_module_list(value), ("foo.bar", "baz.qux"))


class LoadExternalToolPluginsTests(unittest.TestCase):
    def test_loads_plugins_from_module(self) -> None:
        plugin = ToolPlugin(
            definition=ToolDefinition(
                name="ext.echo",
                description="Echo",
                parameters={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
            ),
            handler=lambda _args, _ctx: "ok",
        )
        mod = types.ModuleType("ext_demo")
        mod.get_openplanter_tools = lambda: [plugin]  # type: ignore[attr-defined]

        with patch("agent.plugin_loader.importlib.import_module", return_value=mod) as mocked_import:
            loaded = load_external_tool_plugins(["ext_demo"])
        mocked_import.assert_called_once_with("ext_demo")
        self.assertEqual(loaded, [plugin])

    def test_missing_getter_raises(self) -> None:
        mod = types.ModuleType("bad_mod")
        with patch("agent.plugin_loader.importlib.import_module", return_value=mod):
            with self.assertRaises(ValueError):
                load_external_tool_plugins(["bad_mod"])

    def test_non_list_return_raises(self) -> None:
        mod = types.ModuleType("bad_mod")
        mod.get_openplanter_tools = lambda: "nope"  # type: ignore[attr-defined]
        with patch("agent.plugin_loader.importlib.import_module", return_value=mod):
            with self.assertRaises(TypeError):
                load_external_tool_plugins(["bad_mod"])

    def test_non_plugin_item_raises(self) -> None:
        mod = types.ModuleType("bad_mod")
        mod.get_openplanter_tools = lambda: [object()]  # type: ignore[attr-defined]
        with patch("agent.plugin_loader.importlib.import_module", return_value=mod):
            with self.assertRaises(TypeError):
                load_external_tool_plugins(["bad_mod"])

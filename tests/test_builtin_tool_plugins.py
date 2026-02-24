from __future__ import annotations

import unittest

from agent.builtin_tool_plugins import get_builtin_tool_plugins
from agent.tool_defs import TOOL_DEFINITIONS


class BuiltinToolPluginsTests(unittest.TestCase):
    def test_builtin_plugin_count_and_names(self) -> None:
        plugins = get_builtin_tool_plugins()
        names = [p.definition.name for p in plugins]
        self.assertEqual(len(plugins), 20)
        expected = {
            "think",
            "list_files",
            "search_files",
            "repo_map",
            "web_search",
            "fetch_url",
            "read_file",
            "read_image",
            "write_file",
            "apply_patch",
            "edit_file",
            "hashline_edit",
            "run_shell",
            "run_shell_bg",
            "check_shell_bg",
            "kill_shell_bg",
            "subtask",
            "execute",
            "list_artifacts",
            "read_artifact",
        }
        self.assertEqual(set(names), expected)

    def test_builtin_plugins_have_unique_names(self) -> None:
        names = [p.definition.name for p in get_builtin_tool_plugins()]
        self.assertEqual(len(names), len(set(names)))

    def test_builtin_plugins_match_tool_definitions_metadata(self) -> None:
        by_name = {d["name"]: d for d in TOOL_DEFINITIONS}
        for plugin in get_builtin_tool_plugins():
            defn = plugin.definition
            self.assertIn(defn.name, by_name)
            source = by_name[defn.name]
            self.assertEqual(defn.description, source["description"])
            self.assertEqual(defn.parameters, source["parameters"])

    def test_get_builtin_tool_plugins_returns_copy(self) -> None:
        a = get_builtin_tool_plugins()
        b = get_builtin_tool_plugins()
        self.assertIsNot(a, b)
        a.pop()
        self.assertEqual(len(b), 20)
        self.assertEqual(len(get_builtin_tool_plugins()), 20)

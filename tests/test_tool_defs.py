"""Tests for tool_defs.py: schema definitions and provider conversions."""
from __future__ import annotations

import unittest

from agent.tool_defs import (
    TOOL_DEFINITIONS,
    _make_strict_parameters,
    get_tool_definitions,
    to_anthropic_tools,
    to_openai_tools,
)


class ToolDefinitionsTests(unittest.TestCase):
    """Verify the canonical tool definitions list."""

    def test_all_tools_have_required_keys(self) -> None:
        for d in TOOL_DEFINITIONS:
            self.assertIn("name", d)
            self.assertIn("description", d)
            self.assertIn("parameters", d)
            params = d["parameters"]
            self.assertEqual(params["type"], "object")
            self.assertIn("properties", params)
            self.assertIn("required", params)

    def test_tool_count(self) -> None:
        names = [d["name"] for d in TOOL_DEFINITIONS]
        self.assertEqual(len(names), len(TOOL_DEFINITIONS))
        expected = {
            "list_files", "search_files", "repo_map", "web_search", "fetch_url",
            "read_file", "read_image", "write_file", "apply_patch", "edit_file",
            "hashline_edit",
            "run_shell", "run_shell_bg", "check_shell_bg", "kill_shell_bg",
            "think", "subtask", "execute",
            "list_artifacts", "read_artifact",
        }
        self.assertEqual(set(names), expected)

    def test_no_duplicate_names(self) -> None:
        names = [d["name"] for d in TOOL_DEFINITIONS]
        self.assertEqual(len(names), len(set(names)))


class GetToolDefinitionsTests(unittest.TestCase):
    """Tests for get_tool_definitions() filtering."""

    def test_include_subtask_true(self) -> None:
        defs = get_tool_definitions(include_subtask=True)
        names = [d["name"] for d in defs]
        self.assertIn("subtask", names)
        self.assertNotIn("execute", names)
        self.assertNotIn("list_artifacts", names)
        self.assertNotIn("read_artifact", names)
        # Excludes execute, list_artifacts, read_artifact (3).
        self.assertEqual(len(defs), len(TOOL_DEFINITIONS) - 3)

    def test_include_subtask_false(self) -> None:
        defs = get_tool_definitions(include_subtask=False)
        names = [d["name"] for d in defs]
        self.assertNotIn("subtask", names)
        self.assertNotIn("execute", names)
        self.assertNotIn("list_artifacts", names)
        self.assertNotIn("read_artifact", names)
        # Excludes subtask, execute, list_artifacts, read_artifact (4).
        self.assertEqual(len(defs), len(TOOL_DEFINITIONS) - 4)

    def test_default_includes_subtask(self) -> None:
        defs = get_tool_definitions()
        names = [d["name"] for d in defs]
        self.assertIn("subtask", names)


class MakeStrictParametersTests(unittest.TestCase):
    """Tests for _make_strict_parameters()."""

    def test_optional_property_becomes_nullable(self) -> None:
        params = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "A name"},
            },
            "required": [],
            "additionalProperties": False,
        }
        strict = _make_strict_parameters(params)
        self.assertIn("name", strict["required"])
        prop = strict["properties"]["name"]
        self.assertIn("anyOf", prop)
        types = [a["type"] for a in prop["anyOf"]]
        self.assertIn("string", types)
        self.assertIn("null", types)
        self.assertEqual(prop["description"], "A name")

    def test_required_property_unchanged(self) -> None:
        params = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
            "additionalProperties": False,
        }
        strict = _make_strict_parameters(params)
        self.assertIn("query", strict["required"])
        prop = strict["properties"]["query"]
        # Already required, should NOT be wrapped in anyOf
        self.assertEqual(prop["type"], "string")
        self.assertNotIn("anyOf", prop)

    def test_array_property_items_preserved(self) -> None:
        """The 'items' field on array properties should be carried into the anyOf."""
        params = {
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "URL list",
                },
            },
            "required": [],
            "additionalProperties": False,
        }
        strict = _make_strict_parameters(params)
        prop = strict["properties"]["urls"]
        self.assertIn("anyOf", prop)
        array_variant = [a for a in prop["anyOf"] if a.get("type") == "array"][0]
        self.assertEqual(array_variant["items"], {"type": "string"})

    def test_mixed_required_and_optional(self) -> None:
        params = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Required query"},
                "glob": {"type": "string", "description": "Optional glob"},
            },
            "required": ["query"],
            "additionalProperties": False,
        }
        strict = _make_strict_parameters(params)
        # Both should be in required
        self.assertIn("query", strict["required"])
        self.assertIn("glob", strict["required"])
        # query should NOT have anyOf
        self.assertEqual(strict["properties"]["query"]["type"], "string")
        # glob SHOULD have anyOf
        self.assertIn("anyOf", strict["properties"]["glob"])

    def test_empty_properties(self) -> None:
        params = {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        }
        strict = _make_strict_parameters(params)
        self.assertEqual(strict["required"], [])
        self.assertEqual(strict["properties"], {})

    def test_original_not_mutated(self) -> None:
        params = {
            "type": "object",
            "properties": {
                "glob": {"type": "string", "description": "Pattern"},
            },
            "required": [],
            "additionalProperties": False,
        }
        _make_strict_parameters(params)
        # Original should be untouched
        self.assertEqual(params["properties"]["glob"]["type"], "string")
        self.assertEqual(params["required"], [])


class ToOpenAIToolsTests(unittest.TestCase):
    """Tests for to_openai_tools()."""

    def test_strict_mode_default(self) -> None:
        tools = to_openai_tools()
        self.assertEqual(len(tools), len(TOOL_DEFINITIONS))
        for t in tools:
            self.assertEqual(t["type"], "function")
            self.assertIn("name", t["function"])
            self.assertIn("description", t["function"])
            self.assertIn("parameters", t["function"])
            self.assertTrue(t["function"]["strict"])

    def test_non_strict_mode(self) -> None:
        tools = to_openai_tools(strict=False)
        for t in tools:
            self.assertNotIn("strict", t["function"])

    def test_strict_mode_all_properties_required(self) -> None:
        """In strict mode, every property must appear in the required array."""
        tools = to_openai_tools(strict=True)
        for t in tools:
            params = t["function"]["parameters"]
            prop_keys = set(params.get("properties", {}).keys())
            required = set(params.get("required", []))
            self.assertEqual(prop_keys, required, f"Tool {t['function']['name']}")

    def test_custom_defs(self) -> None:
        custom = [
            {
                "name": "my_tool",
                "description": "A custom tool",
                "parameters": {
                    "type": "object",
                    "properties": {"x": {"type": "integer", "description": "A number"}},
                    "required": ["x"],
                    "additionalProperties": False,
                },
            }
        ]
        tools = to_openai_tools(defs=custom)
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["function"]["name"], "my_tool")

    def test_empty_defs(self) -> None:
        tools = to_openai_tools(defs=[])
        self.assertEqual(tools, [])


class ToAnthropicToolsTests(unittest.TestCase):
    """Tests for to_anthropic_tools()."""

    def test_default_tools(self) -> None:
        tools = to_anthropic_tools()
        self.assertEqual(len(tools), len(TOOL_DEFINITIONS))
        for t in tools:
            self.assertIn("name", t)
            self.assertIn("description", t)
            self.assertIn("input_schema", t)
            # Should NOT have OpenAI-style keys
            self.assertNotIn("type", t)
            self.assertNotIn("function", t)

    def test_custom_defs(self) -> None:
        custom = [
            {
                "name": "my_tool",
                "description": "Custom",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
            }
        ]
        tools = to_anthropic_tools(defs=custom)
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], "my_tool")
        self.assertEqual(tools[0]["input_schema"]["type"], "object")

    def test_empty_defs(self) -> None:
        tools = to_anthropic_tools(defs=[])
        self.assertEqual(tools, [])


if __name__ == "__main__":
    unittest.main()

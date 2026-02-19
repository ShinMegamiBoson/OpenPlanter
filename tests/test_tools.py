from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.tools import ToolError, WorkspaceTools


class ToolTests(unittest.TestCase):
    def test_write_read_in_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tools = WorkspaceTools(root=root)
            write_msg = tools.write_file("a/b/test.txt", "abc")
            read_msg = tools.read_file("a/b/test.txt")
            self.assertIn("Wrote", write_msg)
            self.assertIn("abc", read_msg)

    def test_write_overwrite_blocked_until_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tools = WorkspaceTools(root=root)
            (root / "guard.txt").write_text("v1", encoding="utf-8")
            blocked = tools.write_file("guard.txt", "v2")
            self.assertIn("BLOCKED", blocked)
            tools.read_file("guard.txt")
            allowed = tools.write_file("guard.txt", "v2")
            self.assertIn("Wrote", allowed)
            self.assertEqual((root / "guard.txt").read_text(encoding="utf-8"), "v2")

    def test_path_escape_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tools = WorkspaceTools(root=root)
            with self.assertRaises(ToolError):
                tools.write_file("../outside.txt", "x")

    def test_list_and_search_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tools = WorkspaceTools(root=root)
            tools.write_file("alpha.txt", "hello world\n")
            tools.write_file("beta.txt", "another line\n")

            listed = tools.list_files()
            self.assertIn("alpha.txt", listed)
            self.assertIn("beta.txt", listed)

            matches = tools.search_files("world")
            self.assertIn("alpha.txt:1:hello world", matches)

    def test_run_shell(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tools = WorkspaceTools(root=root)
            out = tools.run_shell("printf 'ok'")
            self.assertIn("[exit_code=0]", out)
            self.assertIn("ok", out)

    def test_web_search_with_mocked_exa_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tools = WorkspaceTools(root=root, exa_api_key="exa-key")
            mocked = {
                "results": [
                    {
                        "url": "https://example.com",
                        "title": "Example",
                        "highlight": "Snippet",
                        "text": "Long text body",
                    }
                ]
            }
            with patch.object(WorkspaceTools, "_exa_request", return_value=mocked):
                raw = tools.web_search("test query", num_results=3, include_text=True)
            parsed = json.loads(raw)
            self.assertEqual(parsed["query"], "test query")
            self.assertEqual(parsed["total"], 1)
            self.assertEqual(parsed["results"][0]["url"], "https://example.com")
            self.assertIn("text", parsed["results"][0])

    def test_fetch_url_with_mocked_exa_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tools = WorkspaceTools(root=root, exa_api_key="exa-key")
            mocked = {
                "results": [
                    {
                        "url": "https://example.com",
                        "title": "Example",
                        "text": "Page body",
                    }
                ]
            }
            with patch.object(WorkspaceTools, "_exa_request", return_value=mocked):
                raw = tools.fetch_url(["https://example.com"])
            parsed = json.loads(raw)
            self.assertEqual(parsed["total"], 1)
            self.assertEqual(parsed["pages"][0]["url"], "https://example.com")
            self.assertEqual(parsed["pages"][0]["text"], "Page body")

    def test_web_search_without_exa_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tools = WorkspaceTools(root=root, exa_api_key=None)
            out = tools.web_search("test")
            self.assertIn("EXA_API_KEY not configured", out)

    def test_repo_map_python_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tools = WorkspaceTools(root=root)
            (root / "mod.py").write_text(
                "class Greeter:\n"
                "    def hi(self):\n"
                "        return 'hi'\n\n"
                "def add(a, b):\n"
                "    return a + b\n",
                encoding="utf-8",
            )
            raw = tools.repo_map(glob="*.py", max_files=10)
            parsed = json.loads(raw)
            self.assertEqual(parsed["total"], 1)
            symbols = parsed["files"][0]["symbols"]
            names = [s["name"] for s in symbols]
            self.assertIn("Greeter", names)
            self.assertIn("Greeter.hi", names)
            self.assertIn("add", names)


    def test_read_file_line_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tools = WorkspaceTools(root=root)
            tools.write_file("nums.txt", "alpha\nbeta\ngamma\n")
            result = tools.read_file("nums.txt", hashline=False)
            self.assertIn("1|alpha", result)
            self.assertIn("2|beta", result)
            self.assertIn("3|gamma", result)

    def test_read_file_hashline_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tools = WorkspaceTools(root=root)
            tools.write_file("hash.txt", "hello\nworld\n")
            result = tools.read_file("hash.txt", hashline=True)
            # Should have LINE:XX| format
            import re
            lines = result.strip().splitlines()
            # First line is the header
            self.assertTrue(lines[0].startswith("# "))
            # Content lines should match N:XX|content pattern
            for line in lines[1:]:
                self.assertRegex(line, r"^\d+:[0-9a-f]{2}\|")

    def test_edit_file_basic(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tools = WorkspaceTools(root=root)
            tools.write_file("edit_me.txt", "foo bar baz\n")
            result = tools.edit_file("edit_me.txt", "bar", "BAR")
            self.assertIn("Edited", result)
            content = Path(tmpdir, "edit_me.txt").read_text()
            self.assertEqual(content, "foo BAR baz\n")

    def test_edit_file_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tools = WorkspaceTools(root=root)
            result = tools.edit_file("no_such_file.txt", "old", "new")
            self.assertIn("File not found", result)

    def test_edit_file_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tools = WorkspaceTools(root=root)
            tools.write_file("dup.txt", "aaa\naaa\n")
            result = tools.edit_file("dup.txt", "aaa", "bbb")
            self.assertIn("appears 2 times", result)

    def test_edit_file_fuzzy_whitespace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tools = WorkspaceTools(root=root)
            tools.write_file("ws.txt", "  hello   world\nother line\n")
            result = tools.edit_file("ws.txt", "hello world", "REPLACED")
            self.assertIn("Edited", result)
            content = Path(tmpdir, "ws.txt").read_text()
            self.assertIn("REPLACED", content)


    def test_hashline_edit_set_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tools = WorkspaceTools(root=root)
            tools.write_file("h.txt", "aaa\nbbb\nccc\n")
            # Read hashline to get anchors
            hl = tools.read_file("h.txt", hashline=True)
            # Parse line 2 anchor (N:HH)
            import re
            anchors = re.findall(r"(\d+:[0-9a-f]{2})\|", hl)
            anchor_2 = anchors[1]  # second line
            result = tools.hashline_edit("h.txt", [{"set_line": anchor_2, "content": "BBB"}])
            self.assertIn("Edited", result)
            content = Path(tmpdir, "h.txt").read_text()
            self.assertEqual(content, "aaa\nBBB\nccc\n")

    def test_hashline_edit_replace_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tools = WorkspaceTools(root=root)
            tools.write_file("h.txt", "line1\nline2\nline3\nline4\n")
            hl = tools.read_file("h.txt", hashline=True)
            import re
            anchors = re.findall(r"(\d+:[0-9a-f]{2})\|", hl)
            result = tools.hashline_edit("h.txt", [{
                "replace_lines": {"start": anchors[1], "end": anchors[2]},
                "content": "NEW2\nNEW3",
            }])
            self.assertIn("Edited", result)
            content = Path(tmpdir, "h.txt").read_text()
            self.assertEqual(content, "line1\nNEW2\nNEW3\nline4\n")

    def test_hashline_edit_insert_after(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tools = WorkspaceTools(root=root)
            tools.write_file("h.txt", "aaa\nccc\n")
            hl = tools.read_file("h.txt", hashline=True)
            import re
            anchors = re.findall(r"(\d+:[0-9a-f]{2})\|", hl)
            result = tools.hashline_edit("h.txt", [{
                "insert_after": anchors[0],
                "content": "bbb",
            }])
            self.assertIn("Edited", result)
            content = Path(tmpdir, "h.txt").read_text()
            self.assertEqual(content, "aaa\nbbb\nccc\n")

    def test_hashline_edit_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tools = WorkspaceTools(root=root)
            tools.write_file("h.txt", "aaa\nbbb\n")
            result = tools.hashline_edit("h.txt", [{"set_line": "1:ff", "content": "x"}])
            self.assertIn("Hash mismatch", result)
            self.assertIn("Current context", result)

    def test_hashline_edit_strips_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tools = WorkspaceTools(root=root)
            tools.write_file("h.txt", "old\n")
            hl = tools.read_file("h.txt", hashline=True)
            import re
            anchors = re.findall(r"(\d+:[0-9a-f]{2})\|", hl)
            # Content with hashline prefix should be stripped
            result = tools.hashline_edit("h.txt", [{
                "set_line": anchors[0],
                "content": "1:ab|new_content",
            }])
            self.assertIn("Edited", result)
            content = Path(tmpdir, "h.txt").read_text()
            self.assertEqual(content, "new_content\n")

    def test_hashline_edit_file_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tools = WorkspaceTools(root=root)
            result = tools.hashline_edit("no_such_file.txt", [{"set_line": "1:00", "content": "x"}])
            self.assertIn("File not found", result)

    def test_hashline_edit_whitespace_invariant_hash(self) -> None:
        from agent.tools import _line_hash
        self.assertEqual(_line_hash("hello"), _line_hash("  hello  "))
        self.assertEqual(_line_hash("a b c"), _line_hash("a  b  c"))
        self.assertEqual(_line_hash("  foo  bar  "), _line_hash("foobar"))


if __name__ == "__main__":
    unittest.main()

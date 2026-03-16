from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.tools import ToolError, WorkspaceTools


class ToolsComplexTests(unittest.TestCase):
    # 1
    def test_shell_timeout_returns_timeout_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools = WorkspaceTools(root=Path(tmpdir), command_timeout_sec=1)
            result = tools.run_shell("sleep 10")
            self.assertIn("timeout after", result)

    def test_shell_policy_blocks_heredoc(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools = WorkspaceTools(root=Path(tmpdir))
            result = tools.run_shell("cat << EOF\nhello\nEOF")
            self.assertIn("BLOCKED", result)

    def test_shell_policy_blocks_interactive_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools = WorkspaceTools(root=Path(tmpdir))
            result = tools.run_shell("vim test.txt")
            self.assertIn("BLOCKED", result)

    # 2
    def test_shell_output_clipping(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools = WorkspaceTools(
                root=Path(tmpdir), max_shell_output_chars=50
            )
            result = tools.run_shell("printf 'x%.0s' {1..200}")
            self.assertIn("truncated", result)

    # 3
    def test_read_file_clipping(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tools = WorkspaceTools(root=root, max_file_chars=100)
            big_file = root / "big.txt"
            big_file.write_text("A" * 50000, encoding="utf-8")
            result = tools.read_file("big.txt")
            self.assertIn("truncated", result)

    # 4
    def test_read_nonexistent_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools = WorkspaceTools(root=Path(tmpdir))
            result = tools.read_file("no_such_file.txt")
            self.assertIn("File not found", result)

    # 5
    def test_read_directory_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            subdir = root / "somedir"
            subdir.mkdir()
            tools = WorkspaceTools(root=root)
            result = tools.read_file("somedir")
            self.assertIn("Path is a directory", result)

    # 6
    def test_list_files_clipping(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tools = WorkspaceTools(root=root, max_files_listed=3)
            for i in range(10):
                (root / f"file_{i:02d}.txt").write_text(
                    f"content {i}", encoding="utf-8"
                )
            result = tools.list_files()
            self.assertIn("omitted", result)

    # 7
    def test_search_files_empty_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools = WorkspaceTools(root=Path(tmpdir))
            result = tools.search_files("")
            self.assertIn("query cannot be empty", result)

    # 8
    def test_search_files_no_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "sample.txt").write_text("hello world", encoding="utf-8")
            tools = WorkspaceTools(root=root)
            result = tools.search_files("zzzzz_no_match_zzzzz")
            self.assertEqual(result, "(no matches)")

    # 9
    def test_resolve_path_absolute_within_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            tools = WorkspaceTools(root=root)
            abs_path = str(root / "subdir" / "file.txt")
            resolved = tools._resolve_path(abs_path)
            self.assertEqual(resolved, root / "subdir" / "file.txt")

    # 10
    def test_resolve_path_escape_via_symlink_or_dotdot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools = WorkspaceTools(root=Path(tmpdir))
            with self.assertRaises(ToolError):
                tools._resolve_path("../../etc/passwd")
            with self.assertRaises(ToolError):
                tools._resolve_path("/tmp/outside")

    # 11
    def test_web_search_clamps_num_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools = WorkspaceTools(
                root=Path(tmpdir), exa_api_key="test-key"
            )
            mock_response = {"results": []}
            with patch.object(
                WorkspaceTools, "_exa_request", return_value=mock_response
            ) as mock_exa:
                tools.web_search("test query", num_results=50)
                mock_exa.assert_called_once()
                payload = mock_exa.call_args[0][1]
                self.assertEqual(payload["numResults"], 20)

    # 12
    def test_fetch_url_non_list_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools = WorkspaceTools(root=Path(tmpdir))
            result = tools.fetch_url("not a list")  # type: ignore[arg-type]
            self.assertIn("requires a list", result)

    # 13
    def test_fetch_url_empty_urls_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools = WorkspaceTools(root=Path(tmpdir))
            result = tools.fetch_url([])
            self.assertIn("requires at least one valid URL", result)

    # 14
    def test_fetch_url_caps_at_10(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools = WorkspaceTools(
                root=Path(tmpdir), exa_api_key="test-key"
            )
            mock_response = {"results": []}
            urls = [f"https://example.com/{i}" for i in range(15)]
            with patch.object(
                WorkspaceTools, "_exa_request", return_value=mock_response
            ) as mock_exa:
                tools.fetch_url(urls)
                mock_exa.assert_called_once()
                payload = mock_exa.call_args[0][1]
                self.assertEqual(len(payload["ids"]), 10)

    # 15
    def test_exa_request_no_key_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools = WorkspaceTools(root=Path(tmpdir), exa_api_key=None)
            with self.assertRaises(ToolError) as ctx:
                tools._exa_request("/search", {"query": "test"})
            self.assertIn("EXA_API_KEY not configured", str(ctx.exception))

    # 16
    def test_write_file_creates_nested_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tools = WorkspaceTools(root=root)
            result = tools.write_file("a/b/c/d.txt", "nested content")
            self.assertIn("Wrote", result)
            written = (root / "a" / "b" / "c" / "d.txt").read_text(
                encoding="utf-8"
            )
            self.assertEqual(written, "nested content")


if __name__ == "__main__":
    unittest.main()

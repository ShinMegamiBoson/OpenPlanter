from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.patching import (
    ApplyReport,
    PatchApplyError,
    _find_subsequence,
    _normalize_ws,
    apply_agent_patch,
    parse_agent_patch,
)


class PatchingComplexTests(unittest.TestCase):
    # ------------------------------------------------------------------
    # 1. Multi-chunk update
    # ------------------------------------------------------------------
    def test_multi_chunk_update(self) -> None:
        """File with 10+ lines, patch with 2 separate @@ hunks updating
        different sections. Assert both hunks applied correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            def resolve_path(p: str) -> Path:

                return Path(tmpdir) / p
            file_path = resolve_path("multi.txt")
            original_lines = [f"line{i}" for i in range(1, 13)]
            file_path.write_text("\n".join(original_lines) + "\n", encoding="utf-8")

            patch = """\
*** Begin Patch
*** Update File: multi.txt
@@
 line2
-line3
+LINE3_REPLACED
 line4
@@
 line10
-line11
+LINE11_REPLACED
 line12
*** End Patch"""
            report = apply_agent_patch(patch, resolve_path)
            result = file_path.read_text(encoding="utf-8")

            self.assertIn("multi.txt", report.updated)
            self.assertIn("LINE3_REPLACED", result)
            self.assertIn("LINE11_REPLACED", result)
            self.assertNotIn("line3\n", result)
            self.assertNotIn("line11\n", result)

    # ------------------------------------------------------------------
    # 2. Chunk retry from zero
    # ------------------------------------------------------------------
    def test_chunk_retry_from_zero(self) -> None:
        """Arrange chunk old_seq that appears BEFORE the cursor position.
        Verify it still finds it by retrying from 0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            def resolve_path(p: str) -> Path:

                return Path(tmpdir) / p
            file_path = resolve_path("retry.txt")
            # Lines: AAA, BBB, CCC, DDD, EEE
            file_path.write_text("AAA\nBBB\nCCC\nDDD\nEEE\n", encoding="utf-8")

            # First hunk matches near end (DDD->DDD_NEW), pushing cursor past
            # the location of the second hunk's target (AAA->AAA_NEW at line 0).
            # The second hunk must retry from 0 to find its match.
            patch = """\
*** Begin Patch
*** Update File: retry.txt
@@
 CCC
-DDD
+DDD_NEW
 EEE
@@
 AAA
-BBB
+BBB_NEW
 CCC
*** End Patch"""
            apply_agent_patch(patch, resolve_path)
            result = file_path.read_text(encoding="utf-8")
            self.assertIn("DDD_NEW", result)
            self.assertIn("BBB_NEW", result)

    # ------------------------------------------------------------------
    # 3. Chunk not found raises
    # ------------------------------------------------------------------
    def test_chunk_not_found_raises(self) -> None:
        """Patch with old_seq that doesn't match any lines in file.
        Assert PatchApplyError with 'could not locate'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            def resolve_path(p: str) -> Path:

                return Path(tmpdir) / p
            file_path = resolve_path("nomatch.txt")
            file_path.write_text("alpha\nbeta\n", encoding="utf-8")

            patch = """\
*** Begin Patch
*** Update File: nomatch.txt
@@
 DOES_NOT_EXIST
-OLD
+NEW
*** End Patch"""
            with self.assertRaises(PatchApplyError) as ctx:
                apply_agent_patch(patch, resolve_path)
            self.assertIn("could not locate", str(ctx.exception))

    # ------------------------------------------------------------------
    # 4. Add existing file raises
    # ------------------------------------------------------------------
    def test_add_existing_file_raises(self) -> None:
        """Try to add a file that already exists.
        Assert PatchApplyError with 'cannot add existing file'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            def resolve_path(p: str) -> Path:

                return Path(tmpdir) / p
            file_path = resolve_path("exists.txt")
            file_path.write_text("hello\n", encoding="utf-8")

            patch = """\
*** Begin Patch
*** Add File: exists.txt
+new content
*** End Patch"""
            with self.assertRaises(PatchApplyError) as ctx:
                apply_agent_patch(patch, resolve_path)
            self.assertIn("cannot add existing file", str(ctx.exception))

    # ------------------------------------------------------------------
    # 5. Delete missing file raises
    # ------------------------------------------------------------------
    def test_delete_missing_file_raises(self) -> None:
        """Try to delete a file that doesn't exist.
        Assert PatchApplyError with 'cannot delete missing file'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            def resolve_path(p: str) -> Path:

                return Path(tmpdir) / p

            patch = """\
*** Begin Patch
*** Delete File: ghost.txt
*** End Patch"""
            with self.assertRaises(PatchApplyError) as ctx:
                apply_agent_patch(patch, resolve_path)
            self.assertIn("cannot delete missing file", str(ctx.exception))

    # ------------------------------------------------------------------
    # 6. Delete directory raises
    # ------------------------------------------------------------------
    def test_delete_directory_raises(self) -> None:
        """Try to delete a path that is a directory.
        Assert PatchApplyError with 'cannot delete directory'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            def resolve_path(p: str) -> Path:

                return Path(tmpdir) / p
            dir_path = resolve_path("mydir")
            dir_path.mkdir()

            patch = """\
*** Begin Patch
*** Delete File: mydir
*** End Patch"""
            with self.assertRaises(PatchApplyError) as ctx:
                apply_agent_patch(patch, resolve_path)
            self.assertIn("cannot delete directory", str(ctx.exception))

    # ------------------------------------------------------------------
    # 7. Update missing file raises
    # ------------------------------------------------------------------
    def test_update_missing_file_raises(self) -> None:
        """Try to update a file that doesn't exist. Assert PatchApplyError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            def resolve_path(p: str) -> Path:

                return Path(tmpdir) / p

            patch = """\
*** Begin Patch
*** Update File: nope.txt
@@
 old
-stuff
+new
*** End Patch"""
            with self.assertRaises(PatchApplyError):
                apply_agent_patch(patch, resolve_path)

    # ------------------------------------------------------------------
    # 8. Parse empty patch raises
    # ------------------------------------------------------------------
    def test_parse_empty_patch_raises(self) -> None:
        """Empty string. Assert PatchApplyError."""
        with self.assertRaises(PatchApplyError):
            parse_agent_patch("")

    # ------------------------------------------------------------------
    # 9. Parse no operations raises
    # ------------------------------------------------------------------
    def test_parse_no_operations_raises(self) -> None:
        """Valid begin/end but no operations between them.
        Assert PatchApplyError with 'no operations'."""
        patch = """\
*** Begin Patch
*** End Patch"""
        with self.assertRaises(PatchApplyError) as ctx:
            parse_agent_patch(patch)
        self.assertIn("no operations", str(ctx.exception))

    # ------------------------------------------------------------------
    # 10. Add file non-plus line raises
    # ------------------------------------------------------------------
    def test_add_file_non_plus_line_raises(self) -> None:
        """Add file block with a line that doesn't start with '+'.
        Assert PatchApplyError."""
        patch = """\
*** Begin Patch
*** Add File: bad.txt
+good line
 bad line without plus
*** End Patch"""
        with self.assertRaises(PatchApplyError):
            parse_agent_patch(patch)

    # ------------------------------------------------------------------
    # 11. Trailing newline preserved
    # ------------------------------------------------------------------
    def test_trailing_newline_preserved(self) -> None:
        """File originally has trailing newline. After update, verify
        trailing newline is preserved."""
        with tempfile.TemporaryDirectory() as tmpdir:
            def resolve_path(p: str) -> Path:

                return Path(tmpdir) / p
            file_path = resolve_path("trailing.txt")
            file_path.write_text("aaa\nbbb\nccc\n", encoding="utf-8")

            patch = """\
*** Begin Patch
*** Update File: trailing.txt
@@
 aaa
-bbb
+BBB
 ccc
*** End Patch"""
            apply_agent_patch(patch, resolve_path)
            result = file_path.read_text(encoding="utf-8")
            self.assertTrue(result.endswith("\n"), "Trailing newline should be preserved")
            self.assertEqual(result, "aaa\nBBB\nccc\n")

    # ------------------------------------------------------------------
    # 12. Trailing newline absent preserved
    # ------------------------------------------------------------------
    def test_trailing_newline_absent_preserved(self) -> None:
        """File originally has NO trailing newline. After update, verify
        no trailing newline added."""
        with tempfile.TemporaryDirectory() as tmpdir:
            def resolve_path(p: str) -> Path:
                return Path(tmpdir) / p
            file_path = resolve_path("notrailing.txt")
            file_path.write_text("aaa\nbbb\nccc", encoding="utf-8")

            patch = """\
*** Begin Patch
*** Update File: notrailing.txt
@@
 aaa
-bbb
+BBB
 ccc
*** End Patch"""
            apply_agent_patch(patch, resolve_path)
            result = file_path.read_text(encoding="utf-8")
            self.assertFalse(result.endswith("\n"), "No trailing newline should be added")
            self.assertEqual(result, "aaa\nBBB\nccc")

    # ------------------------------------------------------------------
    # 13. ApplyReport render all types
    # ------------------------------------------------------------------
    def test_apply_report_render_all_types(self) -> None:
        """Create ApplyReport with added, updated, deleted, moved entries.
        Verify render() output contains all sections."""
        report = ApplyReport(
            added=["new_file.py"],
            updated=["changed.py"],
            deleted=["old.py"],
            moved=["src/a.py -> dst/a.py"],
        )
        rendered = report.render()
        self.assertIn("Patch applied successfully", rendered)
        self.assertIn("Added:", rendered)
        self.assertIn("- new_file.py", rendered)
        self.assertIn("Updated:", rendered)
        self.assertIn("- changed.py", rendered)
        self.assertIn("Deleted:", rendered)
        self.assertIn("- old.py", rendered)
        self.assertIn("Moved:", rendered)
        self.assertIn("- src/a.py -> dst/a.py", rendered)

    # ------------------------------------------------------------------
    # 14. _find_subsequence empty needle
    # ------------------------------------------------------------------
    def test_find_subsequence_empty_needle(self) -> None:
        """Call _find_subsequence with empty needle. Should return
        start_idx (or clamped value)."""
        haystack = ["a", "b", "c"]
        # Empty needle at start_idx 0 -> 0
        self.assertEqual(_find_subsequence(haystack, [], 0), 0)
        # Empty needle at start_idx 2 -> 2
        self.assertEqual(_find_subsequence(haystack, [], 2), 2)
        # Empty needle beyond end -> clamped to len(haystack)
        self.assertEqual(_find_subsequence(haystack, [], 100), len(haystack))
        # Empty needle with negative start -> clamped to 0
        self.assertEqual(_find_subsequence(haystack, [], -5), 0)

    # ------------------------------------------------------------------
    # 15. Move creates directory
    # ------------------------------------------------------------------
    def test_move_creates_directory(self) -> None:
        """Update file with Move to a path whose parent doesn't exist yet.
        Verify parent dir is created and file is moved."""
        with tempfile.TemporaryDirectory() as tmpdir:
            def resolve_path(p: str) -> Path:
                return Path(tmpdir) / p
            source = resolve_path("original.txt")
            source.write_text("foo\nbar\nbaz\n", encoding="utf-8")

            patch = """\
*** Begin Patch
*** Update File: original.txt
*** Move to: deep/nested/dir/moved.txt
@@
 foo
-bar
+BAR
 baz
*** End Patch"""
            report = apply_agent_patch(patch, resolve_path)
            dest = resolve_path("deep/nested/dir/moved.txt")

            self.assertFalse(source.exists(), "Original file should be removed")
            self.assertTrue(dest.exists(), "Destination file should exist")
            self.assertTrue(dest.parent.is_dir(), "Parent directory should be created")
            self.assertEqual(dest.read_text(encoding="utf-8"), "foo\nBAR\nbaz\n")
            self.assertIn("original.txt -> deep/nested/dir/moved.txt", report.moved[0])
            self.assertIn("deep/nested/dir/moved.txt", report.updated)


    # ------------------------------------------------------------------
    # 16. Fuzzy whitespace match
    # ------------------------------------------------------------------
    def test_fuzzy_whitespace_match(self) -> None:
        """File has indented lines, patch context collapses whitespace.
        Patch should still apply via fuzzy fallback."""
        with tempfile.TemporaryDirectory() as tmpdir:
            def resolve_path(p: str) -> Path:
                return Path(tmpdir) / p
            file_path = resolve_path("fuzzy.txt")
            file_path.write_text("    indented  line\nnormal line\n", encoding="utf-8")

            patch = """\
*** Begin Patch
*** Update File: fuzzy.txt
@@
 indented line
-normal line
+replaced line
*** End Patch"""
            report = apply_agent_patch(patch, resolve_path)
            result = file_path.read_text(encoding="utf-8")
            self.assertIn("replaced line", result)
            self.assertIn("fuzzy.txt", report.updated)

    # ------------------------------------------------------------------
    # 17. Fuzzy match fallback order (exact preferred)
    # ------------------------------------------------------------------
    def test_fuzzy_match_fallback_order(self) -> None:
        """Exact match is preferred over fuzzy when both exist."""
        haystack = ["  hello  world", "hello world", "other"]
        needle = ["hello world"]
        # Exact match is at index 1
        idx = _find_subsequence(haystack, needle, 0)
        self.assertEqual(idx, 1)

    # ------------------------------------------------------------------
    # 18. _normalize_ws helper
    # ------------------------------------------------------------------
    def test_normalize_ws_helper(self) -> None:
        self.assertEqual(_normalize_ws("  hello   world  "), "hello world")
        self.assertEqual(_normalize_ws("\t\ttabs\there\t"), "tabs here")
        self.assertEqual(_normalize_ws(""), "")
        self.assertEqual(_normalize_ws("   "), "")
        self.assertEqual(_normalize_ws("single"), "single")


if __name__ == "__main__":
    unittest.main()

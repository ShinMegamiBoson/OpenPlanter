"""Tests for agent.demo — DemoCensor and DemoRenderHook."""

from __future__ import annotations

import unittest
from pathlib import Path

from agent.demo import DemoCensor, DemoRenderHook


class DemoCensorPathTests(unittest.TestCase):
    """Workspace path censoring: distinguishing parts censored, generic parts
    and the project name preserved."""

    def test_username_censored(self) -> None:
        ws = Path("/Users/johndoe/Documents/MyProject")
        c = DemoCensor(ws)
        text = "Workspace: /Users/johndoe/Documents/MyProject"
        result = c.censor_text(text)
        self.assertNotIn("johndoe", result)
        # Generic parts and project name survive
        self.assertIn("Users", result)
        self.assertIn("Documents", result)
        self.assertIn("MyProject", result)

    def test_multiple_custom_segments_censored(self) -> None:
        ws = Path("/home/alice/secret_org/repos/CoolApp")
        c = DemoCensor(ws)
        text = "/home/alice/secret_org/repos/CoolApp"
        result = c.censor_text(text)
        self.assertNotIn("alice", result)
        self.assertNotIn("secret_org", result)
        self.assertIn("home", result)
        self.assertIn("repos", result)
        self.assertIn("CoolApp", result)

    def test_same_length_path_replacement(self) -> None:
        ws = Path("/Users/bob/Documents/Proj")
        c = DemoCensor(ws)
        text = "path is /Users/bob/Documents/Proj end"
        result = c.censor_text(text)
        # "bob" → 3 block chars
        self.assertIn("\u2588" * 3, result)
        self.assertEqual(len(text), len(result))


class DemoCensorEntityTests(unittest.TestCase):
    """Entity name censoring via regex."""

    def test_multi_word_proper_nouns_censored(self) -> None:
        ws = Path("/tmp/Proj")
        c = DemoCensor(ws)
        text = "Contact John Smith about this."
        result = c.censor_text(text)
        self.assertNotIn("John Smith", result)
        self.assertIn("\u2588" * len("John Smith"), result)

    def test_titled_name_censored(self) -> None:
        ws = Path("/tmp/Proj")
        c = DemoCensor(ws)
        text = "See Dr. Smith for details."
        result = c.censor_text(text)
        self.assertNotIn("Dr. Smith", result)

    def test_three_word_entity_censored(self) -> None:
        ws = Path("/tmp/Proj")
        c = DemoCensor(ws)
        text = "Visit Boston Medical Center today."
        result = c.censor_text(text)
        self.assertNotIn("Boston Medical Center", result)

    def test_same_length_entity_replacement(self) -> None:
        ws = Path("/tmp/Proj")
        c = DemoCensor(ws)
        entity = "John Smith"
        text = f"Hi {entity}!"
        result = c.censor_text(text)
        self.assertEqual(len(text), len(result))


class DemoCensorNewlineTests(unittest.TestCase):
    """Regex must not match across newlines."""

    def test_capitalized_words_across_newline_not_merged(self) -> None:
        ws = Path("/tmp/Proj")
        c = DemoCensor(ws)
        # "Oo" alone on each line shouldn't form a single cross-line match
        text = "end Oo\nOo start"
        result = c.censor_text(text)
        # The newline must survive — lines must not be merged
        self.assertIn("\n", result)
        self.assertEqual(result.count("\n"), text.count("\n"))

    def test_splash_art_preserved(self) -> None:
        from agent.tui import SPLASH_ART
        ws = Path("/Users/testuser/Documents/TestProject")
        c = DemoCensor(ws)
        result = c.censor_text(SPLASH_ART)
        # Only "testuser" should be censored; structure (newlines) must be intact
        self.assertEqual(SPLASH_ART.count("\n"), result.count("\n"))


class DemoCensorWhitelistTests(unittest.TestCase):
    """Whitelisted tech terms should NOT be censored."""

    def test_python_not_censored(self) -> None:
        ws = Path("/tmp/Proj")
        c = DemoCensor(ws)
        # "Machine Learning" matches multi-cap but is whitelisted
        text = "Use Machine Learning techniques."
        result = c.censor_text(text)
        self.assertIn("Machine Learning", result)

    def test_month_not_censored(self) -> None:
        ws = Path("/tmp/Proj")
        c = DemoCensor(ws)
        # Months are 1 word so they wouldn't match multi-cap anyway,
        # but let's verify no false positive with "January February"
        text = "Stack Overflow has answers."
        result = c.censor_text(text)
        self.assertIn("Stack Overflow", result)

    def test_visual_studio_not_censored(self) -> None:
        ws = Path("/tmp/Proj")
        c = DemoCensor(ws)
        text = "Open Visual Studio for editing."
        result = c.censor_text(text)
        self.assertIn("Visual Studio", result)


class DemoCensorEdgeCases(unittest.TestCase):
    """Empty and plain text edge cases."""

    def test_empty_string(self) -> None:
        ws = Path("/tmp/Proj")
        c = DemoCensor(ws)
        self.assertEqual(c.censor_text(""), "")

    def test_no_entities_passes_through(self) -> None:
        ws = Path("/tmp/Proj")
        c = DemoCensor(ws)
        text = "this is all lowercase and has no names"
        self.assertEqual(c.censor_text(text), text)


class DemoCensorRichTextTests(unittest.TestCase):
    """Rich Text style spans survive same-length censoring."""

    def test_rich_text_style_preserved(self) -> None:
        from rich.text import Text

        ws = Path("/Users/alice/Documents/Proj")
        c = DemoCensor(ws)

        t = Text("Path: /Users/alice/Documents/Proj")
        t.stylize("bold", 0, 5)  # "Path:" is bold
        c.censor_rich_text(t)

        self.assertNotIn("alice", t.plain)
        self.assertIn("Users", t.plain)
        # Style span should still exist
        self.assertTrue(any("bold" in str(span) for span in t._spans))

    def test_rich_text_unchanged_when_no_match(self) -> None:
        from rich.text import Text

        ws = Path("/tmp/Proj")
        c = DemoCensor(ws)
        t = Text("nothing to censor here")
        original_plain = t.plain
        c.censor_rich_text(t)
        self.assertEqual(t.plain, original_plain)


class DemoRenderHookTests(unittest.TestCase):
    """DemoRenderHook processes Text, Markdown, and Rule correctly."""

    def _make_hook(self) -> DemoRenderHook:
        ws = Path("/Users/jdoe/Documents/Proj")
        censor = DemoCensor(ws)
        return DemoRenderHook(censor)

    def test_text_censored(self) -> None:
        from rich.text import Text

        hook = self._make_hook()
        t = Text("/Users/jdoe/Documents/Proj")
        results = hook.process_renderables([t])
        self.assertEqual(len(results), 1)
        self.assertNotIn("jdoe", results[0].plain)
        self.assertIn("Users", results[0].plain)

    def test_markdown_censored(self) -> None:
        from rich.markdown import Markdown

        hook = self._make_hook()
        md = Markdown("Hello from /Users/jdoe/Documents/Proj")
        results = hook.process_renderables([md])
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], Markdown)
        self.assertNotIn("jdoe", results[0].markup)

    def test_rule_censored(self) -> None:
        from rich.rule import Rule

        hook = self._make_hook()
        r = Rule(title="Step 1 /Users/jdoe/Documents/Proj")
        results = hook.process_renderables([r])
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], Rule)
        self.assertNotIn("jdoe", results[0].title)

    def test_other_renderable_passes_through(self) -> None:
        hook = self._make_hook()
        obj = {"arbitrary": "object"}
        results = hook.process_renderables([obj])
        self.assertEqual(results, [obj])


if __name__ == "__main__":
    unittest.main()

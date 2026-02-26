"""Tests for agent.wiki_graph — wiki parsing, graph construction, and watcher."""
from __future__ import annotations

import os
import textwrap
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.wiki_graph import (
    CATEGORY_COLORS,
    WikiEntry,
    WikiGraphModel,
    WikiWatcher,
    _build_name_registry,
    _category_slug,
    _draw_line,
    extract_cross_refs,
    match_reference,
    parse_index,
)


# ---------------------------------------------------------------------------
# _category_slug
# ---------------------------------------------------------------------------

class TestCategorySlug:
    def test_simple(self):
        assert _category_slug("Campaign Finance") == "campaign-finance"

    def test_ampersand(self):
        assert _category_slug("Regulatory & Enforcement") == "regulatory-enforcement"

    def test_single_word(self):
        assert _category_slug("Sanctions") == "sanctions"


# ---------------------------------------------------------------------------
# parse_index — baseline wiki directory (committed source, seeded to runtime)
# ---------------------------------------------------------------------------

WIKI_DIR = Path(__file__).resolve().parent.parent / "wiki"


@pytest.fixture
def wiki_dir():
    """Return the committed baseline wiki/ directory for parser tests.

    At runtime the wiki lives at {workspace}/.openplanter/wiki/, seeded
    from this baseline.  Tests here validate the parser against the
    baseline content which is identical in structure.
    """
    if not WIKI_DIR.is_dir():
        pytest.skip("wiki/ baseline directory not found")
    return WIKI_DIR


class TestParseIndex:
    def test_parses_entries(self, wiki_dir: Path):
        entries = parse_index(wiki_dir)
        assert len(entries) > 0
        names = [e.name for e in entries]
        assert "Massachusetts OCPF" in names
        assert "FEC Federal Campaign Finance" in names
        assert "SEC EDGAR" in names

    def test_categories_assigned(self, wiki_dir: Path):
        entries = parse_index(wiki_dir)
        cats = {e.category for e in entries}
        assert "campaign-finance" in cats
        assert "government-contracts" in cats
        assert "corporate-registries" in cats

    def test_paths_are_relative(self, wiki_dir: Path):
        entries = parse_index(wiki_dir)
        for entry in entries:
            assert not entry.rel_path.startswith("/")
            assert entry.rel_path.endswith(".md")

    def test_returns_empty_for_missing_dir(self, tmp_path: Path):
        entries = parse_index(tmp_path / "nonexistent")
        assert entries == []


# ---------------------------------------------------------------------------
# extract_cross_refs
# ---------------------------------------------------------------------------

class TestExtractCrossRefs:
    def test_extracts_title_and_refs(self, wiki_dir: Path):
        fec_path = wiki_dir / "campaign-finance" / "fec-federal.md"
        if not fec_path.is_file():
            pytest.skip("fec-federal.md not found")
        title, refs = extract_cross_refs(fec_path)
        assert "FEC" in title or "Campaign" in title
        assert len(refs) > 0
        # Should find references to other sources
        ref_lower = [r.lower() for r in refs]
        # FEC cross-refs mention lobbying, corporate, government contracts
        assert any("campaign" in r or "lobbying" in r or "corporate" in r for r in ref_lower)

    def test_returns_empty_for_missing_file(self, tmp_path: Path):
        title, refs = extract_cross_refs(tmp_path / "missing.md")
        assert title == ""
        assert refs == []

    def test_skips_generic_bold_labels(self, tmp_path: Path):
        """Bold text like **Join keys** should not be included."""
        md = tmp_path / "test.md"
        md.write_text(textwrap.dedent("""\
            # Test Source

            ## Cross-Reference Potential

            - **Campaign Finance**: join stuff
            - **Join keys**: entity names

            ## Data Quality
        """))
        title, refs = extract_cross_refs(md)
        assert title == "Test Source"
        assert "Campaign Finance" in refs
        assert "Join keys" not in refs


# ---------------------------------------------------------------------------
# Name registry and fuzzy matching
# ---------------------------------------------------------------------------

class TestNameRegistry:
    def test_builds_from_entries(self):
        entries = [
            WikiEntry(name="Massachusetts OCPF", category="campaign-finance", rel_path="campaign-finance/massachusetts-ocpf.md"),
            WikiEntry(name="Senate Lobbying Disclosures (LD-1/LD-2)", category="lobbying", rel_path="lobbying/senate-ld.md"),
            WikiEntry(name="ProPublica Nonprofit Explorer / IRS 990", category="nonprofits", rel_path="nonprofits/propublica-990.md"),
        ]
        registry = _build_name_registry(entries)
        # Full name
        assert registry["massachusetts ocpf"] == "Massachusetts OCPF"
        # Parenthetical alias
        assert registry["ld-1/ld-2"] == "Senate Lobbying Disclosures (LD-1/LD-2)"
        # Without parenthetical
        assert registry["senate lobbying disclosures"] == "Senate Lobbying Disclosures (LD-1/LD-2)"
        # Slash parts
        assert registry["irs 990"] == "ProPublica Nonprofit Explorer / IRS 990"
        assert registry["propublica nonprofit explorer"] == "ProPublica Nonprofit Explorer / IRS 990"
        # Slug from filename
        assert registry["massachusetts-ocpf"] == "Massachusetts OCPF"
        assert registry["senate-ld"] == "Senate Lobbying Disclosures (LD-1/LD-2)"


class TestMatchReference:
    @pytest.fixture
    def registry(self):
        entries = [
            WikiEntry(name="Massachusetts OCPF", category="campaign-finance", rel_path="campaign-finance/massachusetts-ocpf.md"),
            WikiEntry(name="FEC Federal Campaign Finance", category="campaign-finance", rel_path="campaign-finance/fec-federal.md"),
            WikiEntry(name="Boston Open Checkbook", category="contracts", rel_path="contracts/boston-open-checkbook.md"),
            WikiEntry(name="USASpending.gov", category="contracts", rel_path="contracts/usaspending.md"),
            WikiEntry(name="SAM.gov", category="contracts", rel_path="contracts/sam-gov.md"),
            WikiEntry(name="MA Secretary of Commonwealth", category="corporate", rel_path="corporate/massachusetts-soc.md"),
            WikiEntry(name="SEC EDGAR", category="corporate", rel_path="corporate/sec-edgar.md"),
            WikiEntry(name="Senate Lobbying Disclosures (LD-1/LD-2)", category="lobbying", rel_path="lobbying/senate-ld.md"),
            WikiEntry(name="ProPublica Nonprofit Explorer / IRS 990", category="nonprofits", rel_path="nonprofits/propublica-990.md"),
            WikiEntry(name="OFAC SDN List", category="sanctions", rel_path="sanctions/ofac-sdn.md"),
        ]
        return _build_name_registry(entries)

    def test_exact_match(self, registry):
        assert match_reference("Massachusetts OCPF", registry) == "Massachusetts OCPF"

    def test_case_insensitive(self, registry):
        assert match_reference("massachusetts ocpf", registry) == "Massachusetts OCPF"

    def test_parenthetical_extraction(self, registry):
        # Cross-ref text like "Campaign finance (OCPF, FEC)" — inner part mentions OCPF
        result = match_reference("Campaign finance (OCPF, FEC)", registry)
        # Should match Massachusetts OCPF via substring
        assert result is not None

    def test_substring_match(self, registry):
        # "Lobbying disclosures" is a substring of the canonical name
        result = match_reference("Lobbying disclosures", registry)
        assert result == "Senate Lobbying Disclosures (LD-1/LD-2)"

    def test_slug_match(self, registry):
        assert match_reference("sec-edgar", registry) == "SEC EDGAR"

    def test_no_match_returns_none(self, registry):
        assert match_reference("Completely Unknown Source", registry) is None

    def test_irs_990_match(self, registry):
        result = match_reference("IRS 990 filings", registry)
        assert result == "ProPublica Nonprofit Explorer / IRS 990"


# ---------------------------------------------------------------------------
# WikiGraphModel
# ---------------------------------------------------------------------------

class TestWikiGraphModel:
    def test_rebuild_creates_nodes(self, wiki_dir: Path):
        model = WikiGraphModel(wiki_dir)
        model.rebuild()
        assert model.node_count() > 0

    def test_rebuild_creates_edges(self, wiki_dir: Path):
        model = WikiGraphModel(wiki_dir)
        model.rebuild()
        # Wiki entries cross-reference each other, so there should be edges
        assert model.edge_count() > 0

    def test_nodes_have_category_and_color(self, wiki_dir: Path):
        model = WikiGraphModel(wiki_dir)
        model.rebuild()
        g = model.graph
        for node in g.nodes():
            data = g.nodes[node]
            assert "category" in data
            assert "color" in data
            assert data["category"] in CATEGORY_COLORS

    def test_layout_computed(self, wiki_dir: Path):
        model = WikiGraphModel(wiki_dir)
        model.rebuild()
        assert len(model.layout) == model.node_count()

    def test_render_to_buffer(self, wiki_dir: Path):
        model = WikiGraphModel(wiki_dir)
        model.rebuild()
        buf = model.render_to_buffer(60, 20)
        assert len(buf) == 20
        assert all(len(row) == 60 for row in buf)
        # Should have at least some non-space characters
        chars = [ch for row in buf for ch, _ in row if ch != " "]
        assert len(chars) > 0

    def test_dirty_flag(self, wiki_dir: Path):
        model = WikiGraphModel(wiki_dir)
        assert model.is_dirty
        model.rebuild()
        assert not model.is_dirty
        model.mark_dirty()
        assert model.is_dirty

    def test_empty_wiki_dir(self, tmp_path: Path):
        model = WikiGraphModel(tmp_path)
        model.rebuild()
        assert model.node_count() == 0
        assert model.edge_count() == 0


# ---------------------------------------------------------------------------
# _draw_line (Bresenham)
# ---------------------------------------------------------------------------

class TestDrawLine:
    def test_horizontal_line(self):
        buf = [[(" ", "dim")] * 10 for _ in range(5)]
        _draw_line(buf, 1, 2, 8, 2, 10, 5)
        dots = [(x, y) for y, row in enumerate(buf) for x, (ch, _) in enumerate(row) if ch == "."]
        assert len(dots) > 0
        assert all(y == 2 for x, y in dots)

    def test_vertical_line(self):
        buf = [[(" ", "dim")] * 10 for _ in range(10)]
        _draw_line(buf, 5, 1, 5, 8, 10, 10)
        dots = [(x, y) for y, row in enumerate(buf) for x, (ch, _) in enumerate(row) if ch == "."]
        assert len(dots) > 0
        assert all(x == 5 for x, y in dots)


# ---------------------------------------------------------------------------
# WikiWatcher
# ---------------------------------------------------------------------------

class TestWikiWatcher:
    def test_detects_file_change(self, tmp_path: Path):
        # Create initial file
        md_file = tmp_path / "test.md"
        md_file.write_text("initial")

        changed = threading.Event()
        watcher = WikiWatcher(tmp_path, interval=0.1)
        watcher.start(on_change=lambda: changed.set())

        try:
            # Modify the file
            time.sleep(0.15)
            md_file.write_text("modified")

            # Wait for detection
            assert changed.wait(timeout=2.0), "Watcher did not detect file change"
        finally:
            watcher.stop()

    def test_stop_cleanly(self, tmp_path: Path):
        watcher = WikiWatcher(tmp_path, interval=0.1)
        watcher.start()
        watcher.stop()
        assert watcher._thread is None


# Need threading import at module level
import threading

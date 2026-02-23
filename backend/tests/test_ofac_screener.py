"""Tests for redthread.ofac.screener and redthread.agent.tools.ofac.

All tests use inline SDN fixture data loaded into a tmp_path SQLite
database — no live network calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from redthread.db.sqlite import SQLiteDB
from redthread.ofac.downloader import SDNEntry, load_sdn_to_sqlite
from redthread.ofac.screener import ScreeningHit, _invalidate_cache, screen_entity
from redthread.agent.tools.ofac import screen_ofac


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# A small set of SDN entries covering individuals, entities, and aliases
# for comprehensive screening tests.
FIXTURE_SDN_ENTRIES = [
    SDNEntry(
        uid=1001,
        entry_type="Individual",
        name="Mohammad AL-RASHID",
        program="SDGT",
        aliases=["Mohammed AL RASHEED", "M. RASHID"],
    ),
    SDNEntry(
        uid=1002,
        entry_type="Entity",
        name="PETROLEX TRADING LLC",
        program="IRAN",
        aliases=["PETROLEX IMPORTS", "P.T.L. TRADING"],
    ),
    SDNEntry(
        uid=1003,
        entry_type="Individual",
        name="Carlos GARCIA LOPEZ",
        program="SDNTK",
        aliases=["C. GARCIA"],
    ),
    SDNEntry(
        uid=1004,
        entry_type="Entity",
        name="GOLDEN BRIDGE INVESTMENTS",
        program="UKRAINE-EO13662",
        aliases=[],
    ),
    SDNEntry(
        uid=1005,
        entry_type="Vessel",
        name="MV OCEAN STAR",
        program="CUBA",
        aliases=["OCEAN STAR", "M/V OCEANSTAR"],
    ),
]


@pytest.fixture(autouse=True)
def _clear_cache():
    """Ensure the in-memory SDN cache is cleared before each test."""
    _invalidate_cache()
    yield
    _invalidate_cache()


@pytest.fixture
def sqlite_db(tmp_path: Path) -> SQLiteDB:
    db = SQLiteDB(str(tmp_path / "test_screener.db"))
    load_sdn_to_sqlite(FIXTURE_SDN_ENTRIES, db)
    return db


# ---------------------------------------------------------------------------
# screen_entity — exact match
# ---------------------------------------------------------------------------


class TestScreenEntityExact:
    """Exact or near-exact name matches return confirmed hits."""

    def test_exact_match_returns_confirmed(self, sqlite_db: SQLiteDB):
        """Exact SDN name should return a confirmed hit."""
        hits = screen_entity("Mohammad AL-RASHID", sqlite_db)
        assert len(hits) >= 1
        top = hits[0]
        assert top.sdn_uid == 1001
        assert top.confidence == "confirmed"

    def test_exact_entity_match(self, sqlite_db: SQLiteDB):
        """Exact entity name match returns confirmed."""
        hits = screen_entity("PETROLEX TRADING LLC", sqlite_db)
        assert len(hits) >= 1
        top = hits[0]
        assert top.sdn_uid == 1002
        assert top.confidence == "confirmed"


# ---------------------------------------------------------------------------
# screen_entity — fuzzy / variant match
# ---------------------------------------------------------------------------


class TestScreenEntityFuzzy:
    """Fuzzy name variants return probable or possible hits."""

    def test_fuzzy_variant_returns_hit(self, sqlite_db: SQLiteDB):
        """A spelling variant should return a probable or possible hit."""
        hits = screen_entity("Mohammed AL RASHEED", sqlite_db)
        assert len(hits) >= 1
        # Should match alias "Mohammed AL RASHEED" with high confidence
        top = hits[0]
        assert top.sdn_uid == 1001
        assert top.confidence in ("confirmed", "probable")

    def test_case_insensitive_match(self, sqlite_db: SQLiteDB):
        """Screening is case-insensitive."""
        hits = screen_entity("petrolex trading llc", sqlite_db)
        assert len(hits) >= 1
        assert hits[0].sdn_uid == 1002


# ---------------------------------------------------------------------------
# screen_entity — alias matching
# ---------------------------------------------------------------------------


class TestScreenEntityAliases:
    """Screening checks aliases, not just the primary name."""

    def test_match_on_alias_returns_hit(self, sqlite_db: SQLiteDB):
        """A query matching an alias (not primary name) should produce a hit."""
        hits = screen_entity("PETROLEX IMPORTS", sqlite_db)
        assert len(hits) >= 1
        top = hits[0]
        assert top.sdn_uid == 1002
        assert top.matched_alias == "PETROLEX IMPORTS"

    def test_alias_match_for_individual(self, sqlite_db: SQLiteDB):
        """Alias match for individual."""
        hits = screen_entity("M. RASHID", sqlite_db)
        assert len(hits) >= 1
        top = hits[0]
        assert top.sdn_uid == 1001
        assert top.matched_alias is not None  # matched via alias

    def test_primary_name_match_has_no_alias_field(self, sqlite_db: SQLiteDB):
        """When primary name matches, matched_alias should be None."""
        hits = screen_entity("Mohammad AL-RASHID", sqlite_db)
        assert len(hits) >= 1
        top = hits[0]
        assert top.sdn_uid == 1001
        assert top.matched_alias is None


# ---------------------------------------------------------------------------
# screen_entity — no match
# ---------------------------------------------------------------------------


class TestScreenEntityNoMatch:
    """Names with no SDN matches return empty list."""

    def test_no_match_returns_empty(self, sqlite_db: SQLiteDB):
        hits = screen_entity("Jane Completely Unknown Person", sqlite_db)
        assert hits == []

    def test_empty_name_returns_empty(self, sqlite_db: SQLiteDB):
        hits = screen_entity("", sqlite_db)
        assert hits == []

    def test_whitespace_only_returns_empty(self, sqlite_db: SQLiteDB):
        hits = screen_entity("   ", sqlite_db)
        assert hits == []


# ---------------------------------------------------------------------------
# screen_entity — sorting and top_n
# ---------------------------------------------------------------------------


class TestScreenEntitySorting:
    """Results are sorted by score descending."""

    def test_results_sorted_by_score_descending(self, sqlite_db: SQLiteDB):
        """All returned hits should be in descending score order."""
        # Use a broad query that may match multiple entries
        hits = screen_entity("TRADING", sqlite_db, top_n=50)
        if len(hits) > 1:
            for i in range(len(hits) - 1):
                assert hits[i].match_score >= hits[i + 1].match_score

    def test_top_n_limits_results(self, sqlite_db: SQLiteDB):
        """top_n parameter limits the number of returned hits."""
        hits = screen_entity("Mohammad AL-RASHID", sqlite_db, top_n=1)
        assert len(hits) <= 1


# ---------------------------------------------------------------------------
# screen_ofac tool wrapper
# ---------------------------------------------------------------------------


class TestScreenOfacTool:
    """Tests for the agent tool wrapper screen_ofac()."""

    async def test_tool_returns_matches(self, sqlite_db: SQLiteDB):
        result = await screen_ofac(
            entity_name="Mohammad AL-RASHID",
            investigation_id="inv-001",
            db=sqlite_db,
        )
        assert "Mohammad AL-RASHID" in result
        assert "1001" in result

    async def test_tool_includes_analyst_review_language(self, sqlite_db: SQLiteDB):
        """Response must include 'analyst review' language."""
        result = await screen_ofac(
            entity_name="Mohammad AL-RASHID",
            investigation_id="inv-001",
            db=sqlite_db,
        )
        assert "analyst review" in result.lower()

    async def test_tool_no_matches_still_has_review_language(self, sqlite_db: SQLiteDB):
        """Even a clear result includes review notice."""
        result = await screen_ofac(
            entity_name="Jane Completely Unknown Person",
            investigation_id="inv-001",
            db=sqlite_db,
        )
        assert "no matches" in result.lower()
        assert "analyst review" in result.lower()

    async def test_tool_empty_name_returns_error(self, sqlite_db: SQLiteDB):
        """Empty entity_name returns an error message."""
        result = await screen_ofac(
            entity_name="",
            investigation_id="inv-001",
            db=sqlite_db,
        )
        assert "error" in result.lower()

    async def test_tool_whitespace_name_returns_error(self, sqlite_db: SQLiteDB):
        """Whitespace-only entity_name returns an error message."""
        result = await screen_ofac(
            entity_name="   ",
            investigation_id="inv-001",
            db=sqlite_db,
        )
        assert "error" in result.lower()

    async def test_tool_includes_confidence_info(self, sqlite_db: SQLiteDB):
        """Response includes confidence level information."""
        result = await screen_ofac(
            entity_name="PETROLEX TRADING LLC",
            investigation_id="inv-001",
            db=sqlite_db,
        )
        assert "confidence" in result.lower() or "confirmed" in result.lower()

    async def test_tool_shows_match_count(self, sqlite_db: SQLiteDB):
        """Response states the number of matches found."""
        result = await screen_ofac(
            entity_name="Mohammad AL-RASHID",
            investigation_id="inv-001",
            db=sqlite_db,
        )
        assert "potential match" in result.lower()

"""Tests for redthread.entity.pairwise — Tier 1 pairwise entity resolution.

TDD: These tests were written before the implementation.
Tests the MatchResult dataclass and compare_entities() function.
Pipeline: normalize -> business suffix strip -> human name decomposition
         -> fuzzy score -> phonetic check -> composite score.
Thresholds: >=0.95 confirmed, >=0.80 probable, >=0.60 possible, <0.60 unresolved.
"""

import pytest

from redthread.entity.pairwise import MatchResult, compare_entities


# ---------------------------------------------------------------------------
# MatchResult dataclass
# ---------------------------------------------------------------------------


class TestMatchResultDataclass:
    """MatchResult has the required fields and correct types."""

    def test_fields_exist(self):
        """MatchResult has score, name_similarity, phonetic_match, normalized_a/b, match_type."""
        result = MatchResult(
            score=0.95,
            name_similarity=0.92,
            phonetic_match=True,
            normalized_a="acme",
            normalized_b="acme",
            match_type="exact",
        )
        assert result.score == 0.95
        assert result.name_similarity == 0.92
        assert result.phonetic_match is True
        assert result.normalized_a == "acme"
        assert result.normalized_b == "acme"
        assert result.match_type == "exact"


# ---------------------------------------------------------------------------
# Business entity comparisons (cleanco suffix stripping)
# ---------------------------------------------------------------------------


class TestBusinessEntityComparisons:
    """Test entity comparison with business suffix stripping via cleanco."""

    def test_acme_llc_vs_acme(self):
        """'ACME LLC' vs 'Acme' -> confirmed (suffix stripping + normalization)."""
        result = compare_entities("ACME LLC", "Acme", entity_type="organization")
        assert result.score >= 0.95
        assert result.match_type in ("exact", "fuzzy")

    def test_deutsche_bank_ag_vs_deutsche_bank(self):
        """'Deutsche Bank AG' vs 'Deutsche Bank' -> confirmed (suffix stripping)."""
        result = compare_entities("Deutsche Bank AG", "Deutsche Bank", entity_type="organization")
        assert result.score >= 0.95

    def test_johnson_and_johnson_ampersand(self):
        """'Johnson & Johnson' vs 'Johnson and Johnson' -> confirmed."""
        result = compare_entities(
            "Johnson & Johnson", "Johnson and Johnson", entity_type="organization",
        )
        assert result.score >= 0.95

    def test_different_businesses(self):
        """Completely different business names -> unresolved."""
        result = compare_entities("Acme Corp", "Globex Industries", entity_type="organization")
        assert result.score < 0.60
        assert result.match_type == "weak"


# ---------------------------------------------------------------------------
# Human name comparisons (nameparser decomposition)
# ---------------------------------------------------------------------------


class TestHumanNameComparisons:
    """Test entity comparison with human name decomposition via nameparser."""

    def test_john_smith_vs_smith_john(self):
        """'John Smith' vs 'Smith, John' -> confirmed (name parsing + token sort)."""
        result = compare_entities("John Smith", "Smith, John", entity_type="person")
        assert result.score >= 0.95
        assert result.match_type in ("exact", "fuzzy")

    def test_robert_smith_vs_bob_smith(self):
        """'Robert Smith' vs 'Bob Smith' -> possible (phonetic helps but not exact)."""
        result = compare_entities("Robert Smith", "Bob Smith", entity_type="person")
        # Bob/Robert are different enough that this should be below confirmed
        # but phonetic might help push it into possible range
        assert result.score < 0.95
        assert result.score >= 0.40  # At least not completely unresolved

    def test_identical_names_confirmed(self):
        """Identical names after normalization -> confirmed with high score."""
        result = compare_entities("John Smith", "john smith", entity_type="person")
        assert result.score >= 0.95
        assert result.match_type in ("exact", "fuzzy")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_string_a(self):
        """Empty string input for name_a -> handled gracefully (unresolved, score 0)."""
        result = compare_entities("", "John Smith", entity_type="person")
        assert result.score == 0.0
        assert result.match_type == "weak"

    def test_empty_string_b(self):
        """Empty string input for name_b -> handled gracefully (unresolved, score 0)."""
        result = compare_entities("John Smith", "", entity_type="person")
        assert result.score == 0.0
        assert result.match_type == "weak"

    def test_both_empty(self):
        """Both empty strings -> unresolved, score 0."""
        result = compare_entities("", "", entity_type="person")
        assert result.score == 0.0
        assert result.match_type == "weak"

    def test_completely_different_names(self):
        """'Completely Different' vs 'Something Else' -> unresolved."""
        result = compare_entities("Completely Different", "Something Else")
        assert result.score < 0.60
        assert result.match_type == "weak"

    def test_default_entity_type(self):
        """Entity type defaults to 'unknown' when not specified."""
        result = compare_entities("Test Name", "Test Name")
        assert result.score >= 0.95

    def test_whitespace_handling(self):
        """Names with extra whitespace are normalized."""
        result = compare_entities("  John   Smith  ", "John Smith", entity_type="person")
        assert result.score >= 0.95

    def test_punctuation_handling(self):
        """Names with punctuation differences are normalized."""
        result = compare_entities("O'Brien", "OBrien", entity_type="person")
        assert result.score >= 0.80


# ---------------------------------------------------------------------------
# Threshold classification
# ---------------------------------------------------------------------------


class TestThresholdClassification:
    """Verify that scores map to correct match_type classifications."""

    def test_exact_match_returns_exact_or_fuzzy(self):
        """Exact match after normalization -> match_type is 'exact' or 'fuzzy'."""
        result = compare_entities("ACME", "acme", entity_type="organization")
        assert result.match_type in ("exact", "fuzzy")
        assert result.score >= 0.95

    def test_phonetic_match_detected(self):
        """Names with phonetic similarity have phonetic_match=True."""
        # "Smith" and "Smyth" should have same soundex
        result = compare_entities("Smith", "Smyth", entity_type="person")
        assert result.phonetic_match is True

    def test_normalized_names_returned(self):
        """MatchResult includes the normalized versions of both names."""
        result = compare_entities("ACME LLC", "acme", entity_type="organization")
        # Normalized names should be lowercase and stripped
        assert result.normalized_a == result.normalized_a.lower().strip()
        assert result.normalized_b == result.normalized_b.lower().strip()


# ---------------------------------------------------------------------------
# Composite scoring
# ---------------------------------------------------------------------------


class TestCompositeScoring:
    """Verify composite score weighting behaves correctly."""

    def test_score_bounded_0_to_1(self):
        """Score is always between 0.0 and 1.0 inclusive."""
        # Test various inputs
        test_pairs = [
            ("Acme", "Acme"),
            ("John", "Jane"),
            ("ABC Corp", "XYZ Inc"),
            ("", "test"),
            ("a", "b"),
        ]
        for name_a, name_b in test_pairs:
            result = compare_entities(name_a, name_b)
            assert 0.0 <= result.score <= 1.0, (
                f"Score {result.score} out of bounds for ({name_a!r}, {name_b!r})"
            )

    def test_phonetic_bonus_improves_score(self):
        """Phonetic match adds a bonus to the composite score."""
        # "Smith" vs "Smyth" - similar fuzzy, phonetic match
        result = compare_entities("Smith", "Smyth", entity_type="person")
        assert result.phonetic_match is True
        # The phonetic bonus should help push the score higher
        assert result.score > result.name_similarity * 0.7  # More than just fuzzy weight

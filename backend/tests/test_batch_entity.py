"""Tests for redthread.entity.batch — Tier 2 batch entity resolution.

TDD: These tests were written before the implementation.
Tests the BatchMatchResult dataclass and batch_resolve() function.
The batch resolver can use either splink (preferred) or a fallback
that loops compare_entities() over all record pairs.
"""

import pytest

from redthread.entity.batch import BatchMatchResult, batch_resolve


# ---------------------------------------------------------------------------
# BatchMatchResult dataclass
# ---------------------------------------------------------------------------


class TestBatchMatchResultDataclass:
    """BatchMatchResult has the required fields."""

    def test_fields_exist(self):
        """BatchMatchResult has pairs, total_comparisons, matches_found."""
        result = BatchMatchResult(
            pairs=[{"entity_a": "A", "entity_b": "B", "score": 0.9}],
            total_comparisons=10,
            matches_found=1,
        )
        assert result.pairs == [{"entity_a": "A", "entity_b": "B", "score": 0.9}]
        assert result.total_comparisons == 10
        assert result.matches_found == 1


# ---------------------------------------------------------------------------
# batch_resolve with known duplicates
# ---------------------------------------------------------------------------


class TestBatchResolveWithDuplicates:
    """Batch resolve on records with known duplicates identifies them."""

    def test_identifies_duplicate_names(self):
        """Records with similar names are identified as matches."""
        records = [
            {"unique_id": "1", "name": "Acme Corporation", "entity_type": "organization"},
            {"unique_id": "2", "name": "ACME Corp", "entity_type": "organization"},
            {"unique_id": "3", "name": "Globex Industries", "entity_type": "organization"},
            {"unique_id": "4", "name": "Acme LLC", "entity_type": "organization"},
        ]
        result = batch_resolve(records, match_fields=["name"], threshold=0.80)

        assert result.matches_found > 0
        # Acme Corporation, ACME Corp, and Acme LLC should match each other
        matched_pairs_names = set()
        for pair in result.pairs:
            matched_pairs_names.add((pair["entity_a"], pair["entity_b"]))

        # At least one pair of Acme variants should be matched
        acme_ids = {"1", "2", "4"}
        found_acme_match = False
        for pair in result.pairs:
            if pair["entity_a"] in acme_ids and pair["entity_b"] in acme_ids:
                found_acme_match = True
                break
        assert found_acme_match, "Expected at least one Acme variant pair to match"

    def test_larger_dataset(self):
        """Batch resolve on a larger set of records with known duplicates."""
        records = []
        for i in range(50):
            records.append({
                "unique_id": str(i),
                "name": f"Company {i}",
                "entity_type": "organization",
            })
        # Add some duplicates
        records.append({"unique_id": "100", "name": "Company 0", "entity_type": "organization"})
        records.append({"unique_id": "101", "name": "COMPANY 1", "entity_type": "organization"})
        records.append({"unique_id": "102", "name": "Company 2 LLC", "entity_type": "organization"})

        result = batch_resolve(records, match_fields=["name"], threshold=0.80)

        # Should find the duplicates we added
        assert result.matches_found >= 2  # At least "Company 0" and "COMPANY 1" matches
        assert result.total_comparisons > 0


# ---------------------------------------------------------------------------
# Match result scores
# ---------------------------------------------------------------------------


class TestMatchResultScores:
    """Match results include match probability/score values."""

    def test_results_include_scores(self):
        """Each match pair includes a score."""
        records = [
            {"unique_id": "1", "name": "John Smith", "entity_type": "person"},
            {"unique_id": "2", "name": "Smith, John", "entity_type": "person"},
        ]
        result = batch_resolve(records, match_fields=["name"], threshold=0.60)

        for pair in result.pairs:
            assert "score" in pair
            assert isinstance(pair["score"], (int, float))
            assert 0.0 <= pair["score"] <= 1.0


# ---------------------------------------------------------------------------
# Threshold filtering
# ---------------------------------------------------------------------------


class TestThresholdFiltering:
    """Threshold filtering excludes low-confidence pairs."""

    def test_high_threshold_reduces_matches(self):
        """Higher threshold returns fewer matches."""
        records = [
            {"unique_id": "1", "name": "Acme Corporation", "entity_type": "organization"},
            {"unique_id": "2", "name": "ACME Corp", "entity_type": "organization"},
            {"unique_id": "3", "name": "Globex Industries", "entity_type": "organization"},
        ]
        result_low = batch_resolve(records, match_fields=["name"], threshold=0.50)
        result_high = batch_resolve(records, match_fields=["name"], threshold=0.99)

        assert result_high.matches_found <= result_low.matches_found


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_input_returns_empty(self):
        """Empty input returns empty results."""
        result = batch_resolve([], match_fields=["name"])
        assert result.pairs == []
        assert result.total_comparisons == 0
        assert result.matches_found == 0

    def test_single_record_returns_empty(self):
        """Single record has no pairs to compare."""
        records = [{"unique_id": "1", "name": "Solo Entity", "entity_type": "person"}]
        result = batch_resolve(records, match_fields=["name"])
        assert result.pairs == []
        assert result.total_comparisons == 0
        assert result.matches_found == 0

    def test_missing_field_handled_gracefully(self):
        """Records with missing fields in match columns handled gracefully."""
        records = [
            {"unique_id": "1", "name": "John Smith", "entity_type": "person"},
            {"unique_id": "2", "entity_type": "person"},  # No name field
            {"unique_id": "3", "name": "Jane Doe", "entity_type": "person"},
        ]
        result = batch_resolve(records, match_fields=["name"], threshold=0.60)
        # Should not crash; missing fields treated as empty
        assert isinstance(result, BatchMatchResult)

    def test_results_sorted_by_score_descending(self):
        """Results are sorted by match score descending."""
        records = [
            {"unique_id": "1", "name": "Acme Corporation", "entity_type": "organization"},
            {"unique_id": "2", "name": "ACME Corp", "entity_type": "organization"},
            {"unique_id": "3", "name": "Acme LLC", "entity_type": "organization"},
            {"unique_id": "4", "name": "Deutsche Bank", "entity_type": "organization"},
            {"unique_id": "5", "name": "Deutsche Bank AG", "entity_type": "organization"},
        ]
        result = batch_resolve(records, match_fields=["name"], threshold=0.60)

        if len(result.pairs) > 1:
            scores = [p["score"] for p in result.pairs]
            assert scores == sorted(scores, reverse=True), "Pairs should be sorted by score descending"

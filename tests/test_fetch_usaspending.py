#!/usr/bin/env python3
"""
Unit tests for fetch_usaspending.py

Tests the USASpending.gov API acquisition script by making a small real API call
to verify the endpoint responds correctly. Skips tests if network is unavailable.
"""

import unittest
import sys
import os
import json
import urllib.error

# Add scripts directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

import fetch_usaspending


class TestUsaspendingFetch(unittest.TestCase):
    """Test suite for USASpending.gov data acquisition."""

    @classmethod
    def setUpClass(cls):
        """Check if the API is reachable before running tests."""
        cls.api_available = False
        try:
            # Try a minimal GET request to check connectivity (agencies endpoint)
            response = fetch_usaspending.make_api_request(
                "/references/toptier_agencies/",
                method="GET"
            )
            # Verify we got a valid response structure
            if isinstance(response, dict) and "results" in response:
                cls.api_available = True
                print(f"\nUSASpending.gov API is reachable ({len(response.get('results', []))} agencies found)", file=sys.stderr)
            else:
                print(f"\nSkipping USASpending tests: Unexpected API response format", file=sys.stderr)
        except (urllib.error.URLError, urllib.error.HTTPError, Exception) as e:
            print(f"\nSkipping USASpending tests: API not reachable ({e})", file=sys.stderr)
            cls.api_available = False

    def setUp(self):
        """Skip tests if API is not available."""
        if not self.api_available:
            self.skipTest("USASpending.gov API not available")

    def test_make_api_request_get(self):
        """Test basic GET request to the API."""
        # The agencies endpoint should return a list of federal agencies
        response = fetch_usaspending.make_api_request("/references/toptier_agencies/", method="GET")

        self.assertIsInstance(response, dict)
        self.assertIn("results", response)
        self.assertIsInstance(response["results"], list)
        self.assertGreater(len(response["results"]), 0, "Should return at least one agency")

        # Verify agency structure
        first_agency = response["results"][0]
        self.assertIn("agency_id", first_agency)
        self.assertIn("toptier_code", first_agency)

    def test_make_api_request_post(self):
        """Test POST request to autocomplete endpoint."""
        data = {
            "search_text": "defense",
            "limit": 5
        }

        response = fetch_usaspending.make_api_request(
            "/autocomplete/awarding_agency/",
            method="POST",
            data=data
        )

        self.assertIsInstance(response, dict)
        self.assertIn("results", response)
        self.assertIsInstance(response["results"], list)

        # Autocomplete endpoint returns results with 'id', 'toptier_flag', 'subtier_agency' fields
        # Just verify we got results back - the exact structure may vary
        if len(response["results"]) > 0:
            first_result = response["results"][0]
            # Verify it's a dict with some keys
            self.assertIsInstance(first_result, dict)
            self.assertGreater(len(first_result), 0, "Result should have at least one field")

    def test_search_awards_minimal(self):
        """Test award search with minimal filters (small result set)."""
        # Search for recent contracts, limited to 5 results
        filters = {
            "award_type_codes": ["A", "B", "C", "D"],  # Contracts
            "time_period": [{
                "start_date": "2023-01-01",
                "end_date": "2023-01-31"
            }]
        }

        fields = [
            "Award ID",
            "Recipient Name",
            "Award Amount",
            "Awarding Agency"
        ]

        response = fetch_usaspending.search_awards(
            filters=filters,
            fields=fields,
            limit=5,
            page=1
        )

        # Verify response structure
        self.assertIsInstance(response, dict)
        self.assertIn("results", response)
        self.assertIn("page_metadata", response)

        # Verify results
        results = response["results"]
        self.assertIsInstance(results, list)
        self.assertLessEqual(len(results), 5, "Should respect limit parameter")

        # Verify page metadata
        metadata = response["page_metadata"]
        self.assertIn("page", metadata)
        self.assertIn("hasNext", metadata)
        self.assertIsInstance(metadata.get("total"), (int, type(None)))

        # If there are results, verify structure
        if len(results) > 0:
            first_result = results[0]
            # Check for expected fields (may be None)
            self.assertIn("Award ID", first_result)
            self.assertIn("Recipient Name", first_result)
            self.assertIn("Award Amount", first_result)
            self.assertIn("Awarding Agency", first_result)

    def test_build_filters_comprehensive(self):
        """Test filter building with various combinations."""
        # Test with all parameters
        filters = fetch_usaspending.build_filters(
            award_types=["A", "B", "C"],
            start_date="2023-01-01",
            end_date="2023-12-31",
            recipient="Test Corporation",
            agency="Department of Defense"
        )

        self.assertIn("award_type_codes", filters)
        self.assertEqual(filters["award_type_codes"], ["A", "B", "C"])

        self.assertIn("time_period", filters)
        self.assertEqual(len(filters["time_period"]), 1)
        self.assertEqual(filters["time_period"][0]["start_date"], "2023-01-01")
        self.assertEqual(filters["time_period"][0]["end_date"], "2023-12-31")

        self.assertIn("recipient_search_text", filters)
        self.assertEqual(filters["recipient_search_text"], ["Test Corporation"])

        self.assertIn("agencies", filters)
        self.assertEqual(len(filters["agencies"]), 1)
        self.assertEqual(filters["agencies"][0]["name"], "Department of Defense")

    def test_build_filters_minimal(self):
        """Test filter building with minimal parameters."""
        # Test with only start date
        filters = fetch_usaspending.build_filters(start_date="2023-01-01")

        self.assertIn("time_period", filters)
        self.assertEqual(filters["time_period"][0]["start_date"], "2023-01-01")
        self.assertNotIn("end_date", filters["time_period"][0])

        # Test with empty parameters
        filters_empty = fetch_usaspending.build_filters()
        self.assertEqual(filters_empty, {})

    def test_parse_award_type(self):
        """Test award type parsing."""
        # Test valid types
        contracts = fetch_usaspending.parse_award_type("contracts")
        self.assertEqual(contracts, ["A", "B", "C", "D"])

        grants = fetch_usaspending.parse_award_type("grants")
        self.assertEqual(grants, ["02", "03", "04", "05"])

        loans = fetch_usaspending.parse_award_type("loans")
        self.assertEqual(loans, ["07", "08"])

        # Test case insensitivity
        contracts_upper = fetch_usaspending.parse_award_type("CONTRACTS")
        self.assertEqual(contracts_upper, ["A", "B", "C", "D"])

        # Test invalid type
        with self.assertRaises(ValueError):
            fetch_usaspending.parse_award_type("invalid_type")

    def test_validate_date(self):
        """Test date validation."""
        # Valid dates
        valid_date = fetch_usaspending.validate_date("2023-01-15")
        self.assertEqual(valid_date, "2023-01-15")

        # Invalid formats
        import argparse
        with self.assertRaises(argparse.ArgumentTypeError):
            fetch_usaspending.validate_date("01/15/2023")

        with self.assertRaises(argparse.ArgumentTypeError):
            fetch_usaspending.validate_date("2023-13-01")  # Invalid month

        with self.assertRaises(argparse.ArgumentTypeError):
            fetch_usaspending.validate_date("not-a-date")

    def test_get_default_fields(self):
        """Test default fields list."""
        fields = fetch_usaspending.get_default_fields()

        self.assertIsInstance(fields, list)
        self.assertGreater(len(fields), 0)

        # Check for key expected fields
        expected_fields = [
            "Award ID",
            "Recipient Name",
            "Award Amount",
            "Awarding Agency"
        ]

        for field in expected_fields:
            self.assertIn(field, fields, f"Expected field '{field}' not in default fields")

    def test_api_error_handling(self):
        """Test handling of API errors."""
        # Test with invalid endpoint
        with self.assertRaises(urllib.error.HTTPError):
            fetch_usaspending.make_api_request("/invalid/endpoint/", method="GET")

    def test_search_with_recipient_filter(self):
        """Test searching by recipient name (minimal real request)."""
        # Note: API requires award_type_codes to be present
        filters = fetch_usaspending.build_filters(
            award_types=["A", "B", "C", "D"],  # Contracts
            recipient="Corporation",  # Generic term likely to match
            start_date="2023-01-01",
            end_date="2023-01-15"  # Short window to limit results
        )

        # Note: sort field must be included in fields list
        response = fetch_usaspending.search_awards(
            filters=filters,
            fields=["Award ID", "Recipient Name", "Award Amount"],
            limit=3,
            sort="Award Amount"
        )

        self.assertIsInstance(response, dict)
        self.assertIn("results", response)
        # Results may be empty if no matches in narrow window, that's OK
        self.assertIsInstance(response["results"], list)


if __name__ == "__main__":
    # Run tests with verbose output
    unittest.main(verbosity=2)

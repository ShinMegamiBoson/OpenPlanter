#!/usr/bin/env python3
"""
Unit tests for FDIC BankFind API client.

Tests make small real API calls to validate functionality.
Tests are skipped if network is unavailable.
"""

import json
import sys
import unittest
from pathlib import Path

# Add scripts directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

try:
    import fetch_fdic
    import urllib.error
except ImportError as e:
    raise ImportError(f"Cannot import fetch_fdic module: {e}")


class TestFdicFetch(unittest.TestCase):
    """Test FDIC BankFind API client functionality."""

    def _check_network(self):
        """Skip test if network is unavailable."""
        try:
            fetch_fdic.fetch_fdic("institutions", limit=1)
        except urllib.error.URLError:
            self.skipTest("Network unavailable")

    def test_build_url_basic(self):
        """Test URL building with basic parameters."""
        url = fetch_fdic.build_url("institutions", limit=10, offset=0)
        self.assertIn("https://api.fdic.gov/banks/institutions", url)
        self.assertIn("limit=10", url)
        self.assertIn("offset=0", url)

    def test_build_url_with_filters(self):
        """Test URL building with filters."""
        url = fetch_fdic.build_url(
            "institutions",
            filters="STALP:MA AND ACTIVE:1",
            limit=5
        )
        self.assertIn("filters=STALP:MA", url)
        self.assertIn("ACTIVE:1", url)

    def test_build_url_with_fields(self):
        """Test URL building with field selection."""
        url = fetch_fdic.build_url(
            "institutions",
            fields="NAME,CITY,STALP,CERT",
            limit=5
        )
        self.assertIn("fields=NAME%2CCITY%2CSTALP%2CCERT", url)

    def test_build_url_invalid_endpoint(self):
        """Test that invalid endpoint raises ValueError."""
        with self.assertRaises(ValueError):
            fetch_fdic.build_url("invalid_endpoint")

    def test_fetch_institutions(self):
        """Test fetching institutions data."""
        self._check_network()

        data = fetch_fdic.fetch_fdic("institutions", limit=2)

        # Validate response structure
        self.assertIsInstance(data, dict)
        self.assertIn("meta", data)
        self.assertIn("data", data)
        self.assertIn("total", data["meta"])

        # Validate we got records
        self.assertGreater(len(data["data"]), 0)
        self.assertLessEqual(len(data["data"]), 2)

        # Validate record structure
        first_record = data["data"][0]
        self.assertIn("data", first_record)
        record_data = first_record["data"]

        # Check for key fields
        self.assertIn("NAME", record_data)
        self.assertIn("CERT", record_data)
        self.assertIn("CITY", record_data)
        self.assertIn("STALP", record_data)

    def test_fetch_failures(self):
        """Test fetching bank failures data."""
        self._check_network()

        data = fetch_fdic.fetch_fdic("failures", limit=2)

        # Validate response structure
        self.assertIsInstance(data, dict)
        self.assertIn("meta", data)
        self.assertIn("data", data)

        # Validate we got records
        self.assertGreater(len(data["data"]), 0)

        # Validate record structure
        first_record = data["data"][0]
        self.assertIn("data", first_record)
        record_data = first_record["data"]

        # Check for key fields
        self.assertIn("NAME", record_data)
        self.assertIn("FAILDATE", record_data)

    def test_fetch_locations(self):
        """Test fetching branch locations data."""
        self._check_network()

        data = fetch_fdic.fetch_fdic("locations", limit=2)

        # Validate response structure
        self.assertIsInstance(data, dict)
        self.assertIn("meta", data)
        self.assertIn("data", data)

        # Validate we got records
        self.assertGreater(len(data["data"]), 0)

        # Validate record structure
        first_record = data["data"][0]
        self.assertIn("data", first_record)
        record_data = first_record["data"]

        # Check for key fields
        self.assertIn("NAME", record_data)
        self.assertIn("OFFNAME", record_data)
        self.assertIn("CITY", record_data)

    def test_fetch_history(self):
        """Test fetching history data."""
        self._check_network()

        data = fetch_fdic.fetch_fdic("history", limit=2)

        # Validate response structure
        self.assertIsInstance(data, dict)
        self.assertIn("meta", data)
        self.assertIn("data", data)

        # Validate we got records
        self.assertGreater(len(data["data"]), 0)

        # Validate record structure
        first_record = data["data"][0]
        self.assertIn("data", first_record)
        record_data = first_record["data"]

        # Check for key fields
        self.assertIn("INSTNAME", record_data)
        self.assertIn("CERT", record_data)

    def test_fetch_summary(self):
        """Test fetching summary data."""
        self._check_network()

        data = fetch_fdic.fetch_fdic("summary", limit=2)

        # Validate response structure
        self.assertIsInstance(data, dict)
        self.assertIn("meta", data)
        self.assertIn("data", data)

        # Validate we got records
        self.assertGreater(len(data["data"]), 0)

        # Validate record structure
        first_record = data["data"][0]
        self.assertIn("data", first_record)
        record_data = first_record["data"]

        # Check for key fields
        self.assertIn("STNAME", record_data)
        self.assertIn("YEAR", record_data)

    def test_fetch_financials(self):
        """Test fetching financial data."""
        self._check_network()

        data = fetch_fdic.fetch_fdic("financials", limit=2)

        # Validate response structure
        self.assertIsInstance(data, dict)
        self.assertIn("meta", data)
        self.assertIn("data", data)

        # Validate we got records
        self.assertGreater(len(data["data"]), 0)

        # Validate record structure
        first_record = data["data"][0]
        self.assertIn("data", first_record)
        record_data = first_record["data"]

        # Check for key fields
        self.assertIn("CERT", record_data)
        self.assertIn("ASSET", record_data)

    def test_fetch_with_filter(self):
        """Test fetching with filter parameter."""
        self._check_network()

        # Filter for active Massachusetts banks
        data = fetch_fdic.fetch_fdic(
            "institutions",
            filters="STALP:MA AND ACTIVE:1",
            limit=5
        )

        self.assertIsInstance(data, dict)
        self.assertGreater(len(data["data"]), 0)

        # Validate filter was applied
        for record in data["data"]:
            record_data = record["data"]
            self.assertEqual(record_data["STALP"], "MA")
            self.assertEqual(record_data["ACTIVE"], 1)

    def test_fetch_with_fields(self):
        """Test fetching with field selection."""
        self._check_network()

        # Request specific fields only
        data = fetch_fdic.fetch_fdic(
            "institutions",
            fields="NAME,CITY,STALP,CERT",
            limit=2
        )

        self.assertIsInstance(data, dict)
        self.assertGreater(len(data["data"]), 0)

        # Validate only requested fields are present (plus ID field)
        first_record = data["data"][0]["data"]
        expected_fields = {"NAME", "CITY", "STALP", "CERT", "ID"}

        # The API may return a few extra fields, but requested ones must be present
        for field in expected_fields:
            if field != "ID":  # ID is internal
                self.assertIn(field, first_record,
                            f"Expected field {field} not in response")

    def test_fetch_with_pagination(self):
        """Test pagination with offset and limit."""
        self._check_network()

        # Get first page
        page1 = fetch_fdic.fetch_fdic("institutions", limit=2, offset=0)

        # Get second page
        page2 = fetch_fdic.fetch_fdic("institutions", limit=2, offset=2)

        # Validate different records returned
        self.assertIsInstance(page1, dict)
        self.assertIsInstance(page2, dict)

        if len(page1["data"]) > 0 and len(page2["data"]) > 0:
            page1_first_id = page1["data"][0]["data"].get("ID")
            page2_first_id = page2["data"][0]["data"].get("ID")

            # Records should be different
            self.assertNotEqual(page1_first_id, page2_first_id)

    def test_fetch_csv_format(self):
        """Test fetching CSV format."""
        self._check_network()

        data = fetch_fdic.fetch_fdic(
            "institutions",
            limit=2,
            output_format="csv"
        )

        # CSV should be a string
        self.assertIsInstance(data, str)

        # Should have header row
        lines = data.strip().split("\n")
        self.assertGreater(len(lines), 1)

        # First line should be header with comma-separated fields
        header = lines[0]
        self.assertIn(",", header)

    def test_invalid_endpoint_raises_error(self):
        """Test that invalid endpoint raises ValueError."""
        with self.assertRaises(ValueError):
            fetch_fdic.fetch_fdic("invalid_endpoint")


def run_tests():
    """Run all tests with verbose output."""
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestFdicFetch)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
